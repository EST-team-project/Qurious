"""일반 자동매매 손절: 확정 일봉 ATR, 진입/전환 시 고정, 보유 회차별 저장."""
import asyncio
import math
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import LiveOrder, OrderIntent
from app.models.risk_stop import RiskStop
from app.services import collector_db, execution_control, live_ownership, market_calendar, ta_utils
from app.services.execution_policy import policy_for
from app.services.price_basis import adjusted_to_raw, positive

KST = ZoneInfo("Asia/Seoul")


def atr_distance(symbol, policy, *, now=None):
    now = now or datetime.now(KST)
    through = now.date() if now.time() >= time(15, 30) else now.date() - timedelta(days=1)
    calendar = market_calendar.trading_days(through - timedelta(days=14), through)
    days = [d["date"] for d in calendar["days"] if d["is_trading_day"]]
    if calendar.get("partial") or not days:
        raise ValueError("마지막 확정 거래일을 확인하지 못했습니다.")
    day = date.fromisoformat(days[-1])
    path = collector_db.db_path()
    if path is None:
        raise ValueError("ATR 계산용 수집 DB가 없습니다.")
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT p.bas_dt,p.hipr,p.lopr,p.clpr,a.adj_hipr,a.adj_lopr,a.adj_clpr,a.cum_factor "
            "FROM price_daily p LEFT JOIN price_adjusted a USING (bas_dt,srtn_cd) "
            "WHERE p.srtn_cd=? AND p.bas_dt<=? ORDER BY p.bas_dt DESC LIMIT 250",
            (symbol.split('.')[0], day.strftime('%Y%m%d'))).fetchall()[::-1]
    if len(rows) < 14 or rows[-1][0] != day.strftime('%Y%m%d'):
        raise ValueError("마지막 확정 일봉까지 ATR(14) 자료가 필요합니다.")
    adjusted = []
    for _, high, low, close, ah, al, ac, factor in rows:
        high, low, close, ah, al, ac, factor = [positive(v, "ATR 가격·계수") for v in (high, low, close, ah, al, ac, factor)]
        if not low <= close <= high or not al <= ac <= ah or any(
                not math.isclose(raw * factor, adj, rel_tol=1e-6, abs_tol=1)
                for raw, adj in ((high, ah), (low, al), (close, ac))):
            raise ValueError("ATR 원주가·수정주가 단위가 일치하지 않습니다.")
        adjusted.append((ah, al, ac))
    df = pd.DataFrame(adjusted, columns=["high", "low", "close"])
    atr = float(ta_utils.atr(df.high, df.low, df.close, 14).iloc[-1])
    return {"distance": adjusted_to_raw(atr, rows[-1][-1]) * policy.atr_mult,
            "atr_adjusted": atr, "factor": rows[-1][-1], "atr_as_of": day.isoformat()}


async def entry_basis(symbol, price, policy):
    price = positive(price, "손절 기준 가격")
    try:
        details = (await asyncio.to_thread(atr_distance, symbol, policy) if policy.stop_kind == "atr"
                   else {"distance": price * policy.stop_loss_pct / 100})
    except (sqlite3.Error, market_calendar.CalendarUnavailable) as exc:
        raise ValueError("확정 ATR 자료를 확인하지 못해 진입을 보류합니다.") from exc
    stop = positive(price - details["distance"], "손절선")
    return {**details, "stop_price": stop, "entry_price": price, "stop_kind": policy.stop_kind,
            "stop_loss_pct": policy.stop_loss_pct, "atr_mult": policy.atr_mult,
            "fixed_at": datetime.now(KST).isoformat(), "origin": "entry"}


async def _position_identity(db, uid, row, mode, position):
    if mode != "live":
        # 장부의 한 보유는 설정한 전략이 바뀌어도 같은 회차다. 타 전략 매도는 소유권 관문에서 막는다.
        key = execution_control.digest([str(uid), "QUANT", str(position.id)])
        entry_id = getattr(position, "risk_entry_intent_id", None)
        owner = await db.get(OrderIntent, entry_id) if entry_id else None
        if owner and (owner.user_id != uid or owner.book != "QUANT" or owner.symbol != position.symbol or owner.side != "BUY"):
            raise ValueError("진입 주문의 보유 귀속이 일치하지 않습니다.")
        return key, positive(float(position.avg_price), "평균매입가"), owner
    from app.services.brokers import stock_coin_trade_gateway as gateway
    strategy, version = live_ownership.strategy(row)
    ref = live_ownership.account_ref(row, gateway)
    orders = (await db.execute(select(LiveOrder).where(LiveOrder.user_id == uid, LiveOrder.account_ref == ref,
        LiveOrder.strategy_id == strategy, LiveOrder.strategy_version == version, LiveOrder.symbol == position.symbol)
        .order_by(LiveOrder.created_at, LiveOrder.id))).scalars().all()
    quantity, average, anchor = 0, 0.0, None
    for order in orders:
        qty = order.filled_quantity
        if not qty:
            continue
        if order.side == "BUY":
            if quantity == 0:
                anchor = order
            average = (average * quantity + positive(order.avg_filled_price, "확정 체결가") * qty) / (quantity + qty)
            quantity += qty
        elif order.side == "SELL":
            quantity -= qty
        else:
            raise ValueError("확정 체결 방향을 확인하지 못했습니다.")
        if quantity < 0:
            raise ValueError("전략 체결 순수량이 유효하지 않습니다.")
    if anchor is None or quantity != position.quantity or quantity <= 0:
        raise ValueError("손절 보유 회차를 확인하지 못했습니다.")
    key = execution_control.digest([str(uid), ref, strategy, version, str(anchor.id)])
    owner = (await db.execute(select(OrderIntent).where(OrderIntent.user_id == uid,
        OrderIntent.account_ref == ref, OrderIntent.strategy_id == strategy, OrderIntent.strategy_version == version,
        OrderIntent.symbol == position.symbol, OrderIntent.side == "BUY",
        OrderIntent.intent_id.startswith(anchor.client_order_id.removeprefix("intent:")))
        .limit(1))).scalar_one_or_none() if anchor.client_order_id.startswith("intent:") else None
    return key, average, owner


async def for_position(db, uid, row, mode, position):
    """원자적 최초 저장. 설정 변경이나 평균가 변경으로 손절 위험을 자동으로 넓히지 않는다."""
    if position is None or position.quantity <= 0:
        return None
    key, average, owner = await _position_identity(db, uid, row, mode, position)
    stored = await db.get(RiskStop, key)
    policy = policy_for(row)
    if stored is None:
        original = ((owner.result or {}).get("price_basis") or {}).get("stop") if owner else None
        if original:
            distance = average * original["stop_loss_pct"] / 100 if original["stop_kind"] == "pct" else original["distance"]
            basis = {**original, "distance": distance, "entry_price": average,
                     "stop_price": positive(average - distance, "손절선")}
        elif policy.size_kind == "risk_pct":
            basis = {**await entry_basis(position.symbol, average, policy), "origin": "transition"}
        else:
            return None
        await db.execute(insert(RiskStop).values(position_key=key, user_id=uid, basis=basis).on_conflict_do_nothing())
        # 주문 관문은 별도 연결의 계좌 잠금을 유지한다. 저장 경쟁에서는 먼저 고정된 값을 읽는다.
        await db.commit()
        stored = await db.get(RiskStop, key, populate_existing=True)
    if not math.isclose(average, stored.basis["entry_price"], rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError("보유 평균가가 고정 손절 기준과 달라 확인이 필요합니다. 자동 재설정하지 않습니다.")
    return dict(stored.basis)
