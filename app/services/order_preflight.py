"""공통 관문에 넘기는 가격·잔고는 서버가 잠금 안에서 다시 읽는다."""
from datetime import datetime, timezone
from sqlalchemy import select

from app.models import BrokerSettings, BrokerPositionBaseline, LiveOrder, Portfolio, LIVE_ORDER_OPEN_STATUSES
from app.services import execution_control as control, kis_execution, live_ownership, quant_valuation, trading_cost
from app.services.brokers import stock_coin_trade_gateway as gateway


async def quant(db, intent, mode, requested_quantity):
    row = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == intent.user_id))).scalar_one_or_none()
    if row is None or row.quant_mode != mode or live_ownership.strategy(row) != (intent.strategy_id, intent.strategy_version):
        raise control.Rejected("SETTINGS_CHANGED", "계좌 또는 전략 설정이 바뀌었습니다.")
    signature = control.settings_signature(row)
    if mode == "live":
        if live_ownership.account_ref(row, gateway) != intent.account_ref:
            raise control.Rejected("SETTINGS_CHANGED", "주문 계좌가 바뀌었습니다.")
        snapshot = await kis_execution.account_snapshot(row, gateway, {intent.symbol: {"symbol": intent.symbol}})
        opened = (await db.execute(select(LiveOrder).where(
            LiveOrder.user_id == intent.user_id, LiveOrder.symbol == intent.symbol,
            LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES, "LOST"))))).scalars().all()
        if opened:
            raise control.Rejected("OPEN_ORDER", "접수·체결 미확인 주문이 있습니다.")
        owned, blocked = await live_ownership.reconcile(db, intent.account_ref, snapshot, intent.user_id,
                                                       intent.strategy_id, intent.strategy_version)
        if intent.side == "BUY":
            base = await db.get(BrokerPositionBaseline, (intent.account_ref, intent.symbol))
            if base is not None and intent.symbol in blocked:
                raise control.Rejected("OWNERSHIP_UNCONFIRMED", blocked[intent.symbol])
            await live_ownership.ensure_baseline(db, intent.account_ref, intent.symbol, snapshot)
        client, creds = kis_execution.client_for(row)
        if not client.paper:
            raise control.Rejected("REAL_TRADING_DISABLED", "이번 자동 주문 관문은 모의 계좌만 지원합니다.")
        quote = await client.get_price(intent.symbol)
        price = float(quote.current)
        cash = snapshot["cash"]
        max_qty = requested_quantity
        if intent.side == "BUY":
            power = await client.get_buying_power(creds.account_no, intent.symbol, price)
            cash, max_qty = min(cash, power["amount"]), min(max_qty, power["quantity"])
        held = next((p.quantity for p in owned if p.symbol == intent.symbol), 0)
        equity = snapshot["equity"]
        position_value = snapshot["holdings"].get(intent.symbol, {}).get("value", 0)
    else:
        snapshot = await quant_valuation.snapshot(db, intent.user_id)
        if not snapshot["complete"] or not snapshot["has_account"]:
            raise control.Rejected("ACCOUNT_UNAVAILABLE", "가상계좌 평가를 확인하지 못했습니다.")
        quote = await quant_valuation.quote(db, intent.user_id, intent.symbol, fresh=True)
        price, cash, equity = quote["price"], snapshot["cash"], snapshot["equity"]
        position = (await db.execute(select(Portfolio).where(Portfolio.user_id == intent.user_id,
            Portfolio.book == "QUANT", Portfolio.symbol == intent.symbol))).scalar_one_or_none()
        held = int(position.quantity) if position else 0
        position_value = held * price
        held = await live_ownership.virtual_quantity(db, intent, held)
        max_qty = requested_quantity
    if intent.side == "BUY":
        rate = trading_cost.cost_rate("buy", trading_cost.today_kst(), slippage_bps=0,
                                      market=trading_cost.market_of(intent.symbol))
        cash = cash / (1 + rate)
        budget = float(row.quant_per_trade_budget) * float(row.quant_buy_ratio)
        max_qty = min(max_qty, max(0, int(min(cash, budget) / price)))
    return {"price": price, "cash": cash, "equity": equity, "position_value": position_value,
            "owned_quantity": held, "max_quantity": max_qty, "checked_at": datetime.now(timezone.utc),
            "db": db, "broker": row, "settings": signature}


async def execute_quant(db, uid, row, mode, symbol, name, action, quantity, reason, decision):
    from app.services import auto_trade
    try:
        ref = live_ownership.account_ref(row, gateway) if mode == "live" else control.digest([str(uid), "QUANT"])
    except (ValueError, RuntimeError):
        return control.blocked("ACCOUNT_IDENTITY_UNAVAILABLE", "계좌 식별 근거를 확인하지 못해 주문을 보류합니다.")
    strategy_id, version = live_ownership.strategy(row)
    intent = control.Intent(uid, ref, "KIS" if mode == "live" else "QUANT", strategy_id, version,
        symbol, action.upper(), str(decision.get("signal_key") or ""), "quant", decision.get("input_hash", ""))
    async def prepare(session):
        return await quant(session, intent, mode, quantity)
    async def send(order_id, qty, basis):
        return await auto_trade._execute_trade_unchecked(basis["db"], uid, basis["broker"], mode,
            symbol, name, action, basis["price"], qty, reason)
    result = await control.execute(intent, quantity, prepare, send, require_enabled=True)
    if result.get("duplicate"):
        result = {**result, "original_status": result.get("status"), "status": "duplicate"}
    return {"symbol": symbol, "name": name, "action": action, **result}
