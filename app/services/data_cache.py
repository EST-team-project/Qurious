"""PostgreSQL-backed data cache with internet connectivity detection.

When internet is available, callers can fetch live data and store it here.
When offline, callers read stale-but-valid cached data.
"""
import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.postgres import get_session_factory
from app.models import DataCache

logger = logging.getLogger(__name__)

# Connectivity probe: lightweight HEAD request to Yahoo Finance
_PROBE_URL = "https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d"


#: 정리해도 되는 **외부 시세 캐시** — 다시 받을 수 있고, 읽는 쪽이 허용하는 나이가 모두 24시간 이하(6 · 3 · 2 · 24시간)인 것만 둔다(할 일 ①-29).
#: 이 표(`data_cache`)에는 상태 · 결과도 함께 들어 있어서(자동매매 사이클 로그 `quant:cycle_log:*` · 대사 기준선 `quant:reconcile:*` ·
#: 모델 비교 작업 결과 · AI 예측 `ai_predict:*`) **허용 목록에 없는 키는 절대 지우지 않는다.**
EXTERNAL_KEY_PREFIXES = ("candles:", "indicators:", "fundamentals:")
EXTERNAL_KEYS = ("market_indices", "macro_indicators", "sector_etfs", "us_stocks", "krx_company_list")
#: 이보다 오래된 줄만 지운다. 읽는 쪽 최대 나이(24시간)보다 훨씬 길게 잡아 한 번 늦게 돌아도 읽을 줄을 안 지운다.
PRUNE_DEFAULT_DAYS = 7
PRUNE_MIN_DAYS = 1


def is_external_key(key: str) -> bool:
    """정리 대상(외부 시세 캐시)인가 — 허용 목록 · 접두사에 든 키만 True."""
    return key in EXTERNAL_KEYS or key.startswith(EXTERNAL_KEY_PREFIXES)


def _external_condition():
    return or_(*[DataCache.key.startswith(p, autoescape=True) for p in EXTERNAL_KEY_PREFIXES], DataCache.key.in_(EXTERNAL_KEYS))


async def prune_external(max_age_days: float = PRUNE_DEFAULT_DAYS, *, dry_run: bool = False) -> dict:
    """나이 지난 외부 시세 캐시를 지운다(하루 한 번 · Celery). `dry_run` 이면 세기만 한다.

    허용 목록(`EXTERNAL_KEY_PREFIXES` · `EXTERNAL_KEYS`)에 든 키만 건드리고, `max_age_days` 는 읽는 쪽 최대 나이(24시간)를 지키려고
    1일 아래로 못 준다. 실패하면 예외를 그대로 올린다(조용히 삼키지 않는다 — 작업이 실패로 기록되게).
    """
    if max_age_days < PRUNE_MIN_DAYS:
        raise ValueError(f"max_age_days 는 {PRUNE_MIN_DAYS} 이상이어야 한다(읽는 쪽이 24시간까지 쓴다): {max_age_days}")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    where = (DataCache.updated_at < cutoff) & _external_condition()
    session_factory = get_session_factory()
    async with session_factory() as db:
        if dry_run:
            n = (await db.execute(select(func.count()).select_from(DataCache).where(where))).scalar_one()
        else:
            n = (await db.execute(delete(DataCache).where(where))).rowcount or 0
            await db.commit()
    logger.info("[prune_external] %s %d줄 (기준 %s)", "지울 것" if dry_run else "지움", n, cutoff.isoformat())
    return {"deleted": 0 if dry_run else int(n), "would_delete": int(n) if dry_run else None,
            "cutoff": cutoff.isoformat(), "dry_run": dry_run}


async def is_internet_available() -> bool:
    """Return True if the external internet is reachable."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.head(_PROBE_URL)
            return r.status_code < 500
    except Exception:
        return False


async def cache_get(key: str, max_age_hours: float = 24) -> dict | None:
    """Return cached payload if it exists and is fresher than max_age_hours.

    Returns None when the key is missing or stale.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(select(DataCache).where(DataCache.key == key))
            row = result.scalar_one_or_none()
        if not row:
            return None
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - updated_at
        if age > timedelta(hours=max_age_hours):
            return None
        return row.data
    except Exception as e:
        logger.warning("[cache_get] %s: %s", key, e)
        return None


async def cache_set(key: str, data) -> None:
    """Upsert a cached payload."""
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            stmt = pg_insert(DataCache).values(key=key, data=data, updated_at=func.now())
            stmt = stmt.on_conflict_do_update(
                index_elements=[DataCache.key], set_={"data": data, "updated_at": func.now()}
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.warning("[cache_set] %s: %s", key, e)


async def cache_info(key: str) -> dict | None:
    """Return {updated_at, age_minutes} for a cache key, or None."""
    try:
        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(select(DataCache.updated_at).where(DataCache.key == key))
            updated_at = result.scalar_one_or_none()
        if not updated_at:
            return None
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - updated_at
        return {
            "key": key,
            "updated_at": updated_at.isoformat(),
            "age_minutes": round(age.total_seconds() / 60, 1),
        }
    except Exception:
        return None
