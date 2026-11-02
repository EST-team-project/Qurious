"""개인 KIS 모의 취소·확정 잔량 재주문. 사용자 요청과 선택적 자동 재주문을 구분한다."""
import asyncio
from datetime import datetime, timedelta
import json
import math
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.database.postgres import get_session_factory
from app.models import BrokerCancelRequest, BrokerSettings, LiveOrder, LIVE_ORDER_OPEN_STATUSES
from app.services import (auto_trade, execution_control as control, kis_execution, live_ownership,
                          market_calendar, order_preflight, etf_execution)
from app.services.brokers import stock_coin_trade_gateway as gateway
from app.services.brokers.factory import live_trading_allowed
from app.services.execution_policy import policy_for


async def pause():
    await asyncio.sleep(1.1)


def check_window(day):
    """기존 C5와 같은 KRX 정규장. 자료가 불완전한 거래일은 허용하지 않는다."""
    now = datetime.now(control.KST)
    calendar = market_calendar.trading_days(day, day)
    if (now.date() != day or not gateway.is_krx_market_open(now)
            or calendar.get("partial") or not any(item["date"] == day.isoformat() and item["is_trading_day"]
                                                 for item in calendar.get("days", []))):
        raise control.Rejected("OUTSIDE_WINDOW", "확인된 KRX 정규장(09:00~15:30)에만 취소·재주문합니다.")


def context(row):
    if row is None or row.broker != "kis" or live_trading_allowed() or gateway.is_configured():
        raise control.Rejected("PAPER_ONLY", "개인 KIS 직접 모의 계좌만 지원합니다.")
    client, credentials = kis_execution.client_for(row)
    if not client.paper or not credentials.paper:
        raise control.Rejected("PAPER_ONLY", "개인 KIS 모의 계좌만 지원합니다.")
    return client, credentials, kis_execution.account_key(credentials.app_key, credentials.account_no, "paper")


async def parent_for(db, uid, order_id):
    parent = await db.scalar(select(LiveOrder).where(LiveOrder.id == order_id, LiveOrder.user_id == uid)
                             .execution_options(populate_existing=True))
    if parent is None:
        raise control.Rejected("ORDER_NOT_FOUND", "본인의 추적 주문을 찾을 수 없습니다.")
    if (parent.broker != "kis-direct" or parent.environment != "paper" or parent.order_type != "LIMIT"
            or not parent.account_ref or not parent.order_no or not parent.created_at):
        raise control.Rejected("UNSUPPORTED_ORDER", "계좌가 확인된 KIS 직접 모의 지정가 주문만 지원합니다.")
    return parent


def verify_account(parent, row):
    client, credentials, ref = context(row)
    if parent.account_ref != ref:
        raise control.Rejected("SETTINGS_CHANGED", "주문 당시 계좌와 현재 계좌가 다릅니다.")
    return client, credentials, ref


def apply_status(parent, latest):
    if (latest is None or latest.get("orderedQuantity") != parent.quantity
            or latest.get("quantityEvidenceComplete") is not True
            or type(latest.get("filledQuantity")) is not int
            or not parent.filled_quantity <= latest["filledQuantity"] <= parent.quantity):
        raise control.Rejected("ORDER_UNCONFIRMED", "증권사 원 주문·체결 수량을 확인하지 못했습니다.")
    if (not math.isfinite(latest.get("avgFilledPrice", float("nan")))
            or latest["filledQuantity"] and latest["avgFilledPrice"] <= 0):
        raise control.Rejected("ORDER_UNCONFIRMED", "증권사 체결 가격을 확인하지 못했습니다.")
    parent.status = latest["status"]
    parent.filled_quantity = latest["filledQuantity"]
    parent.avg_filled_price = latest["avgFilledPrice"]
    parent.raw = json.dumps(latest, ensure_ascii=False)


async def cancel(uid, order_id):
    """한 주문에 취소 전송은 한 번. 비상 정지 상태에서도 노출을 줄이는 취소는 허용."""
    try:
        async with get_session_factory()() as db:
            parent = await parent_for(db, uid, order_id)
            async with control.account_lock(db, parent.account_ref) as acquired:
                if not acquired:
                    return control.blocked("ACCOUNT_BUSY", "같은 계좌의 다른 실행이 진행 중입니다.")
                parent = await parent_for(db, uid, order_id)
                previous = await db.get(BrokerCancelRequest, parent.id)
                if previous:
                    return {"status": previous.status, "duplicate": True, "order_id": str(parent.id)}
                row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
                client, credentials, _ = verify_account(parent, row)
                day = datetime.now(control.KST).date()
                check_window(day)
                if parent.created_at.astimezone(control.KST).date() != day:
                    raise control.Rejected("OUTSIDE_WINDOW", "당일 주문만 취소 요청합니다.")
                latest = await kis_execution.direct_status(parent, row)
                apply_status(parent, latest)
                await db.commit()
                if parent.status in ("FILLED", "CANCELLED"):
                    return {"status": parent.status, "order_id": str(parent.id), "sent": False}
                remaining, organization = latest.get("remainingQuantity"), latest.get("organization", "")
                if (type(remaining) is not int or remaining <= 0 or remaining > parent.quantity-parent.filled_quantity
                        or not organization.isdigit()):
                    raise control.Rejected("CANCEL_UNCONFIRMED", "취소 가능 잔량 또는 원 접수의 주문조직번호를 확인하지 못했습니다.")
                signature = control.settings_signature(row)
                await pause()
                await db.refresh(row)
                verify_account(parent, row)
                if control.settings_signature(row) != signature:
                    raise control.Rejected("SETTINGS_CHANGED", "취소 직전 계좌 설정이 변경됐습니다.")
                check_window(day)
                request = BrokerCancelRequest(order_id=parent.id, quantity=remaining, status="UNKNOWN")
                db.add(request)
                parent.status = "CANCEL_REQUESTED"
                await db.commit()  # 프로세스 종료·응답 유실 뒤에도 취소를 재전송하지 않는다.
                try:
                    response = await client.cancel_order(credentials.account_no, parent.order_no, organization, remaining)
                    request.status = "ACCEPTED"
                    request.cancel_order_no = response["cancel_order_no"]
                except Exception:
                    # 거절·전송 오류 모두 다음 체결 조회로 원 주문 상태를 확인한다.
                    # API 예외 원문에는 계좌 정보가 있을 수 있어 저장/노출하지 않는다.
                    request.status = "UNKNOWN"
                await db.commit()
                return {"status": request.status, "order_id": str(parent.id),
                        "reason": "취소 접수 후 원 주문의 취소 확정 조회가 필요합니다."}
    except control.Rejected as exc:
        return control.blocked(exc.code, str(exc))
    except Exception:
        return {"status": "unknown", "code": "CANCEL_LOOKUP_REQUIRED", "reason": "원 주문과 취소 요청 기록을 확인하세요."}


def retry_policy(parent, row, automatic):
    if row.risk_kill_switch:
        raise control.Rejected("KILL_SWITCH", "비상 정지 상태입니다.")
    policy = policy_for(row)
    if automatic and (not policy.retry_enabled or not row.quant_auto_enabled or row.quant_mode != "live"
                      or live_ownership.strategy(row) != (parent.strategy_id, parent.strategy_version)):
        raise control.Rejected("DISABLED", "이 전략의 자동 재주문이 꺼져 있습니다.")
    now = datetime.now(control.KST)
    started = parent.retry_started_at or parent.created_at
    if not 0 <= (now-started).total_seconds() <= policy.retry_window_min*60:
        raise control.Rejected("RETRY_EXPIRED", "원 주문의 재주문 허용 시간이 지났습니다.")
    if (parent.retry_number or 0) >= policy.retry_max_attempts:
        raise control.Rejected("RETRY_LIMIT", "원 주문의 재주문 횟수 한도입니다.")
    check_window(now.date())
    return policy


async def retry(uid, order_id, *, automatic=False):
    """명시적 1회 요청 또는 설정된 자동 경로. 원 주문당 공통 의도·자식은 하나다."""
    try:
        async with get_session_factory()() as db:
            parent = await parent_for(db, uid, order_id)
            if parent.side != "SELL" or not parent.strategy_id:
                raise control.Rejected("UNSUPPORTED_ORDER", "전략 귀속이 있는 지정가 매도만 재주문합니다.")
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            _, _, ref = verify_account(parent, row)
            intent = control.Intent(uid, ref, "KIS", parent.strategy_id, parent.strategy_version,
                parent.symbol, "SELL", "cancelled:"+str(parent.id), "kis_cancelled_sell_retry",
                control.digest([str(parent.id), parent.quantity, parent.price, ref]))

        async def prepare(db):
            parent = await parent_for(db, uid, order_id)
            row = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == uid))
            _, _, current_ref = verify_account(parent, row)
            if current_ref != ref:
                raise control.Rejected("SETTINGS_CHANGED", "재주문 계좌가 변경됐습니다.")
            policy = retry_policy(parent, row, automatic)
            signature = control.settings_signature(row)
            latest = await kis_execution.direct_status(parent, row)
            apply_status(parent, latest)
            await db.commit()
            remaining = parent.quantity-parent.filled_quantity
            if (parent.status != "CANCELLED" or not latest.get("cancelled") or latest.get("remainingQuantity") != 0
                    or remaining <= 0 or latest.get("cancelledQuantity") not in (None, remaining)):
                raise control.Rejected("CANCEL_UNCONFIRMED", "원 주문의 잔량 전부 취소가 확정되지 않았습니다.")
            if await db.scalar(select(LiveOrder.id).where(LiveOrder.retry_of == parent.id)):
                raise control.Rejected("RETRY_EXISTS", "이미 연결된 재주문이 있습니다. 그 주문을 확인하세요.")
            opened = await db.scalar(select(LiveOrder.id).where(LiveOrder.account_ref == ref,
                LiveOrder.status.in_((*LIVE_ORDER_OPEN_STATUSES, "LOST"))).limit(1))
            if opened or latest.get("otherOpenOrders", 0):
                raise control.Rejected("OPEN_ORDER", "계좌의 접수·체결 미확인 주문이 있습니다.")
            await pause()
            snapshot = await kis_execution.account_snapshot(row, gateway, {parent.symbol: {}})
            owned, blocked = await live_ownership.reconcile(db, ref, snapshot, uid, parent.strategy_id, parent.strategy_version)
            if parent.symbol in blocked:
                raise control.Rejected("OWNERSHIP_UNCONFIRMED", blocked[parent.symbol])
            held = next((p.quantity for p in owned if p.symbol == parent.symbol), 0)
            quantity = min(remaining, held, snapshot["holdings"].get(parent.symbol, {}).get("quantity", 0))
            await pause()
            quote = await order_preflight.current_quote(db, uid, row, "live", parent.symbol)
            if (not math.isfinite(parent.price) or parent.price <= 0
                    or abs(quote["price"]/parent.price-1)*100 > policy.retry_price_deviation_pct):
                raise control.Rejected("PRICE_DEVIATION", "원 지정가와 현재가의 차이가 재주문 한도를 넘었습니다.")
            instrument = await asyncio.to_thread(etf_execution.describe, parent.symbol)
            if gateway.align_price_to_tick(parent.price, "sell", is_etf=instrument["is_etf"]) != parent.price:
                raise control.Rejected("INVALID_TICK", "원 지정가의 현재 호가 단위가 유효하지 않습니다.")
            holding = snapshot["holdings"].get(parent.symbol, {})
            equity = snapshot["equity"] + holding.get("quantity", 0)*quote["price"] - holding.get("value", 0)
            await pause()
            return {"db": db, "broker": row, "parent": parent, "settings": signature,
                    "cash": snapshot["cash"], "equity": equity, "quantity": quantity, "price": parent.price,
                    "owned_quantity": held, "checked_at": datetime.now(control.KST),
                    "price_basis": {"quote": quote, "parent_order_id": str(parent.id),
                                    "cancelled_remainder": remaining, "retry_number": (parent.retry_number or 0)+1}}

        async def send(client_id, quantity, basis):
            retry_policy(basis["parent"], basis["broker"], automatic)
            verify_account(basis["parent"], basis["broker"])
            row = SimpleNamespace(**{c.name: getattr(basis["broker"], c.name) for c in BrokerSettings.__table__.columns})
            row.quant_mode = "live"
            return await auto_trade._place_live_order(row, intent.symbol, basis["parent"].name, "sell",
                quantity, basis["price"], str(uid), db=basis["db"], client_order_id=client_id, retry_parent=basis["parent"])

        result = await control.execute(intent, parent.quantity, prepare, send, require_enabled=automatic)
        return {k: v for k, v in result.items() if k in ("status", "code", "reason", "intent_id", "duplicate", "client_order_id")}
    except control.Rejected as exc:
        return control.blocked(exc.code, str(exc))
    except Exception:
        return control.blocked("RETRY_LOOKUP_REQUIRED", "기존 주문과 재주문 기록을 확인해야 합니다.")


async def retry_cancelled_orders(limit=3):
    summary = {"submitted": 0, "skipped": 0, "errors": 0}
    if gateway.is_configured() or live_trading_allowed():
        return summary
    async with get_session_factory()() as db:
        child = aliased(LiveOrder)
        candidates = (await db.execute(select(LiveOrder.id, LiveOrder.user_id).join(
            BrokerSettings, BrokerSettings.user_id == LiveOrder.user_id).where(
                LiveOrder.broker == "kis-direct", LiveOrder.environment == "paper", LiveOrder.side == "SELL",
                LiveOrder.status == "CANCELLED", LiveOrder.created_at >= datetime.now(control.KST)-timedelta(minutes=120),
                ~select(child.id).where(child.retry_of == LiveOrder.id).exists(),
                BrokerSettings.quant_strategy_id == LiveOrder.strategy_id,
                BrokerSettings.quant_strategy_version == LiveOrder.strategy_version,
                BrokerSettings.quant_auto_enabled.is_(True), BrokerSettings.risk_kill_switch.is_(False),
                BrokerSettings.quant_execution_policy["retry_enabled"].as_boolean().is_(True))
            .order_by(LiveOrder.created_at.desc()).limit(min(limit, 3)))).all()
    for order_id, uid in candidates:
        result = await retry(uid, order_id, automatic=True)
        summary["submitted" if result.get("status") == "submitted" and not result.get("duplicate") else
                "errors" if result.get("status") == "unknown" else "skipped"] += 1
    return summary
