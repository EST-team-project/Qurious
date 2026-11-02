"""커밋된 PAPER 체결만 알림으로 전달. 주문 ID로 중복을 막고 재시작 시 미처리 건을 회수한다."""
import logging

from sqlalchemy import select

from app.database.postgres import get_session_factory
from app.models.trading import Order
from app.services import notification

logger = logging.getLogger(__name__)


async def drain(*, user_id=None, order_id=None, limit=50):
    # 호출자의 금융 트랜잭션과 분리한다. 알림 실패가 체결 성공 응답을 바꾸지 않는다.
    try:
        async with get_session_factory()() as db:
            stmt = select(Order).where(Order.fill_notice_pending.is_(True), Order.status == "filled",
                                       Order.source == "PAPER", Order.broker == "virtual")
            if user_id is not None:
                stmt = stmt.where(Order.user_id == user_id)
            if order_id is not None:
                stmt = stmt.where(Order.id == order_id)
            rows = (await db.execute(stmt.order_by(Order.created_at, Order.id).limit(limit)
                                     .with_for_update(skip_locked=True))).scalars().all()
            for order in rows:
                try:
                    await notification.notify_paper_order_filled(order)
                    order.fill_notice_pending = False
                except Exception as exc:
                    # 발송 전 장애는 다음 tick에서 회수. 이미 선점된 발송은 notifier가 재발송하지 않는다.
                    logger.warning("PAPER 체결 알림 보류: %s", type(exc).__name__)
            await db.commit()
    except Exception as exc:
        logger.warning("PAPER 체결 알림 회수 보류: %s", type(exc).__name__)
