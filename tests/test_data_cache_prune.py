"""TC-DCP — 외부 시세 캐시 정리 (app/services/data_cache.py `prune_external` · 할 일 ①-29 · 2026-10-30)

`data_cache` 는 외부 시세 캐시와 함께 상태 · 결과(자동매매 사이클 로그 · 대사 기준선 · 모델 비교 결과 · AI 예측)도 담는다.
나이만 보고 지우면 상태가 사라지므로 **허용 목록 키만** 지운다. 가짜 세션으로 실제 SQL 을 만들어 본다(DB 없이).
1. 허용 목록 판정 — 외부 시세 키는 True · 상태 · 결과 키는 False. (TC-DCP-01)
2. 실제 코드의 캐시 키와 어긋나지 않는다 — 코드에 쓰이는 접두사가 목록에 있고, 상태 키는 목록에 없다. (TC-DCP-02)
3. 지우는 SQL — 허용 목록 조건 + 나이 조건이 붙고 `quant:` · `ai_predict:` 는 안 걸린다 · dry_run 은 지우지 않는다 · 1일 아래는 거부. (TC-DCP-03)
4. 하루 한 번 작업으로 예약돼 있다. (TC-DCP-04)
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import data_cache as dc  # noqa: E402


def test_allowlist_judgement():
    """TC-DCP-01 · 외부 시세 캐시는 정리 대상, 상태 · 결과 키는 아니다."""
    for k in ("candles:005930:1y:1d", "candles:kis:005930:1y:1d", "indicators:AAPL:2y", "fundamentals:005930",
              "market_indices", "macro_indicators", "sector_etfs", "us_stocks", "krx_company_list"):
        assert dc.is_external_key(k), k
    for k in ("quant:cycle_log:123", "quant:reconcile:baseline:u:env", "quant:reconcile:latest:u", "quant:last_beat_run",
              "ai_predict:v4:005930", "model_compare:abc", "", "candle", "indicator:x"):
        assert not dc.is_external_key(k), k


def test_allowlist_matches_keys_used_in_code_and_never_covers_state_keys():
    """TC-DCP-02 · 코드에서 쓰는 외부 시세 키 접두사가 목록에 있고(드리프트 방지), 상태 키 접두사는 목록에 없다."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app").rglob("*.py") if p.name != "data_cache.py")
    for prefix in dc.EXTERNAL_KEY_PREFIXES:
        assert re.search(r'f?["\']' + re.escape(prefix), src), f"코드에서 안 쓰는 접두사가 목록에 있다: {prefix}"
    for key in dc.EXTERNAL_KEYS:
        assert f'"{key}"' in src, f"코드에서 안 쓰는 키가 목록에 있다: {key}"
    for state_prefix in ("quant:", "ai_predict:"):
        assert state_prefix in src, f"상태 키 접두사 {state_prefix} 가 코드에서 사라졌다 — 이 시험을 갱신한다"
        assert not any(state_prefix.startswith(p) or p.startswith(state_prefix) for p in dc.EXTERNAL_KEY_PREFIXES)
        assert state_prefix not in dc.EXTERNAL_KEYS


class _FakeSession:
    def __init__(self, log, count=3):
        self.log, self.count = log, count

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        self.log.append(str(stmt.compile(dialect=postgresql.dialect())))
        return SimpleNamespace(rowcount=self.count, scalar_one=lambda: self.count)

    async def commit(self):
        self.log.append("COMMIT")


def _run(monkeypatch, *args, **kw):
    log: list[str] = []
    monkeypatch.setattr(dc, "get_session_factory", lambda: (lambda: _FakeSession(log)))
    return log, asyncio.run(dc.prune_external(*args, **kw))


def test_prune_sql_is_limited_to_allowlist_and_age(monkeypatch):
    """TC-DCP-03 · 지우는 SQL 은 나이 조건 + 허용 목록 조건이고 · dry_run 은 세기만 하며 · 1일 아래는 거부한다."""
    log, out = _run(monkeypatch)
    sql = log[0]
    assert sql.startswith("DELETE FROM data_cache") and "updated_at <" in sql and "LIKE" in sql and " IN " in sql
    assert "quant" not in sql and "ai_predict" not in sql
    assert log[-1] == "COMMIT" and out["deleted"] == 3 and out["dry_run"] is False and out["would_delete"] is None
    log, out = _run(monkeypatch, dry_run=True)
    assert log[0].startswith("SELECT count") and "COMMIT" not in log and out["deleted"] == 0 and out["would_delete"] == 3
    for bad in (0, 0.5, -1):
        with pytest.raises(ValueError, match="1 이상"):
            asyncio.run(dc.prune_external(bad))
    assert dc.PRUNE_DEFAULT_DAYS >= 7 * dc.PRUNE_MIN_DAYS, "읽는 쪽 최대 나이(24시간)보다 훨씬 길게"


def test_prune_is_scheduled_once_a_day_as_a_registered_task():
    """TC-DCP-04 · 비트가 등록 이름으로 하루 한 번 부른다(이름이 어긋나면 워커가 버린다 — celery_app 주석)."""
    from app.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["prune-external-cache-daily"]
    assert entry["task"] == "sync.prune_external_cache"
    from app.tasks import sync_tasks
    assert sync_tasks.prune_external_cache.name == "sync.prune_external_cache"
    rep = repr(entry["schedule"]).replace(" ", "")
    assert "crontab" in rep.lower() and "3" in rep
