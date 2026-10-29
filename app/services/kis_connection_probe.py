"""전략 평가와 분리한 수동 KIS 모의 매수 점검: 005930 1주, 사용자·계좌·날짜당 한 번."""
import math
from datetime import datetime, time
from types import SimpleNamespace

from sqlalchemy import select, func

from app.database.postgres import get_session_factory
from app.models import BrokerSettings, LiveOrder, OrderIntent, RiskDay, LIVE_ORDER_OPEN_STATUSES
from app.services import auto_trade, execution_control as control, kis_execution, live_ownership
from app.services import market_calendar, order_preflight, trading_cost
from app.services.execution_policy import policy_for
from app.services.brokers.factory import live_trading_allowed
from app.services.brokers import stock_coin_trade_gateway as gateway

SYMBOL = "005930.KS"
STRATEGY = "kis_connection_check"


def eligible(row, expected_day):
    now = datetime.now(control.KST)
    calendar = market_calendar.trading_days(now.date(), now.date())
    if (now.date() != expected_day or not time(9) <= now.time().replace(tzinfo=None) < time(15, 20)
            or calendar.get("partial") or not any(d["date"] == expected_day.isoformat() and d["is_trading_day"]
                                                   for d in calendar.get("days", []))):
        raise control.Rejected("OUTSIDE_WINDOW", "확인된 거래일 09:00~15:20 KST에만 점검합니다.")
    if row is None or row.broker != "kis" or row.quant_auto_enabled or row.risk_kill_switch:
        raise control.Rejected("PROBE_DISABLED", "개인 KIS 연결·자동매매 OFF·비상 정지 해제가 필요합니다.")
    if live_trading_allowed() or gateway.is_configured():
        raise control.Rejected("PAPER_ONLY", "실전 허용 OFF인 개인 KIS 직접 모의 경로만 지원합니다.")
    client, creds = kis_execution.client_for(row)
    if not client.paper or not creds.paper:
        raise control.Rejected("PAPER_ONLY", "모의 계좌만 점검합니다.")
    if policy_for(row).size_kind != "fixed_budget":
        raise control.Rejected("UNSUPPORTED_POLICY", "이 수동 연결 점검은 고정 예산 정책만 지원합니다.")
    return client, kis_execution.account_key(creds.app_key, creds.account_no, "paper"), creds


async def run(uid, *, max_price, execute=False):
    if isinstance(max_price, bool) or not isinstance(max_price, (int, float)) or not math.isfinite(max_price) or max_price <= 0:
        raise ValueError("1주 지정가 상한을 양수로 지정하세요.")
    day = datetime.now(control.KST).date()
    async with get_session_factory()() as db:
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        _, ref, _ = eligible(row, day)
    intent = control.Intent(uid, ref, "KIS", STRATEGY, 1, SYMBOL, "BUY", day.isoformat(),
                            "manual_connection_check", control.digest([SYMBOL, "BUY", 1, max_price]))

    async def prepare(db):
        row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        client, current_ref, creds = eligible(row, day)
        if current_ref != ref:
            raise control.Rejected("SETTINGS_CHANGED", "점검 계좌가 변경되었습니다.")
        signature = control.settings_signature(row)
        opened = await db.scalar(select(LiveOrder.id).where(
            (LiveOrder.account_ref == ref) | LiveOrder.raw.contains(ref),
            LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES, "LOST"))).limit(1))
        if opened:
            raise control.Rejected("OPEN_ORDER", "같은 계좌의 접수·체결 미확인 주문이 있습니다.")
        start = datetime.combine(day, time.min, control.KST)
        used = await db.scalar(select(func.count()).select_from(LiveOrder).where(
            (LiveOrder.account_ref == ref) | LiveOrder.raw.contains(ref), LiveOrder.created_at >= start))
        if used >= 3:
            raise control.Rejected("PROBE_DAILY_LIMIT", "계좌의 하루 경로 점검 상한 3건에 도달했습니다.")
        snapshot = await kis_execution.account_snapshot(row, gateway, {SYMBOL: {"symbol": SYMBOL}})
        _, blocked = await live_ownership.reconcile(db, ref, snapshot, uid, STRATEGY, 1)
        if SYMBOL in blocked:
            raise control.Rejected("OWNERSHIP_UNCONFIRMED", blocked[SYMBOL])
        quote = await order_preflight.current_quote(db, uid, row, "live", SYMBOL)
        price = quote["price"]
        if price > max_price or not float(price).is_integer():
            raise control.Rejected("PRICE_CAP", "현재가가 지정 상한을 넘었거나 유효하지 않습니다.")
        power = await client.get_buying_power(creds.account_no, SYMBOL, price)
        cash = min(snapshot["cash"], power["amount"])
        budget = row.quant_per_trade_budget * row.quant_buy_ratio
        cost = price * (1 + trading_cost.cost_rate("buy", day, slippage_bps=0, market="KOSPI"))
        if not math.isfinite(budget) or budget < cost or cash < cost or power["quantity"] < 1:
            raise control.Rejected("ZERO_QUANTITY", "현금·미수 없는 매수 가능 수량·기존 예산으로 1주를 살 수 없습니다.")
        holding = snapshot["holdings"].get(SYMBOL, {})
        value = holding.get("quantity", 0) * price
        equity = snapshot["equity"] + value - holding.get("value", 0)
        baseline = await db.get(RiskDay, (ref, day))
        control.check_limits(row=row, quantity=1, price=price, cash=cash, equity=equity,
            start_equity=baseline.equity if baseline else equity, orders_today=used, position_value=value)
        await live_ownership.ensure_baseline(db, ref, SYMBOL, snapshot)
        return {"db": db, "broker": row, "settings": signature, "cash": cash, "equity": equity,
                "price": price, "position_value": value, "checked_at": datetime.now(control.KST),
                "price_basis": {"quote": quote, "quantity": 1, "max_price": max_price,
                                "purpose": "manual_connection_check", "strategy_signal": False}}

    async def send(order_id, quantity, basis):
        _, current_ref, _ = eligible(basis["broker"], day)
        if current_ref != ref:
            raise control.Rejected("SETTINGS_CHANGED", "전송 직전 계좌가 변경되었습니다.")
        # 저장 설정은 바꾸지 않는다. 별도 소유권으로 기존 KIS 추적 경로를 사용한다.
        row = SimpleNamespace(**{c.name: getattr(basis["broker"], c.name) for c in BrokerSettings.__table__.columns})
        row.quant_mode = "live"
        return await auto_trade._place_live_order(row, SYMBOL, "삼성전자", "buy", quantity, basis["price"],
            str(uid), db=basis["db"], client_order_id=order_id)

    if not execute:
        async with get_session_factory()() as db:
            try:
                existing = await db.get(OrderIntent, intent.key)
                if existing:
                    return {"status": "DRY_RUN", "would_status": "DUPLICATE", "intent_id": intent.key}
                basis = await prepare(db)
                return {"status": "DRY_RUN", "quantity": 1, "price": basis["price"],
                        "intent_id": intent.key, "scope": "조회 사전 점검; 전송 시 잠금·전체 위험 검사를 다시 수행"}
            finally:
                await db.rollback()
    result = await control.execute(intent, 1, prepare, send)
    # 증권사 원문은 명령 출력에 복제하지 않는다.
    return {k: v for k, v in result.items() if k in ("status", "code", "reason", "intent_id", "duplicate", "client_order_id", "order_no", "environment")}
