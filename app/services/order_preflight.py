"""공통 관문에 넘기는 가격·잔고는 서버가 잠금 안에서 다시 읽는다."""
from datetime import datetime, timezone
import math
from sqlalchemy import select

from app.models import BrokerSettings, BrokerPositionBaseline, LiveOrder, Portfolio, LIVE_ORDER_OPEN_STATUSES
from app.services import execution_control as control, kis_execution, live_ownership, quant_valuation, trading_cost
from app.services.brokers import stock_coin_trade_gateway as gateway
from app.services.execution_policy import policy_for, risk_quantity


async def current_quote(db, uid, row, mode, symbol):
    """실행용 원주가. KIS 직접 주문은 그 계좌의 시세를 읽고 조회 시각을 남긴다."""
    if mode != "live":
        return await quant_valuation.quote(db, uid, symbol, fresh=True)
    client, _ = kis_execution.client_for(row)
    if not client.paper:
        raise control.Rejected("REAL_TRADING_DISABLED", "이번 자동 주문 관문은 모의 계좌만 지원합니다.")
    try:
        value = (await client.get_price(symbol)).current
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError("invalid quote")
    except Exception as exc:
        raise control.Rejected("PRICE_UNAVAILABLE", "증권사 주문 가격을 확인하지 못했습니다.") from exc
    now = datetime.now(timezone.utc)
    from app.services.quote_now import label_for
    return {"price": float(value), "source": "kis_user", "as_of": now.isoformat(),
            "fetched_at": now.isoformat(), "label": label_for("kis_user", now=now), "fallback": []}


async def quant(db, intent, mode, requested_quantity, decision=None, name=""):
    decision = decision or {}
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
        quote = await current_quote(db, intent.user_id, row, mode, intent.symbol)
        price = quote["price"]
        cash = snapshot["cash"]
        max_qty = None
        if intent.side == "BUY":
            power = await client.get_buying_power(creds.account_no, intent.symbol, price)
            cash, max_qty = min(cash, power["amount"]), power["quantity"]
        held = next((p.quantity for p in owned if p.symbol == intent.symbol), 0)
        average = next((p.avg_price for p in owned if p.symbol == intent.symbol), None)
        equity = snapshot["equity"]
        account_holding = snapshot["holdings"].get(intent.symbol, {})
        position_value = account_holding.get("quantity", 0) * price
        equity += position_value - account_holding.get("value", 0)
    else:
        snapshot = await quant_valuation.snapshot(db, intent.user_id)
        if not snapshot["complete"] or not snapshot["has_account"]:
            raise control.Rejected("ACCOUNT_UNAVAILABLE", "가상계좌 평가를 확인하지 못했습니다.")
        quote = await current_quote(db, intent.user_id, row, mode, intent.symbol)
        price, cash, equity = quote["price"], snapshot["cash"], snapshot["equity"]
        position = (await db.execute(select(Portfolio).where(Portfolio.user_id == intent.user_id,
            Portfolio.book == "QUANT", Portfolio.symbol == intent.symbol))).scalar_one_or_none()
        held = int(position.quantity) if position else 0
        position_value = held * price
        # 같은 주문 직전 가격으로 보유 평가액도 바꾼다.
        equity += position_value - snapshot["values"].get(intent.symbol, 0)
        average = position.avg_price if position else None
        held = await live_ownership.virtual_quantity(db, intent, held)
        if position and held != int(position.quantity):
            average = None  # 다른 전략·수동 보유가 섞인 평단을 전략 손절 원가로 쓰지 않는다.
        max_qty = None
    policy = policy_for(row)
    if policy.size_kind == "risk_pct" and quote['source'] not in ('kis_user', 'kis_gateway'):
        raise control.Rejected("PRICE_UNAVAILABLE", "위험 판단·수량 계산용 현재 원주가를 확인하지 못했습니다.")
    if decision.get("risk_stop"):
        if (quote["source"] not in ("kis_user", "kis_gateway") or not average
                or price > float(average) * (1 - policy.stop_loss_pct / 100)):
            raise control.Rejected("STOP_NOT_CONFIRMED", "주문 직전 현재가로 손절 조건을 확인하지 못했습니다.")
    sizing = None
    quantity = requested_quantity
    if intent.side == "BUY":
        budget = float(row.quant_per_trade_budget) * float(row.quant_buy_ratio)
        cap = control.risk_guard.RiskLimits.from_row(row).max_position_pct
        if decision.get("position_cap_pct") is not None:
            card_cap = float(decision["position_cap_pct"])
            cap = min(cap, card_cap) if cap > 0 else card_cap
        if policy.size_kind == "risk_pct":
            if held or position_value > 0:
                raise control.Rejected("ALREADY_HELD", "위험 기준 수량은 보유 종목 추가 매수를 하지 않습니다.")
            sizing = risk_quantity(equity=equity, cash=cash, price=price,
                stop_price=price * (1 - policy.stop_loss_pct / 100), budget=budget,
                existing_value=position_value, position_cap_pct=cap, risk_pct=policy.risk_pct,
                slippage_bps=policy.slippage_bps, when=trading_cost.today_kst(),
                market=trading_cost.market_of(intent.symbol), is_etf=trading_cost.is_etf_name(name))
            quantity = sizing["quantity"] if decision.get("size_from_budget") else min(quantity, sizing["quantity"])
        elif decision.get("size_from_budget"):
            quantity = max(0, int(budget / price))
        rate = trading_cost.cost_rate("buy", trading_cost.today_kst(), slippage_bps=0,
                                      market=trading_cost.market_of(intent.symbol))
        cash = cash / (1 + rate)
        quantity = min(quantity, max(0, int(min(cash, budget) / price)))
        quantity, _ = control.risk_guard.cap_buy_quantity(quantity, price, position_value, equity, cap)
    quantity = min(quantity, max_qty) if max_qty is not None else quantity
    price_basis = {"signal_price": decision.get("signal_price"), "signal_as_of": decision.get("signal_as_of"),
                   "quote": quote, "quantity": quantity}
    signal_price = decision.get("signal_price")
    if signal_price and signal_price > 0:
        price_basis["price_delta_pct"] = round((price / signal_price - 1) * 100, 4)
    if sizing:
        estimated_cash = sizing["estimated_cash"] * quantity / sizing["quantity"] if sizing["quantity"] else 0
        sizing = {**sizing, "quantity": quantity, "estimated_loss": sizing["loss_per_share"] * quantity,
                  "estimated_cash": estimated_cash}
        price_basis["sizing"] = sizing
    return {"price": price, "cash": cash, "equity": equity, "position_value": position_value,
            "owned_quantity": held, "quantity": quantity, "price_basis": price_basis,
            "checked_at": datetime.now(timezone.utc),
            "db": db, "broker": row, "settings": signature}


async def execute_quant(db, uid, row, mode, symbol, name, action, quantity, reason, decision):
    from app.services import auto_trade, strategy_loader
    if strategy_loader.is_fixed_test() and mode != "paper":
        return control.blocked("TEST_STRATEGY_PAPER_ONLY", "고정 시험 전략은 앱 가상계좌 전용입니다.")
    try:
        ref = live_ownership.account_ref(row, gateway) if mode == "live" else control.digest([str(uid), "QUANT"])
    except (ValueError, RuntimeError):
        return control.blocked("ACCOUNT_IDENTITY_UNAVAILABLE", "계좌 식별 근거를 확인하지 못해 주문을 보류합니다.")
    strategy_id, version = live_ownership.strategy(row)
    intent = control.Intent(uid, ref, "KIS" if mode == "live" else "QUANT", strategy_id, version,
        symbol, action.upper(), str(decision.get("signal_key") or ""), "quant", decision.get("input_hash", ""))
    async def prepare(session):
        return await quant(session, intent, mode, quantity, decision, name)
    async def send(order_id, qty, basis):
        result = await auto_trade._execute_trade_unchecked(basis["db"], uid, basis["broker"], mode,
            symbol, name, action, basis["price"], qty, reason)
        return {**result, "price_basis": basis["price_basis"]}
    result = await control.execute(intent, quantity, prepare, send, require_enabled=True)
    if result.get("duplicate"):
        result = {**result, "original_status": result.get("status"), "status": "duplicate"}
    return {"symbol": symbol, "name": name, "action": action, **result}
