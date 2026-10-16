"""환율 변환 — 해외 종목 시세를 원화(KRW)로 환산한다.

Yahoo Finance 통화쌍 심볼(USD→KRW: "KRW=X", 그 외: "{CUR}KRW=X")을 10분 캐시로 조회한다.
조회 실패 시 마지막 성공값을 쓰고, 그것도 없으면 보수적 기본값(USD 1,350원)을 사용해 서비스가 멈추지 않게 한다.

쓴 값이 무엇인지는 말없이 넘기지 않는다(2026-10-16 · 시장 범위 조사서 D12 「말없는 fallback」) — `rate_info` 가
환율과 함께 출처(live 10분 안에 받은 값 · last 지금 조회가 실패해 마지막 성공값 · fallback 받은 적 없어 고정 대체값 ·
missing 대체값도 없어 1) · 받은 시각 · 화면에 그대로 보일 한 줄을 준다(글은 여기 한 곳). 동작(어느 값을 쓰나)은
그대로이고, 대체값일 때 주문을 막을지는 모의투자 주담당이 정한다. 옛 약속(`get_rate_to_krw` · `to_krw`)도 그대로다.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_CACHE: dict[str, dict] = {}
_TTL = 600
_FALLBACK = {"USD": 1350.0, "JPY": 9.0, "EUR": 1480.0, "HKD": 173.0, "CNY": 187.0, "GBP": 1720.0}


def fx_symbol(currency: str) -> str:
    cur = (currency or "").upper()
    return "KRW=X" if cur == "USD" else f"{cur}KRW=X"


def _as_of(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=KST).isoformat(timespec="seconds")


def _info(cur: str, rate: float, source: str, ts: float | None) -> dict:
    """환율 한 건과 그 출처 · 받은 시각 · 화면 글."""
    when = None if ts is None else datetime.fromtimestamp(ts, tz=KST).strftime("%m-%d %H:%M")
    if source == "live":
        note = f"받은 환율 1 {cur} = {rate:,.2f}원 · {when} 기준"
    elif source == "last":
        note = f"지금 환율을 받지 못해 마지막으로 받은 값을 씀 — 1 {cur} = {rate:,.2f}원 · {when} 기준"
    elif source == "fallback":
        note = f"대체 환율 — 환율을 받지 못해 고정값 1 {cur} = {rate:,.0f}원을 씀(실제 환율과 다를 수 있음)"
    else:
        note = f"환율 없음 — {cur} 환율을 받지 못했고 대체값도 없어 1 로 계산함(금액이 크게 틀릴 수 있음)"
    return {"rate": rate, "source": source, "as_of": _as_of(ts), "note": note}


async def rate_info(currency: str | None) -> dict:
    """1 {currency} = ? KRW 와 그 출처 — {"rate", "source", "as_of", "note"}.

    source: None(원화 · 환산 없음) | "live"(10분 안에 받은 값) | "last"(지금 조회 실패 · 마지막 성공값)
            | "fallback"(받은 적 없음 · 고정 대체값) | "missing"(대체값도 없는 통화 · 1 로 계산 — 크게 틀릴 수 있음)
    as_of: 그 값을 받은 시각(KST · ISO) — 대체값은 None.
    """
    cur = (currency or "KRW").upper()
    if cur in ("KRW", ""):
        return {"rate": 1.0, "source": None, "as_of": None, "note": None}
    now = time.time()
    hit = _CACHE.get(cur)
    if hit and now - hit["ts"] < _TTL:
        return _info(cur, hit["rate"], "live", hit["ts"])
    try:
        from app.services.stock import get_quote
        q = await get_quote(fx_symbol(cur))
        rate = float(q.get("price") or 0)
        if rate > 0:
            _CACHE[cur] = {"ts": now, "rate": rate}
            return _info(cur, rate, "live", now)
    except Exception as exc:
        logger.warning("환율 조회 실패 %s: %s", cur, exc)
    if hit:
        return _info(cur, hit["rate"], "last", hit["ts"])
    if cur in _FALLBACK:
        return _info(cur, _FALLBACK[cur], "fallback", None)
    return _info(cur, 1.0, "missing", None)


async def get_rate_to_krw(currency: str) -> float:
    """1 {currency} = ? KRW — 숫자만(옛 약속). 출처까지 필요하면 `rate_info`."""
    return (await rate_info(currency))["rate"]


async def to_krw(price: float, currency: str) -> tuple[float, float]:
    """(원화 환산 가격, 적용 환율)."""
    rate = await get_rate_to_krw(currency)
    return float(price) * rate, rate


async def to_krw_info(price: float, currency: str) -> tuple[float, dict]:
    """(원화 환산 가격, `rate_info` 한 건) — 환산 값과 출처가 같은 한 번의 조회에서 온다."""
    info = await rate_info(currency)
    return float(price) * info["rate"], info
