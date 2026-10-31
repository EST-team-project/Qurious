"""TC-ECH — 웹훅 → 기록 → 알림 → DB 한 흐름 (3차 ①-22 · 2026-10-31)

TC-WH · TC-WHP 는 받는 쪽(검증 · 중복 · 주문), TC-NH · TC-NR 은 알림 쪽(이력 글 · 재시도)을 따로 지킨다.
여기서는 그 조각을 **실제 일회용 PG 로 끝까지 잇는다** — TradingView 알림 한 건이
`tv.handle_alert`(기록 + 가짜 주문) → 응답 뒤 작업 `_after_response`(알림 선점 → 채널 보내기 → 전달 결과 저장) →
`NotificationLog` 행 → 알림 설정 화면이 읽는 이력 API 의 글 까지 어떻게 남는가.
채널(Slack)과 주문은 가짜다. 재시도 사이의 기다림은 건너뛴다.

무엇을 지키나
1. 연결 실패 한 번 뒤 성공 → 신호 행 하나 · 알림 행 하나(전달됨 · 시도 2) · 이력 글 「전달됨」. (TC-ECH-01)
2. 같은 알림이 또 와도(duplicate) · 같은 결과로 응답 뒤 작업이 다시 돌아도 보내기는 늘지 않고 알림 행도 하나다. (TC-ECH-02)
3. 계속 연결이 안 되면 상한(처음 1 + 재시도 3 = 4번)에서 멈추고 「전달 실패」 로 남는다 — 신호 기록은 영향 없음. (TC-ECH-03)
4. 응답이 불명확한 실패는 한 번만 보내고 「전달 실패」 로 남는다(자동 재발송 금지). (TC-ECH-04)
"""
import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import ApiKey, NotificationLog, User, WebhookSignal
from app.routes import notification as notification_route
from app.routes import tradingview as tv_route
from app.services import notification
from app.services import tradingview as tv

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]

NOW = datetime(2026, 10, 28, 5, 30, 0, tzinfo=timezone.utc)


def alert(token, **over):
    p = {"token": token, "ticker": "KRX:005930", "action": "buy", "contracts": "2", "price": "70000",
         "strategy": "MA 교차", "strategy_id": "ma-cross", "strategy_version": 1,
         "bar_time": "2026-10-28T00:00:00Z", "sent_at": "2026-10-28T05:29:50Z"}
    p.update(over)
    return p


@pytest.fixture
def chain(monkeypatch):
    """일회용 PG 세션 + 가짜 주문 · 가짜 감사 · 가짜 채널(Slack) · 건너뛰는 기다림. 시나리오는 `chain(script, go)` 로 돌린다."""
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    from app.database import postgres
    monkeypatch.setattr(postgres, "get_session_factory", lambda: sessions)  # 알림 선점 · 저장이 쓰는 세션
    monkeypatch.setattr(tv.pt, "stock_order", AsyncMock(return_value={"symbol": "005930", "price": 70000, "name": "삼성전자"}))
    monkeypatch.setattr(tv_route, "audit", AsyncMock())
    monkeypatch.setattr(notification, "_load_user_settings", AsyncMock(return_value={"channels": ["slack"], "slack_webhook_url": "http://x.invalid"}))
    sleeps: list[float] = []

    async def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr(notification.asyncio, "sleep", fake_sleep)

    def run(script, scenario):
        """script: 보내기 시도마다 `(성공, 재시도 가능 표시)` — 모자라면 마지막 값을 되풀이한다."""
        sent: list[int] = []

        async def fake_slack(message, webhook_url="", outcome=None):
            ok, retryable = script[min(len(sent), len(script) - 1)]
            sent.append(1)
            if retryable and outcome is not None:
                outcome["retryable"] = True
            return ok

        monkeypatch.setattr(notification, "send_slack", fake_slack)

        async def go():
            token = f"qk_test_{uuid.uuid4().hex}"
            uid = uuid.uuid4()
            async with sessions() as db:
                db.add(User(id=uid, name="chain test", email=f"{uid}@example.com", client_id=uid.hex, password_hash="test"))
                await db.flush()
                db.add(ApiKey(user_id=uid, key_prefix=token[:12], key_hash=hashlib.sha256(token.encode()).hexdigest()))
                await db.commit()
            try:
                await scenario(sessions, uid, token, sent, sleeps)
            finally:
                async with sessions() as db:
                    await db.execute(delete(NotificationLog).where(NotificationLog.user_id == uid))
                    await db.execute(delete(WebhookSignal).where(WebhookSignal.user_id == uid))
                    await db.execute(delete(ApiKey).where(ApiKey.user_id == uid))
                    await db.execute(delete(User).where(User.id == uid))
                    await db.commit()

        asyncio.run(go())

    yield run
    asyncio.run(engine.dispose())


async def receive(sessions, token, payload):
    """라우트가 하는 일: 토큰 조회 → handle_alert → 커밋. 응답 뒤 작업이 받는 결과 전체를 돌려준다."""
    async with sessions() as db:
        key = await tv.resolve_user_by_token(db, token)
        res = await tv.handle_alert(db, payload, key=key, now=NOW)
        await db.commit()
        return res


async def logs(sessions, uid):
    async with sessions() as db:
        return (await db.execute(select(NotificationLog).where(NotificationLog.user_id == uid))).scalars().all()


async def history(sessions, uid):
    async with sessions() as db:
        return await notification_route.notification_history(limit=50, user={"id": str(uid)}, db=db)


def test_alert_to_history_with_one_connection_retry(chain):
    """TC-ECH-01 · 연결 실패 한 번 뒤 성공 → 신호 1 · 알림 1(전달됨 · 시도 2) · 이력 글 「전달됨」."""
    async def scenario(sessions, uid, token, sent, sleeps):
        res = await receive(sessions, token, alert(token))
        assert res["signal"]["status"] == "filled"
        await tv_route._after_response(res)
        (row,) = await logs(sessions, uid)
        assert row.kind == "tradingview_signal" and row.ref == res["notification_ref"]
        assert row.delivery_status == "delivered"
        assert row.channels == [{"channel": "slack", "ok": True, "attempts": 2}]
        assert len(sent) == 2 and sleeps == [1.0]
        out = await history(sessions, uid)
        assert out["count"] == 1 and out["events"][0]["status_label"] == "전달됨"
        async with sessions() as db:
            assert len((await db.execute(select(WebhookSignal).where(WebhookSignal.user_id == uid))).scalars().all()) == 1
    chain([(False, True), (True, False)], scenario)


def test_repeated_alert_or_repeated_after_work_sends_nothing_more(chain):
    """TC-ECH-02 · 같은 알림(duplicate) · 같은 결과로 응답 뒤 작업을 다시 돌려도 보내기도 알림 행도 늘지 않는다."""
    async def scenario(sessions, uid, token, sent, sleeps):
        first = await receive(sessions, token, alert(token))
        await tv_route._after_response(first)
        again = await receive(sessions, token, alert(token))
        assert again["signal"]["status"] == "duplicate"
        await tv_route._after_response(again)       # duplicate 는 알림을 다시 보내지 않는다
        await tv_route._after_response(first)       # 같은 사건의 응답 뒤 작업이 다시 돌아도 선점된 사건이다
        assert len(sent) == 1 and len(await logs(sessions, uid)) == 1
    chain([(True, False)], scenario)


def test_connection_never_recovers_stops_at_cap_and_records_failure(chain):
    """TC-ECH-03 · 계속 연결 실패 → 4번(처음 1 + 재시도 3)에서 멈추고 간격 1 · 3 · 9초 · 「전달 실패」 · 신호 기록은 그대로."""
    async def scenario(sessions, uid, token, sent, sleeps):
        res = await receive(sessions, token, alert(token))
        await tv_route._after_response(res)
        (row,) = await logs(sessions, uid)
        assert row.delivery_status == "failed" and row.channels == [{"channel": "slack", "ok": False, "attempts": 4}]
        assert len(sent) == 4 and sleeps == [1.0, 3.0, 9.0]
        assert (await history(sessions, uid))["events"][0]["status_label"] == "전달 실패"
        async with sessions() as db:
            (sig,) = (await db.execute(select(WebhookSignal).where(WebhookSignal.user_id == uid))).scalars().all()
            assert sig.status == "filled"
    chain([(False, True)], scenario)


def test_ambiguous_failure_is_sent_once_and_recorded(chain):
    """TC-ECH-04 · 응답이 불명확한 실패(재시도 표시 없음) → 한 번만 보내고 「전달 실패」 · 기다림 없음."""
    async def scenario(sessions, uid, token, sent, sleeps):
        res = await receive(sessions, token, alert(token))
        await tv_route._after_response(res)
        (row,) = await logs(sessions, uid)
        assert row.delivery_status == "failed" and row.channels == [{"channel": "slack", "ok": False, "attempts": 1}]
        assert len(sent) == 1 and sleeps == []
    chain([(False, False)], scenario)
