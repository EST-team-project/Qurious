"""개인 KIS 모의 수동 주문: 사용자 요청 ID, 공통 선점, 직접 체결 추적.

자동 전략 보유와 구분하기 위해 이 경로에서 확정된 보유만 매도한다.
요청 수량·지정가는 축소하거나 현재가로 바꾸지 않는다.
"""
from datetime import datetime, time
import math
from types import SimpleNamespace
import uuid

from sqlalchemy import select

from app.database.postgres import get_session_factory
from app.models import BrokerSettings, LiveOrder, OrderIntent, BrokerPositionBaseline, LIVE_ORDER_OPEN_STATUSES
from app.services import auto_trade, execution_control as control, kis_execution, live_ownership
from app.services import market_calendar, order_preflight, pattern_view, trading_cost
from app.services.brokers import stock_coin_trade_gateway as gateway
from app.services.brokers.factory import live_trading_allowed
from app.services.brokers.quote_feedback import balance_failure

STRATEGY = "manual_broker"
VERSION = 1


def request_key(uid, request_id):
    # 종목·방향·계좌를 바꾼 재전송도 같은 요청이다. input_hash로 충돌을 검사한다.
    return control.digest(["manual_broker_request_v1", str(uid), str(request_id)])


class ManualIntent(control.Intent):
    @property
    def key(self):
        return request_key(self.user_id, self.signal_key)


def eligible(row):
    if row is None or row.broker != "kis":
        raise control.Rejected("BROKER_NOT_CONFIGURED", "개인 KIS 계좌 연결이 필요합니다.")
    if live_trading_allowed() or gateway.is_configured():
        raise control.Rejected("PAPER_ONLY", "개인 KIS 직접 모의 주문만 지원합니다.")
    if row.risk_kill_switch:
        raise control.Rejected("KILL_SWITCH", "비상 정지 상태입니다.")
    try:
        client, creds = kis_execution.client_for(row)
    except Exception:
        raise control.Rejected("BROKER_NOT_CONFIGURED", "KIS 인증 정보를 확인하지 못했습니다.") from None
    if not client.paper or not creds.paper:
        raise control.Rejected("PAPER_ONLY", "개인 KIS 모의 계좌만 지원합니다.")
    return client, creds, kis_execution.account_key(creds.app_key, creds.account_no, "paper")


def check_window(day):
    now = datetime.now(control.KST)
    cal = market_calendar.trading_days(day, day)
    if (now.date() != day or not time(9) <= now.time().replace(tzinfo=None) < time(15, 20)
            or cal.get("partial") or not any(r["date"] == day.isoformat() and r["is_trading_day"]
                                             for r in cal.get("days", []))):
        raise control.Rejected("OUTSIDE_WINDOW", "확인된 거래일 09:00~15:20 KST에만 주문합니다.")


async def lookup(uid, request_id):
    """재시작·응답 유실 뒤에도 사용자 본인의 요청만 조회한다. 주문 재전송은 없다."""
    key = request_key(uid, request_id)
    async with get_session_factory()() as db:
        item = await db.get(OrderIntent, key)
        if item is None or item.user_id != uid or item.source != "manual_broker":
            return None
        order = await db.scalar(select(LiveOrder).where(
            LiveOrder.user_id == uid, LiveOrder.client_order_id == "intent:" + key[:57]))
        result = {"request_id": str(request_id), "intent_id": key,
                  "status": "unknown" if item.status == "PENDING" else item.status,
                  "symbol": item.symbol, "side": item.side,
                  "code": item.result.get("code"), "reason": item.result.get("reason")}
        if order is not None:
            result["order"] = {"client_order_id": order.client_order_id, "order_no": order.order_no,
                "status": order.status, "environment": order.environment,
                "quantity": order.quantity, "price": order.price,
                "filled_quantity": order.filled_quantity, "avg_filled_price": order.avg_filled_price}
            if order.status == "FILLED":
                result["status"] = "filled"
        return result


async def submit(uid, *, request_id, symbol, side, quantity, price):
    uid, request_id = uuid.UUID(str(uid)), uuid.UUID(str(request_id))
    # 이 서비스는 HTTP 외의 호출에도 같은 입력 경계를 적용한다.
    import re
    if (not isinstance(symbol, str) or not re.fullmatch(r"[0-9]{6}(?:\.(?:KS|KQ))?", symbol)
            or side not in ("buy", "sell") or type(quantity) is not int or not 0 < quantity <= 2147483647
            or isinstance(price, bool) or not isinstance(price, (int, float))
            or not math.isfinite(price) or price <= 0 or not float(price).is_integer()
            or not math.isfinite(price * quantity)):
        return control.blocked("INVALID_INPUT", "국내 종목·매수/매도·양의 정수 수량과 원 단위 지정가가 필요합니다.")
    symbol = pattern_view.resolve_symbol(symbol[:6])
    price = float(price)
    day = datetime.now(control.KST).date()
    try:
        async with get_session_factory()() as db:
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            _, _, ref = eligible(row)
        item = ManualIntent(uid, ref, "KIS", STRATEGY, VERSION, symbol, side.upper(), str(request_id),
                            "manual_broker", control.digest([ref, symbol, side, quantity, price]))

        async def prepare(db):
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            client, creds, current_ref = eligible(row)
            if current_ref != ref:
                raise control.Rejected("SETTINGS_CHANGED", "주문 계좌가 변경됐습니다.")
            signature = control.settings_signature(row)
            check_window(day)
            opened = await db.scalar(select(LiveOrder.id).where(
                (LiveOrder.account_ref == ref) | LiveOrder.raw.contains(ref),
                LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES, "LOST"))).limit(1))
            if opened:
                raise control.Rejected("OPEN_ORDER", "같은 계좌의 접수·체결 미확인 주문이 있습니다.")
            try:
                snapshot = await kis_execution.account_snapshot(row, gateway, {symbol: {"symbol": symbol}})
            except Exception as exc:
                detail = balance_failure(exc)
                raise control.Rejected(detail["code"], detail["message"] + " 주문을 전송하지 않았습니다.") from None
            owned, blocked = await live_ownership.reconcile(db, ref, snapshot, uid, STRATEGY, VERSION)
            baseline = await db.get(BrokerPositionBaseline, (ref, symbol))
            if symbol in blocked and (side == "sell" or baseline is not None):
                raise control.Rejected("OWNERSHIP_UNCONFIRMED", blocked[symbol])
            held = next((r.quantity for r in owned if r.symbol == symbol), 0)
            quote = await order_preflight.current_quote(db, uid, row, "live", symbol)
            current = quote["price"]
            holding = snapshot["holdings"].get(symbol, {})
            account_qty = holding.get("quantity", 0)
            equity = snapshot["equity"] + account_qty * current - holding.get("value", 0)
            cash = snapshot["cash"]
            if side == "buy":
                try:
                    power = await client.get_buying_power(creds.account_no, symbol, price)
                    amount, available = power["amount"], power["quantity"]
                    if (isinstance(amount, bool) or not isinstance(amount, (int, float))
                            or not math.isfinite(amount) or amount < 0 or type(available) is not int or available < 0):
                        raise ValueError
                except Exception:
                    raise control.Rejected("BUYING_POWER_UNAVAILABLE", "미수 없는 주문 가능 금액·수량을 확인하지 못했습니다.") from None
                cash = min(cash, amount) / (1 + trading_cost.cost_rate("buy", day, slippage_bps=0,
                                                                   market=trading_cost.market_of(symbol)))
                if available < quantity:
                    raise control.Rejected("BUYING_POWER_LIMIT", "요청 수량이 미수 없는 매수 가능 수량을 초과합니다.")
                await live_ownership.ensure_baseline(db, ref, symbol, snapshot)
            return {"db": db, "broker": row, "settings": signature, "cash": cash, "equity": equity,
                "price": price, "quantity": quantity, "owned_quantity": held,
                "position_value": account_qty * max(current, price), "checked_at": datetime.now(control.KST),
                "price_basis": {"quote": quote, "limit_price": price, "quantity": quantity, "purpose": "manual_broker"}}

        async def send(order_id, qty, basis):
            check_window(day)
            _, _, current_ref = eligible(basis["broker"])
            if current_ref != ref:
                raise control.Rejected("SETTINGS_CHANGED", "전송 직전 계좌가 변경됐습니다.")
            # 자동매매 설정을 저장하거나 다른 전략에 수동 보유를 편입하지 않는다.
            row = SimpleNamespace(**{c.name: getattr(basis["broker"], c.name) for c in BrokerSettings.__table__.columns})
            row.quant_mode = "live"
            return await auto_trade._place_live_order(row, symbol, symbol, side, qty, price, str(uid),
                db=basis["db"], client_order_id=order_id)

        result = await control.execute(item, quantity, prepare, send)
        # 원문·자격증명·계좌 식별 해시는 응답에 복제하지 않는다.
        public = {k: v for k, v in result.items() if k in ("status", "code", "reason", "intent_id", "duplicate")}
        public["request_id"] = str(request_id)
        # 충돌한 새 입력에 원 주문 내용을 붙여 성공처럼 보이지 않게 한다.
        if result.get("status") != "skipped":
            try:
                tracked = await lookup(uid, request_id)
                if tracked:
                    public.update(tracked)
            except Exception:
                # 전송 뒤 조회 장애를 재주문 가능한 실패로 바꾸지 않는다.
                public.update(status="unknown", code="EXECUTION_STORE_UNAVAILABLE",
                              reason="주문 결과 조회가 필요합니다. 같은 요청 ID로 확인하세요.")
        return public
    except control.Rejected as exc:
        return {**control.blocked(exc.code, str(exc)), "request_id": str(request_id)}
    except Exception:
        return {**control.blocked("EXECUTION_STORE_UNAVAILABLE", "실행 기록을 확인하지 못했습니다."),
                "request_id": str(request_id)}
