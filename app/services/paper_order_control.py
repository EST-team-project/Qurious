"""국내주식 PAPER 주문의 공통 관문. TradingView는 KIS 경로에 연결하지 않는다."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import select

from app.models import PaperAccount, Portfolio, CryptoHolding, AlternativePosition
from app.services import execution_control as control, quant_valuation, trading_cost, live_ownership


async def execute(db, uid, info, side, quantity, *, source, signal_key=None, strategy_id="manual"):
    from app.services import paper_trading as pt
    account = (await db.execute(select(PaperAccount).where(PaperAccount.user_id == uid))).scalar_one_or_none()
    epoch = account.epoch if account else 1
    ref = control.digest([str(uid), "PAPER", epoch])
    intent = control.Intent(uid, ref, "PAPER", strategy_id, 1, info["symbol"], side,
        signal_key or uuid.uuid4().hex, source,
        control.digest([info["symbol"], side, quantity, strategy_id]))

    async def prepare(session):
        account = await pt.get_account(session, uid)
        if account.epoch != epoch:
            raise control.Rejected("ACCOUNT_CHANGED", "계좌가 초기화되어 주문을 보류합니다.")
        # 현금은 세 자산군이 공유한다. 혼합 계좌를 주식만 평가한 값으로 승인하지 않는다.
        for model in (CryptoHolding, AlternativePosition):
            if await session.scalar(select(model.id).where(model.user_id == uid, model.quantity > 0).limit(1)):
                raise control.Rejected("ACCOUNT_UNAVAILABLE", "혼합 자산 계좌의 공통 위험 평가가 준비되지 않아 주식 주문을 보류합니다.")
        fresh = await pt._confirm_quote(session, uid, info)
        rows = (await session.execute(select(Portfolio).where(Portfolio.user_id == uid, Portfolio.book == "PAPER"))).scalars().all()
        equity = float(account.cash)
        held, value = 0, 0.0
        for p in rows:
            price = fresh["price"] if p.symbol == info["symbol"] else (await quant_valuation.quote(session, uid, p.symbol, fresh=True))["price"]
            equity += p.quantity * price
            if p.symbol == info["symbol"]:
                held, value = int(p.quantity), p.quantity * price
        held = await live_ownership.virtual_quantity(session, intent, held)
        rate = trading_cost.cost_rate("buy", trading_cost.today_kst(), slippage_bps=0,
                                      market=trading_cost.market_of(info["symbol"]))
        return {"cash": float(account.cash) / (1 + rate), "equity": equity, "price": float(fresh["price"]),
                "position_value": value, "owned_quantity": held, "checked_at": datetime.now(timezone.utc),
                "db": session, "info": fresh}

    async def send(order_id, qty, basis):
        result = await pt._fill_stock_order(basis["db"], uid, basis["info"], side, qty, source=source)
        result.update({k: basis["info"].get(k) for k in ("quote_source", "quote_label", "market_open", "quote_as_of")})
        await basis["db"].commit()
        return result
    result = await control.execute(intent, quantity, prepare, send)
    if result.get("status") not in ("ok", "filled"):
        raise pt.PaperTradeError(result.get("reason") or "주문 결과 확인이 필요합니다.")
    return result
