"""TC-WH(일회용 PG) — 알림 단위 중복 선점 · 동시 요청 · 지연 · 필수 칸 (설계 3.6 #3 ~ #5 · ①-08).
주문 의도 · 위험 관문은 오준영 님 PR #368(`paper_order_control`)이 맡는다 — 여기서는 가짜 주문으로 호출 인자(signal_key · strategy_id)만 본다.

QURIOUS_TEST_DATABASE_URL 이 없으면 건너뛴다. 주문(`pt.stock_order`)은 가짜로 바꿔 몇 번 불렸는지 센다.
"""
import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import ApiKey, User, WebhookSignal
from app.services import paper_trading as pt
from app.services import tradingview as tv

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]

NOW = datetime(2026, 10, 28, 5, 30, 0, tzinfo=timezone.utc)
BAR = "2026-10-28T00:00:00Z"


def alert(token, **over):
    p = {"token": token, "ticker": "KRX:005930", "action": "buy", "contracts": "2", "price": "70000",
         "strategy": "MA 교차", "strategy_id": "ma-cross", "strategy_version": 1,
         "bar_time": BAR, "sent_at": "2026-10-28T05:29:50Z"}
    p.update(over)
    return p


def mocks(monkeypatch, order=None):
    place = AsyncMock(side_effect=order) if order else AsyncMock(return_value={"symbol": "005930", "price": 70000, "name": "삼성전자"})
    monkeypatch.setattr(tv.pt, "stock_order", place)
    return place


def run(coro):
    async def go():
        engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            token = f"qk_test_{uuid.uuid4().hex}"
            async with factory() as db:
                uid = uuid.uuid4()
                db.add(User(id=uid, name="wh test", email=f"{uid}@example.com", client_id=uid.hex, password_hash="test"))
                await db.flush()
                db.add(ApiKey(user_id=uid, key_prefix=token[:12], key_hash=hashlib.sha256(token.encode()).hexdigest()))
                await db.commit()
            await coro(factory, uid, token)
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM webhook_signals"))
                await conn.execute(text("DELETE FROM api_keys"))
                await conn.execute(text("DELETE FROM users WHERE name = 'wh test'"))
            await engine.dispose()
    asyncio.run(go())


async def fire(factory, token, payload, now=NOW):
    """라우트가 하는 일: 토큰 조회 → handle_alert → 커밋(세션 하나가 요청 하나)."""
    async with factory() as db:
        key = await tv.resolve_user_by_token(db, token)
        res = await tv.handle_alert(db, payload, key=key, now=now)
        await db.commit()
        return res["signal"]


async def rows(factory, uid):
    async with factory() as db:
        return (await db.execute(select(WebhookSignal).where(WebhookSignal.user_id == uid)
                                 .order_by(WebhookSignal.created_at))).scalars().all()


def test_first_alert_fills_and_records_key_and_delay(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        sig = await fire(factory, token, alert(token))
        assert sig["status"] == "filled" and sig["fill_price"] == 70000.0 and sig["delay_sec"] == 10.0
        (row,) = await rows(factory, uid)
        assert len(row.dedup_key) == 64 and row.dup_count == 0 and row.delay_sec == 10.0
        assert "token" not in row.payload and row.payload["strategy_id"] == "ma-cross"
        place.assert_awaited_once()
    run(go)


def test_same_alert_again_is_one_order_and_marks_the_first_row(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        assert (await fire(factory, token, alert(token)))["status"] == "filled"
        # 같은 알림이 다시 — 시각 표기가 달라도(같은 순간) 같은 알림이다
        again = await fire(factory, token, alert(token, bar_time="2026-10-28T09:00:00+09:00"))
        assert again["status"] == "duplicate" and "추가 주문 없음" in again["message"] and "filled" in again["message"]
        assert (await fire(factory, token, alert(token)))["status"] == "duplicate"
        rs = await rows(factory, uid)
        first, dups = rs[0], rs[1:]
        assert first.status == "filled" and first.dup_count == 2 and first.dedup_key
        assert [d.status for d in dups] == ["duplicate", "duplicate"] and all(d.dedup_key is None for d in dups)  # 받은 횟수가 줄로 남는다
        place.assert_awaited_once()
        assert place.await_args.kwargs["signal_key"] == BAR and place.await_args.kwargs["strategy_id"] == "tv:ma-cross"
    run(go)


def test_other_bar_or_other_side_is_a_new_alert(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        await fire(factory, token, alert(token))
        assert (await fire(factory, token, alert(token, bar_time="2026-10-29T00:00:00Z", sent_at="2026-10-28T05:29:55Z")))["status"] == "filled"
        assert (await fire(factory, token, alert(token, action="sell")))["status"] == "filled"
        assert (await fire(factory, token, alert(token, strategy_version=2)))["status"] == "filled"
        assert (await fire(factory, token, alert(token, strategy_id="other")))["status"] == "filled"
        assert len(await rows(factory, uid)) == 5 and place.await_count == 5
    run(go)


def test_concurrent_identical_alerts_place_exactly_one_order(monkeypatch):
    async def slow_order(*a, **kw):
        await asyncio.sleep(0.3)  # 첫 요청이 주문하는 동안 둘째가 들어오게 창을 넓힌다
        return {"symbol": "005930", "price": 70000, "name": "삼성전자"}
    place = mocks(monkeypatch, order=slow_order)
    async def go(factory, uid, token):
        results = await asyncio.gather(*[fire(factory, token, alert(token)) for _ in range(4)])
        assert sorted(r["status"] for r in results) == ["duplicate", "duplicate", "duplicate", "filled"]
        assert place.await_count == 1                      # 주문은 한 번
        rs = await rows(factory, uid)                       # 줄은 받은 만큼, 채운 것은 하나
        assert len(rs) == 4 and [r.status for r in rs if r.status == "filled"] == ["filled"]
        assert next(r for r in rs if r.dedup_key).dup_count == 3
    run(go)


def test_missing_signal_or_bad_times_are_recorded_as_rejected_format_without_order(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        for over in ({"bar_time": ""}, {"sent_at": "어제"}, {"sent_at": "2026-10-28T06:30:00Z"}):   # 마지막: 한 시간 뒤 — 시계가 앞선 알림
            sig = await fire(factory, token, alert(token, **over))
            assert sig["status"] == "rejected_format", over
        assert place.await_count == 0
        rs = await rows(factory, uid)
        assert len(rs) == 3 and all(r.dedup_key is None for r in rs)   # 거부는 중복 키를 쓰지 않는다
    run(go)


def test_strategy_id_may_be_omitted_and_the_strategy_name_is_used(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        p = alert(token); del p["strategy_id"]
        assert (await fire(factory, token, p))["status"] == "filled"
        assert place.await_args.kwargs["strategy_id"] == "tv:MA 교차"
        assert (await fire(factory, token, p))["status"] == "duplicate"   # 같은 전략 이름 · 같은 봉 = 같은 알림
        assert place.await_count == 1
    run(go)


def test_signal_id_alone_is_enough_and_is_the_signal_key(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        p = alert(token, signal_id="sig-77"); del p["bar_time"]
        assert (await fire(factory, token, p))["status"] == "filled"
        assert place.await_args.kwargs["signal_key"] == "sig-77"
    run(go)


def test_without_sent_at_a_daily_bar_open_time_is_not_late(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        p = alert(token, bar_time="2026-10-27T00:00:00Z"); del p["sent_at"]
        assert (await fire(factory, token, p))["status"] == "filled" and place.await_count == 1
    run(go)


def test_late_alert_is_recorded_without_order_and_does_not_burn_the_key(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        late = await fire(factory, token, alert(token, sent_at="2026-10-28T05:24:00Z"))   # 6분 전
        assert late["status"] == "late" and late["delay_sec"] == 360.0 and place.await_count == 0
        # 같은 봉의 제때 온 알림은 정상 처리된다 — 늦은 알림이 키를 태우지 않았다
        assert (await fire(factory, token, alert(token)))["status"] == "filled"
        assert place.await_count == 1
    run(go)


def test_alert_only_signals_need_no_fields_and_are_not_deduplicated(monkeypatch):
    place = mocks(monkeypatch)
    async def go(factory, uid, token):
        plain = {"token": token, "ticker": "005930", "comment": "알림만"}
        a = await fire(factory, token, plain)
        b = await fire(factory, token, plain)
        dry = await fire(factory, token, alert(token, dry_run="true"))
        assert a["status"] == b["status"] == dry["status"] == "alert"
        rs = await rows(factory, uid)
        assert len(rs) == 3 and all(r.dedup_key is None for r in rs)   # NULL 키는 여러 줄이어도 된다
        assert place.await_count == 0
    run(go)


def test_order_error_keeps_the_claim_and_never_retries_automatically(monkeypatch):
    place = mocks(monkeypatch, order=pt.PaperTradeError("잔고 부족"))
    async def go(factory, uid, token):
        first = await fire(factory, token, alert(token))
        assert first["status"] == "error" and "잔고 부족" in first["message"]
        again = await fire(factory, token, alert(token))
        assert again["status"] == "duplicate" and "error" in again["message"]
        assert place.await_count == 1                          # 같은 알림으로 주문을 다시 내지 않는다
    run(go)


def test_unknown_and_revoked_tokens_are_401(monkeypatch):
    mocks(monkeypatch)
    async def go(factory, uid, token):
        for bad in ("", "nope", token + "x"):
            async with factory() as db:
                with pytest.raises(tv.WebhookError) as exc:
                    await tv.resolve_user_by_token(db, bad)
                assert exc.value.status == 401
        async with factory() as db:
            await db.execute(text("UPDATE api_keys SET is_active = false"))
            await db.commit()
        async with factory() as db:
            with pytest.raises(tv.WebhookError) as exc:
                await tv.resolve_user_by_token(db, token)
            assert exc.value.status == 401 and exc.value.code == "rejected_auth"
    run(go)


def test_call_count_and_last_used_are_updated_even_for_duplicates(monkeypatch):
    mocks(monkeypatch)
    async def go(factory, uid, token):
        await fire(factory, token, alert(token))
        await fire(factory, token, alert(token))
        async with factory() as db:
            key = (await db.execute(select(ApiKey).where(ApiKey.user_id == uid))).scalar_one()
            assert key.call_count == 2 and key.last_used_at == NOW
    run(go)
