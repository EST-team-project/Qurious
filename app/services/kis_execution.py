"""KIS 직접 주문의 계좌 확인과 체결 조회. 주문번호 없는 주문은 추정 연결하지 않는다."""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from app.services.brokers.factory import get_broker_client
from app.services import kis_credentials

KST = timezone(timedelta(hours=9))


def account_key(app_key: str, account_no: str, environment: str) -> str:
    return hashlib.sha256(json.dumps([app_key, account_no.replace("-", ""), environment]).encode()).hexdigest()


def client_for(row):
    creds = kis_credentials.for_user(row)
    if creds is None or not creds.account_no:
        raise RuntimeError("KIS 인증 정보가 연결되지 않았습니다.")
    client = get_broker_client("kis", creds.app_key, creds.app_secret, paper=creds.paper)
    return client, creds


async def direct_status(order, broker_row) -> dict | None:
    """날짜·주문번호·종목·방향을 모두 대조한다. 미확인은 자동 재주문하지 않는다."""
    if not order.order_no or not order.created_at:
        return None
    client, creds = client_for(broker_row)
    meta = json.loads(order.raw or "{}")
    env = "paper" if client.paper else "real"
    if order.environment != env or meta.get("account_key") != account_key(creds.app_key, creds.account_no, env):
        raise RuntimeError("주문 당시 계좌와 현재 계좌 설정이 다릅니다.")
    date = order.created_at.astimezone(KST).strftime("%Y%m%d")
    fills = await client.get_daily_fills(creds.account_no, date, date, order.symbol[:6])
    candidates = [f for f in fills if f.broker_order_id.lstrip("0") == order.order_no.lstrip("0")
                  and f.order_date == date and f.symbol[:6] == order.symbol[:6]
                  and f.side.lower() == order.side.lower() and f.order_quantity == order.quantity]
    if len(candidates) != 1:
        return None
    f = candidates[0]
    if not 0 <= f.filled_quantity <= order.quantity or not math.isfinite(f.avg_fill_price) or (f.filled_quantity and f.avg_fill_price <= 0):
        raise RuntimeError("증권사 체결 수량·가격을 확인하지 못했습니다.")
    state = "FILLED" if f.filled_quantity == order.quantity else "CANCELLED" if f.cancelled else "PARTIALLY_FILLED" if f.filled_quantity else "ACCEPTED"
    return {"status": state, "filledQuantity": f.filled_quantity, "avgFilledPrice": f.avg_fill_price,
            "account_key": meta["account_key"], "orderNo": order.order_no}


async def account_snapshot(broker_row, gateway, symbols: dict) -> dict:
    """주문 판단의 현금·보유는 KIS에서 읽는다. 가상 장부로 대체하지 않는다."""
    if not broker_row or broker_row.broker != "kis":
        raise RuntimeError("KIS 연동 설정을 확인해 주세요.")
    lookup = {s[:6]: s for s in symbols}
    holdings = {}
    if gateway.is_configured():
        raw = await gateway.get_balance()
        if raw.get("cashBalance") is None or raw.get("totalEvalAmount") is None:
            raise RuntimeError("증권사 잔고 응답이 불완전합니다.")
        cash, equity = float(raw["cashBalance"]), float(raw["totalEvalAmount"])
        rows = [{"symbol": h["symbol"], "quantity": h.get("quantity", 0), "avg_price": h.get("avgPrice", 0),
                 "value": h.get("evalAmount", 0)} for h in raw.get("holdings", [])]
    else:
        client, creds = client_for(broker_row)
        raw = await client.get_balance(creds.account_no)
        cash, equity = float(raw.cash), float(raw.total_eval)
        rows = [{"symbol": h.symbol, "quantity": h.quantity, "avg_price": h.avg_price,
                 "value": h.eval_amount} for h in raw.holdings]
    if not math.isfinite(cash) or not math.isfinite(equity) or cash < 0 or equity < 0:
        raise RuntimeError("증권사 현금·평가액이 유효하지 않습니다.")
    for h in rows:
        if not all(math.isfinite(float(h[k])) and float(h[k]) >= 0 for k in ('quantity', 'avg_price', 'value')):
            raise RuntimeError("증권사 보유 수량·평가액이 유효하지 않습니다.")
        symbol = lookup.get(h["symbol"][:6], h["symbol"])
        if h["quantity"] > 0:
            holdings[symbol] = {**h, "symbol": symbol}
    return {"cash": cash, "equity": equity, "holdings": holdings, "checked_at": datetime.now(timezone.utc).isoformat()}
