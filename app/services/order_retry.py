"""취소가 확인된 모의 게이트웨이 매도 잔량만 제한적으로 재주문한다.

부모당 자식 한 건을 DB에 먼저 기록하고 고정 멱등키로 전송한다.
UNKNOWN/PENDING/취소 요청만 있는 주문은 새 주문으로 재시도하지 않는다.
"""
import json
import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.models import BrokerSettings, LiveOrder, LIVE_ORDER_OPEN_STATUSES
from app.database.postgres import get_session_factory
from app.services import risk_guard, aggressive_mode
from app.services.execution_policy import policy_for
from app.services.brokers import stock_coin_trade_gateway as gateway


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("유효한 잔고·가격이 필요합니다.")
    return value


def enabled(broker, policy):
    return (broker is not None and policy.retry_enabled and broker.broker == "kis"
            and broker.quant_auto_enabled and not broker.risk_kill_switch and broker.quant_mode == "live")


async def coordination_ready():
    try:
        redis = risk_guard._redis()
        return redis is not None and bool(await redis.ping())
    except Exception:
        return False


async def prepare_retry(db, parent_id, now=None):
    now = now or datetime.now(timezone.utc)
    parent = await db.scalar(select(LiveOrder).where(LiveOrder.id == parent_id).with_for_update(skip_locked=True))
    if parent is not None and parent.broker == "kis-direct":
        return None
    if (parent is None or parent.status != "CANCELLED" or parent.side != "SELL" or parent.environment != "paper"
            or not parent.order_no or parent.order_type != "LIMIT" or not parent.account_ref or not parent.strategy_id):
        return None
    broker = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == parent.user_id)
                             .with_for_update().execution_options(populate_existing=True))
    policy = policy_for(broker)
    if not enabled(broker, policy) or gateway.environment() != "paper" or not gateway.is_krx_market_open():
        return None
    if not await coordination_ready():
        return None
    started = parent.retry_started_at or parent.created_at
    if started is None or not 0 <= (now - started).total_seconds() <= policy.retry_window_min * 60:
        return None
    attempt = (parent.retry_number or 0) + 1
    if attempt > policy.retry_max_attempts or await db.scalar(select(LiveOrder.id).where(LiveOrder.retry_of == parent.id)):
        return None
    # 재전송 직전 취소 확정·체결 수량을 다시 읽는다. 잔고 추론은 취소 확정 근거로 쓰지 않는다.
    latest = await gateway.get_order_status(parent.order_no, env="paper")
    if (latest.get("status") != "CANCELLED" or latest.get("lookup") not in (None, "")
            or latest.get("orderNo") != parent.order_no or latest.get("side") != "SELL"
            or latest.get("symbol") != gateway.normalize_symbol(parent.symbol)):
        return None
    ordered, filled = latest.get("orderedQuantity"), latest.get("filledQuantity")
    if type(ordered) is not int or type(filled) is not int or ordered != parent.quantity or not 0 <= filled < ordered:
        return None
    # 같은 종목의 다른 열린 주문과 경쟁하지 않는다(공유 게이트웨이 계좌 포함).
    for order in await gateway.list_today_orders(env="paper", open_only=True):
        if order.get("symbol") == gateway.normalize_symbol(parent.symbol) and order.get("status") not in ("FILLED", "CANCELLED", "REJECTED"):
            return None
    if await db.scalar(select(LiveOrder.id).where(LiveOrder.environment == "paper", LiveOrder.symbol == parent.symbol,
                       LiveOrder.status.in_(LIVE_ORDER_OPEN_STATUSES)).limit(1)):
        return None
    balance = await gateway.get_balance(env="paper")
    if balance.get("accountRef") != parent.account_ref or not isinstance(balance.get("holdings"), list):
        return None  # 현재 게이트웨이 계약에는 accountRef가 없어 자동 재주문도 보류한다.
    holding = next((h for h in balance.get("holdings", []) if h.get("symbol") == gateway.normalize_symbol(parent.symbol)), None)
    if holding is None:
        return None
    quantity = holding.get("quantity")
    if type(quantity) is not int or quantity <= 0:
        return None
    price, equity = positive(holding.get("currentPrice")), positive(balance.get("totalEvalAmount"))
    if abs(price / positive(parent.price) - 1) * 100 > policy.retry_price_deviation_pct:
        return None
    limits = risk_guard.RiskLimits.from_row(broker)
    if aggressive_mode.is_enabled():
        limits = aggressive_mode.apply_limits(limits)
    start = await risk_guard.day_start_equity(f"{parent.user_id}:live:paper", equity)
    if risk_guard.daily_loss_breached(start, equity, limits.daily_loss_limit_pct):
        return None
    day = now.astimezone(gateway.KST).replace(hour=0, minute=0, second=0, microsecond=0)
    count = await db.scalar(select(func.count()).select_from(LiveOrder).where(
        LiveOrder.user_id == parent.user_id, LiveOrder.created_at >= day))
    if limits.max_orders_per_day > 0 and max(count, await risk_guard.orders_today(str(parent.user_id))) >= limits.max_orders_per_day:
        return None
    if not await risk_guard.acquire_order_slot(str(parent.user_id), parent.symbol, "sell", max(1, limits.cooldown_min)):
        return None
    # 원 지정 가격을 보존한다. 시장가는 기록 가격이 0이라 이탈 한도를 검증할 수 없다.
    # 가상 장부는 이미 처리됐으므로 다시 차감하지 않는다.
    child = LiveOrder(user_id=parent.user_id, client_order_id=f"retry:{parent.id.hex}", environment="paper", broker="kis",
                      account_ref=parent.account_ref, strategy_id=parent.strategy_id, strategy_version=parent.strategy_version,
                      symbol=parent.symbol, name=parent.name, side="SELL", order_type=parent.order_type,
                      quantity=min(ordered - filled, quantity), price=parent.price, status="PENDING",
                      retry_of=parent.id, retry_number=attempt, retry_started_at=started,
                      message=f"취소 확정 매도 잔량 재주문 {attempt}회 준비")
    parent.filled_quantity = filled
    db.add(child)
    await db.flush()
    return child.id


async def send_retry(db, child_id):
    # 같은 준비 행을 두 작업자가 보내지 않도록 잠근다. 외부 전송 전에 UNKNOWN을 영속화한다.
    child = await db.scalar(select(LiveOrder).where(LiveOrder.id == child_id).with_for_update(skip_locked=True))
    if child is None or child.status != "PENDING" or child.retry_of is None:
        return False
    broker = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == child.user_id).execution_options(populate_existing=True))
    policy = policy_for(broker)
    now = datetime.now(timezone.utc)
    in_window = child.retry_started_at and 0 <= (now - child.retry_started_at).total_seconds() <= policy.retry_window_min * 60
    if (not enabled(broker, policy) or gateway.environment() != "paper" or not gateway.is_krx_market_open()
            or not in_window or not await coordination_ready()):
        child.status, child.message = "ERROR", "재주문 전 설정·장 운영 상태 변경으로 전송하지 않음"
        await db.commit()
        return False
    child.status = "UNKNOWN"
    await db.commit()
    await risk_guard.increment_orders_today(str(child.user_id))
    try:
        result = await gateway.place_order(child.symbol, child.side, child.quantity, child.price,
                    client_order_id=child.client_order_id, order_type=child.order_type, env="paper")
    except gateway.GatewayError as exc:
        child.status = "UNKNOWN" if exc.code == "GATEWAY_UNREACHABLE" else "ERROR"
        child.message = f"재주문 확인 필요 [{exc.code}] {exc}"[:300]
    else:
        order = result.get("order") or {}
        child.order_no = order.get("orderNo") or ""
        child.status = order.get("status") or "UNKNOWN"
        child.filled_quantity = int(order.get("filledQuantity") or 0)
        child.avg_filled_price = float(order.get("avgFilledPrice") or 0)
        child.raw = json.dumps(order, ensure_ascii=False)
        child.message = f"취소 확정 매도 잔량 재주문 {child.retry_number}회"
    await db.commit()
    return True


async def retry_cancelled_orders(limit=50):
    summary = {"submitted": 0, "skipped": 0, "errors": 0}
    if not gateway.is_configured() or gateway.environment() != "paper":
        return summary
    factory = get_session_factory()
    async with factory() as db:
        ids = (await db.scalars(select(LiveOrder.id).join(BrokerSettings, BrokerSettings.user_id == LiveOrder.user_id).where(
            LiveOrder.status == "CANCELLED", LiveOrder.side == "SELL", LiveOrder.environment == "paper", LiveOrder.broker == "kis",
            LiveOrder.created_at >= datetime.now(timezone.utc) - timedelta(minutes=120),
            BrokerSettings.quant_execution_policy["retry_enabled"].as_boolean().is_(True))
            .order_by(LiveOrder.created_at.desc()).limit(limit))).all()
    for parent_id in ids:
        async with factory() as db:
            try:
                child_id = await prepare_retry(db, parent_id)
                await db.commit()
                if child_id and await send_retry(db, child_id):
                    summary["submitted"] += 1
                else:
                    summary["skipped"] += 1
            except Exception:
                await db.rollback()
                summary["errors"] += 1
                # 한 주문의 통신/DB 실패가 다른 계정의 체결 확인을 중단시키지 않는다.
                import logging
                logging.getLogger(__name__).exception("취소 확정 매도 재주문 확인 실패: %s", parent_id)
    return summary
