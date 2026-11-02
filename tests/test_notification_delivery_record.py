"""새 주문 알림의 실제 전달 결과가 옛 기록 기본값으로 저장되지 않아야 한다."""
import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.database import postgres
from app.models import NotificationLog
from app.services import notification

pytestmark=[pytest.mark.skipif(not os.getenv('QURIOUS_TEST_DATABASE_URL'),reason='격리 PostgreSQL 필요'),
            pytest.mark.usefixtures('rebalance_db_schema')]


@pytest.mark.parametrize('channels,results,status', [(['discord'],[True],'delivered'),
    (['email','discord'],[False,True],'partial'),(['discord'],[False],'failed'),
    (['discord'],[RuntimeError('synthetic')],'failed'),([],[],'no_channels')])
def test_new_delivery_records_status_kind_and_actual_attempts(monkeypatch,channels,results,status):
    async def scenario():
        engine=create_async_engine(os.environ['QURIOUS_TEST_DATABASE_URL'],poolclass=NullPool)
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        monkeypatch.setattr(postgres,'get_session_factory',lambda:sessions)
        subject='test-'+uuid.uuid4().hex
        try:
            await notification._log_dispatch(None,subject,'synthetic',channels,results,[1]*len(channels),
                payload={'kind':'order_fill'})
            async with sessions() as db:
                row=(await db.execute(select(NotificationLog).where(NotificationLog.subject==subject))).scalar_one()
                assert row.delivery_status==status and row.kind=='order_fill'
                assert len(row.channels)==len(channels)
                assert all(r['attempts']==1 for r in row.channels)
        finally:
            await engine.dispose()
    asyncio.run(scenario())
