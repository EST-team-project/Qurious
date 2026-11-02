"""TC-AFL — 보관한 알림을 푸는 흐름을 일회용 PG 로 끝까지 시험한다 (2026-11-01 S183).

조용한 시간 · 묶음 창에 보관된 행(`delivery_status='held'`)이
1. 조용한 시간이 끝나기 전에는 안 나가고, 끝난 뒤 요약 1건으로 나가며 보관 행은 `digested` 가 된다. (TC-AFL-01)
2. 한 건뿐이면 요약이 아니라 원래 사건 그대로 나가고 그 행이 전달 결과를 얻는다. (TC-AFL-02)
3. 풀기를 동시에 두 번 돌려도 보내기는 한 번이다(원자적 선점). (TC-AFL-03)
4. 묶음 창이 아직 안 지났으면 기다린다. (TC-AFL-04)
채널(Slack)은 가짜다.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import NotificationLog, User
from app.services import alert_format as af
from app.services import notification

pytestmark = [pytest.mark.skipif(not os.getenv("QURIOUS_TEST_DATABASE_URL"), reason="일회용 PG 필요"),
              pytest.mark.usefixtures("rebalance_db_schema")]

KST = af.KST
QUIET_CFG = {"channels": ["slack"], "slack_webhook_url": "https://hooks.slack.com/services/T/B/x",
             "preferences": {"quiet": {"enabled": True, "start": "21:00", "end": "08:00"}}}


@pytest.fixture
def pg(monkeypatch):
    engine = create_async_engine(os.environ["QURIOUS_TEST_DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    from app.database import postgres
    monkeypatch.setattr(postgres, "get_session_factory", lambda: sessions)
    sent: list = []

    async def fake_slack(message, webhook_url="", outcome=None, **kw):
        sent.append((message, kw))
        await asyncio.sleep(0.05)       # 동시 풀기가 겹칠 틈을 준다
        return True

    monkeypatch.setattr(notification, "send_slack", fake_slack)
    return sessions, sent


def scenario(pg, go, cfg=None):
    sessions, sent = pg
    cfg = cfg or QUIET_CFG

    async def load(user_id):
        return cfg

    async def main():
        uid = uuid.uuid4()
        async with sessions() as db:
            db.add(User(id=uid, name="flush test", email=f"{uid}@example.com", client_id=uid.hex, password_hash="test"))
            await db.commit()
        try:
            await go(sessions, uid, sent)
        finally:
            async with sessions() as db:
                await db.execute(delete(NotificationLog).where(NotificationLog.user_id == uid))
                await db.execute(delete(User).where(User.id == uid))
                await db.commit()

    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(notification, "_load_user_settings", load)
    try:
        asyncio.run(main())
    finally:
        mp.undo()


async def add_held(sessions, uid, n, reason="quiet", release_at=None, mode="on"):
    async with sessions() as db:
        for i in range(n):
            ev = af.AlertEvent(kind="order_fill", title=f"체결 {i}", summary="요약", ts=datetime(2026, 11, 1, 14, i, tzinfo=KST))
            payload = {**af.to_payload(ev), "hold": {"reason": reason, "release_at": release_at, "mode": mode}}
            db.add(NotificationLog(user_id=uid, subject=f"s{i}", message="m", channels=[], delivery_status="held", payload=payload))
        await db.commit()


async def statuses(sessions, uid):
    async with sessions() as db:
        rows = (await db.execute(select(NotificationLog).where(NotificationLog.user_id == uid))).scalars().all()
    return sorted(r.delivery_status for r in rows), rows


def test_afl01_quiet_rows_become_one_digest_after_quiet_ends(pg):
    async def go(sessions, uid, sent):
        await add_held(sessions, uid, 3)
        assert await notification.flush_held(now=datetime(2026, 11, 2, 23, 0, tzinfo=KST)) == 0 and sent == []
        assert await notification.flush_held(now=datetime(2026, 11, 2, 7, 59, tzinfo=KST)) == 0
        assert await notification.flush_held(now=datetime(2026, 11, 2, 8, 1, tzinfo=KST)) == 3
        assert len(sent) == 1 and "알림 묶음 3건" in sent[0][0]
        st, rows = await statuses(sessions, uid)
        assert st == ["delivered", "digested", "digested", "digested"]
        digest = [r for r in rows if r.kind == "digest"][0]
        assert digest.payload["title"] == "알림 묶음 3건" and digest.ref
        assert await notification.flush_held(now=datetime(2026, 11, 2, 8, 2, tzinfo=KST)) == 0   # 두 번 보내지 않는다
        assert len(sent) == 1
    scenario(pg, go)


def test_afl02_single_row_is_sent_as_itself(pg):
    async def go(sessions, uid, sent):
        await add_held(sessions, uid, 1)
        assert await notification.flush_held(now=datetime(2026, 11, 2, 9, 0, tzinfo=KST)) == 1
        assert len(sent) == 1 and "체결 0" in sent[0][0] and "묶음" not in sent[0][0]
        st, rows = await statuses(sessions, uid)
        assert st == ["delivered"] and rows[0].channels[0]["channel"] == "slack"
    scenario(pg, go)


def test_afl03_concurrent_flush_sends_once(pg):
    async def go(sessions, uid, sent):
        await add_held(sessions, uid, 2)
        now = datetime(2026, 11, 2, 9, 0, tzinfo=KST)
        a, b = await asyncio.gather(notification.flush_held(now=now), notification.flush_held(now=now))
        assert sorted([a, b]) == [0, 2] and len(sent) == 1
    scenario(pg, go)


def test_afl04_group_window_waits(pg):
    async def go(sessions, uid, sent):
        release = datetime(2026, 11, 2, 12, 2, tzinfo=KST)
        await add_held(sessions, uid, 2, reason="group", release_at=release.isoformat())
        assert await notification.flush_held(now=datetime(2026, 11, 2, 12, 1, tzinfo=KST)) == 0
        assert await notification.flush_held(now=release + timedelta(seconds=1)) == 2 and len(sent) == 1
    scenario(pg, go)
