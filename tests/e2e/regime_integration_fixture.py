"""격리 DB에 과거 상승·저변동 플랜 상태를 준비한다. API/계산 함수를 대체하지 않는다."""
import asyncio
from copy import deepcopy
import json
from sqlalchemy import select, text, func
from app.database import postgres as pg
from app.models import User, Order, RebalanceTargetChange
from app.services import rebalance as rb, rebalance_regime as regime, asset_allocation

async def main():
    await pg.connect_postgres()
    try:
        async with pg.get_session_factory()() as db:
            assert await db.scalar(text('SELECT current_database()')) == 'regime_live_test'
            uid = await db.scalar(select(User.id).where(User.email == 'regime.integration@example.com'))
            assert uid is not None
            plan = await rb.get_plan(db, uid)
            assert plan.regime_config and not plan.auto_execute
            assert plan.regime_config['baseline'] == asset_allocation.asset_allocation('moderate', 3)
            assert plan.regime_state['regime'] == 'down_high'
            assert not await db.scalar(select(func.count(RebalanceTargetChange.id)))
            assert not await db.scalar(select(func.count(Order.id)))
            # 합성된 과거 상태를 준비. 현재 실수집 자료는 그대로 읽기 전용이다.
            old_alloc = {'국내주식':33, '해외주식':27.5, '국내채권':25.3, '대체자산':10, '현금':4.2}
            plan.targets = regime.mapped_targets(plan.regime_config, old_alloc)
            plan.regime_state = {'status':'unchanged', 'regime':'up_low', 'data_as_of':'2026-10-30',
                                 'targets':deepcopy(plan.targets), 'message':'격리 시험용 과거 국면 상태'}
            plan.last_auto_check_date = None
            plan.last_auto_check_at = None
            plan.last_auto_check_result = {}
            await db.commit()
        print(json.dumps({'synthetic_prior_regime':'up_low','prior_date':'2026-10-30','stock_pct':33,
                          'collector_modified':False,'api_mocked':False}))
    finally:
        await pg.close_postgres()

if __name__ == '__main__':
    asyncio.run(main())
