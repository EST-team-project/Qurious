"""KIS 모의 1회 시험: 준비 매수(기본 조회)와 체결 후 전략 판단 예약을 분리한다."""
import argparse
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.database.postgres import connect_postgres, close_postgres, get_session_factory
from app.lib.redis_cache import connect_redis, close_redis
from app.models import OrderIntent, LiveOrder
from app.services import kis_paper_trial as trial


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    setup=commands.add_parser('prepare')
    setup.add_argument('--user-id',required=True,type=uuid.UUID)
    setup.add_argument('--max-price',required=True,type=int)
    setup.add_argument('--expires-at',required=True,help='동일 거래일, 현재부터 2시간 이내의 시간대 포함 시각')
    setup.add_argument('--execute',action='store_true',help='준비용 모의 지정가 매수 1주를 실제 전송')
    schedule=commands.add_parser('schedule')
    schedule.add_argument('--seed-intent-id',required=True)
    schedule.add_argument('--countdown',type=int,default=30)
    args=parser.parse_args()
    await connect_postgres()
    try:
        await connect_redis()
        if args.command=='prepare':
            result=await trial.prepare_trial(args.user_id,max_price=args.max_price,
                expires_at=args.expires_at,execute=args.execute)
        else:
            if not 10<=args.countdown<=300:
                raise ValueError('예약은 10~300초 뒤로 지정하세요.')
            async with get_session_factory()() as db:
                seed=await db.get(OrderIntent,args.seed_intent_id)
                if (not seed or seed.source!='kis_trial_setup' or seed.strategy_id!=trial.STRATEGY
                        or seed.status not in ('submitted','filled')):
                    raise ValueError('이 시험의 준비 매수 기록이 없습니다.')
                order=await db.scalar(select(LiveOrder).where(
                    LiveOrder.client_order_id=='intent:'+seed.intent_id[:57]))
                if not order or order.status!='FILLED' or order.filled_quantity!=1 or order.environment!='paper':
                    raise ValueError('준비 매수 1주의 KIS 확정 체결이 먼저 필요합니다.')
                expires=datetime.fromisoformat(seed.result['price_basis']['expires_at'])
            eta=datetime.now(trial.control.KST)+timedelta(seconds=args.countdown)
            if eta>=expires:
                raise ValueError('시험 만료 전으로 예약해야 합니다.')
            from app.tasks.sync_tasks import kis_paper_trial
            task=kis_paper_trial.apply_async(args=[seed.intent_id],eta=eta,expires=expires)
            result={'status':'SCHEDULED','task_id':task.id,'seed_intent_id':seed.intent_id,
                'eta':eta.isoformat(),'expires_at':expires.isoformat()}
        print(json.dumps(result,ensure_ascii=False))
    except trial.control.Rejected as exc:
        print(json.dumps(trial.control.blocked(exc.code,str(exc)),ensure_ascii=False))
    finally:
        await close_redis()
        await close_postgres()


if __name__=='__main__':
    asyncio.run(main())
