"""이슈 #297 — 위험 관문 시작 자산 키가 장부마다 분리되는지."""
import pytest
from app.services import risk_guard


async def _clear(uid_suffix: str):
    r = risk_guard._redis()
    if r is not None:
        key = f"quant:day-equity:{uid_suffix}:{risk_guard.today_key()}"
        try:
            await r.delete(key)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_paper_and_quant_keys_are_separate():
    uid = "297-test-a"
    await _clear(f"{uid}:paper")
    await _clear(f"{uid}:quant")

    # 패턴 화면 먼저 (모의계좌 1억)
    paper_start = await risk_guard.day_start_equity(f"{uid}:paper", 100_012_485.0)
    # 자동매매 다음 (퀀트 장부 1천만)
    quant_start = await risk_guard.day_start_equity(f"{uid}:quant", 10_354_432.0)

    assert paper_start == 100_012_485.0
    assert quant_start == 10_354_432.0


@pytest.mark.asyncio
async def test_same_ledger_locks_first_value():
    uid = "297-test-b"
    await _clear(f"{uid}:quant")

    first = await risk_guard.day_start_equity(f"{uid}:quant", 10_000_000.0)
    second = await risk_guard.day_start_equity(f"{uid}:quant", 8_000_000.0)

    assert first == 10_000_000.0
    assert second == 10_000_000.0   # nx=True 로 첫 값 고정 (기존 동작 유지)