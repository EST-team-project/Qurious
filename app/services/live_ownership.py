"""계좌 전체 평가와 전략별 매도 가능 보유를 분리한다. 잔고로 체결을 추정하지 않는다."""
import math
from types import SimpleNamespace

from sqlalchemy import select
from app.models import BrokerPositionBaseline, LiveOrder, LIVE_ORDER_OPEN_STATUSES
from app.services import kis_execution


class OwnershipUnavailable(ValueError):
    pass


def account_ref(row, gateway):
    # 현재 게이트웨이 계약에는 계좌 식별자가 없다. URL/사용자 ID를 계좌라고 가정하지 않는다.
    if gateway.is_configured():
        raise OwnershipUnavailable("게이트웨이 응답에 안정적인 계좌 식별자가 없어 자동 주문을 보류합니다.")
    client, creds = kis_execution.client_for(row)
    return kis_execution.account_key(creds.app_key, creds.account_no, "paper" if client.paper else "real")


def strategy(row):
    return (row.quant_strategy_id or "quant_default", int(row.quant_strategy_version or 0))


async def reconcile(db, ref, snapshot, uid, strategy_id, version):
    """첫 추적 전 잔고 + 계좌 내 모든 추적 체결 == 현재 잔고일 때만 전략 보유를 반환."""
    baselines = (await db.execute(select(BrokerPositionBaseline).where(
        BrokerPositionBaseline.account_ref == ref))).scalars().all()
    orders = (await db.execute(select(LiveOrder).where(LiveOrder.account_ref == ref))).scalars().all()
    owned, blocked = [], {}
    for base in baselines:
        rows = [o for o in orders if o.symbol == base.symbol]
        if any(o.status in LIVE_ORDER_OPEN_STATUSES or o.status == "LOST" for o in rows):
            blocked[base.symbol] = "접수·체결 미확인 주문이 있습니다."
            continue
        if base.quantity < 0 or any(o.side not in ("BUY", "SELL") or not 0 <= o.filled_quantity <= o.quantity
                or (o.filled_quantity and (not math.isfinite(o.avg_filled_price) or o.avg_filled_price <= 0)) for o in rows):
            blocked[base.symbol] = "체결 기록이 유효하지 않습니다."
            continue
        net = sum(o.filled_quantity * (1 if o.side == "BUY" else -1) for o in rows)
        h = snapshot["holdings"].get(base.symbol, {})
        if base.quantity + net != h.get("quantity", 0):
            blocked[base.symbol] = "추적 보유와 계좌 잔고가 달라 귀속 확인이 필요합니다."
            continue
        selected = [o for o in rows if o.user_id == uid and o.strategy_id == strategy_id and o.strategy_version == version]
        qty = sum(o.filled_quantity * (1 if o.side == "BUY" else -1) for o in selected)
        if qty < 0 or qty > h.get("quantity", 0):
            blocked[base.symbol] = "전략의 확정 순수량이 유효하지 않습니다."
        elif qty > 0:
            buys = [o for o in selected if o.side == "BUY" and o.filled_quantity]
            total = sum(o.filled_quantity for o in buys)
            avg = sum(o.avg_filled_price * o.filled_quantity for o in buys) / total
            # 실제 체결 근거만 사용. 과거 여러 매수/매도의 평균은 손절 원가로 재사용하지 않는다.
            owned.append(SimpleNamespace(symbol=base.symbol, name=h.get("name", base.symbol), quantity=qty,
                                         avg_price=avg if not any(o.side == "SELL" and o.filled_quantity for o in selected) else None))
    for symbol in snapshot["holdings"]:
        if symbol not in {b.symbol for b in baselines}:
            blocked[symbol] = "수동 또는 추적 시작 전 보유로 전략 귀속을 확인할 수 없습니다."
    return owned, blocked


async def ensure_baseline(db, ref, symbol, snapshot):
    """계좌 잠금을 보유한 새 매수 경로에서만 호출. 기존 잔고는 자동 보유로 편입하지 않는다."""
    row = await db.get(BrokerPositionBaseline, (ref, symbol))
    if row is None:
        row = BrokerPositionBaseline(account_ref=ref, symbol=symbol,
                                     quantity=int(snapshot["holdings"].get(symbol, {}).get("quantity", 0)))
        db.add(row)
        await db.flush()
    return row


async def virtual_quantity(db, intent, actual_quantity):
    """가상 장부도 기존/다른 전략 보유를 편입하지 않는다. 외부 장부 변경 시 재대조 필요."""
    from app.models import Order, OrderIntent
    base = await db.get(BrokerPositionBaseline, (intent.account_ref, intent.symbol))
    if base is None:
        if intent.side == "SELL":
            return 0
        base = BrokerPositionBaseline(account_ref=intent.account_ref, symbol=intent.symbol, quantity=actual_quantity)
        db.add(base)
        await db.flush()
    rows = (await db.execute(select(Order, OrderIntent).join(OrderIntent, Order.execution_intent_id == OrderIntent.intent_id).where(
        OrderIntent.account_ref == intent.account_ref, Order.symbol == intent.symbol, Order.status == "filled"))).all()
    net = sum(o.quantity * (1 if o.order_type == "buy" else -1) for o, _ in rows)
    if base.quantity + net != actual_quantity:
        from app.services.execution_control import Rejected
        raise Rejected("OWNERSHIP_UNCONFIRMED", "전략 기록과 가상 장부 보유가 달라 귀속 확인이 필요합니다.")
    return sum(o.quantity * (1 if o.order_type == "buy" else -1) for o, owner in rows
               if owner.user_id == intent.user_id and owner.strategy_id == intent.strategy_id
               and owner.strategy_version == intent.strategy_version)
