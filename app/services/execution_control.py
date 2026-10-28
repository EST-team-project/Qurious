"""공통 주문 관문. DB 선점 뒤 전송하며, 결과가 불명확하면 같은 의도를 다시 보내지 않는다."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import uuid

from sqlalchemy import func, select, text
from app.database.postgres import get_session_factory
from app.models import BrokerSettings, OrderIntent, RiskDay, StrategyDecision, LiveOrder, Order
from app.services import risk_guard

KST = timezone(timedelta(hours=9))
current_intent = ContextVar("execution_intent", default=None)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class Rejected(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Intent:
    user_id: uuid.UUID
    account_ref: str
    book: str
    strategy_id: str
    strategy_version: int
    symbol: str
    side: str
    signal_key: str
    source: str
    input_hash: str

    @property
    def key(self):
        # source는 감사용이다. 즉시/정기 실행 또는 전달 경로만 바꿔 같은 판단을 재전송할 수 없다.
        return digest([str(self.user_id), self.account_ref, self.book, self.strategy_id,
                       self.strategy_version, self.symbol, self.side, self.signal_key])


@asynccontextmanager
async def account_lock(db, ref):
    """별도 연결의 session lock: 주문 함수의 commit에도 유지, 프로세스 종료 시 DB가 해제."""
    fingerprint = ref if re.fullmatch(r"[a-f0-9]{64}", ref) else digest(ref)
    key = int.from_bytes(bytes.fromhex(fingerprint[:16]), "big", signed=True)
    async with db.bind.connect() as conn:
        acquired = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
        await conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await conn.commit()
                except BaseException:
                    # 잠긴 연결을 풀에 돌려주면 다음 호출이 재진입 잠금을 얻을 수 있다.
                    await conn.invalidate()
                    raise


async def coordination_ready():
    try:
        redis = risk_guard._redis()
        if redis is None or not await redis.ping():
            raise RuntimeError
    except Exception:
        raise Rejected("CACHE_UNAVAILABLE", "중복 방지 저장소를 확인하지 못해 주문을 보류합니다.") from None


def check_limits(*, row, quantity, price, cash, equity, start_equity, orders_today,
                 position_value=0.0, owned_quantity=None, side="BUY", require_enabled=False):
    """카드·일반 자동매매·TradingView가 공유하는 순수 한도 검사. 수량 0은 강제 1주로 바꾸지 않는다."""
    if row and row.risk_kill_switch:
        raise Rejected("KILL_SWITCH", "비상 정지 상태입니다.")
    if require_enabled and (row is None or not row.quant_auto_enabled):
        raise Rejected("DISABLED", "자동매매가 중지되었습니다.")
    if type(quantity) is not int or side not in ("BUY", "SELL"):
        raise Rejected("INVALID_INPUT", "주문 방향·수량이 유효하지 않습니다.")
    if quantity <= 0:
        raise Rejected("ZERO_QUANTITY", "위험 한도·예산으로 주문할 수량이 없습니다.")
    values = (price, cash, equity, start_equity, position_value)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
        raise Rejected("ACCOUNT_UNAVAILABLE", "가격·계좌 평가를 확인하지 못했습니다.")
    if price <= 0 or min(cash, equity, start_equity, position_value) < 0:
        raise Rejected("ACCOUNT_UNAVAILABLE", "가격·계좌 평가가 유효하지 않습니다.")
    limits = risk_guard.RiskLimits.from_row(row)
    if any(not math.isfinite(x) or x < 0 for x in (limits.daily_loss_limit_pct, limits.max_position_pct,
                                                 limits.max_orders_per_day, limits.cooldown_min)):
        raise Rejected("INVALID_LIMITS", "위험 한도 설정이 유효하지 않습니다.")
    if risk_guard.daily_loss_breached(start_equity, equity, limits.daily_loss_limit_pct):
        raise Rejected("LOSS_LIMIT", "일손실 한도를 초과했습니다.")
    if limits.max_orders_per_day > 0 and orders_today >= limits.max_orders_per_day:
        raise Rejected("ORDER_LIMIT", "일 주문 수 한도에 도달했습니다.")
    if side == "SELL":
        if owned_quantity is None or type(owned_quantity) is not int or owned_quantity < quantity:
            raise Rejected("OWNERSHIP_UNCONFIRMED", "해당 전략의 매도 가능 보유를 확인하지 못했습니다.")
    else:
        if price * quantity > cash:
            raise Rejected("CASH_LIMIT", "주문 가능 현금이 부족합니다.")
        allowed, _ = risk_guard.cap_buy_quantity(quantity, price, position_value, equity, limits.max_position_pct)
        if allowed < quantity:
            raise Rejected("POSITION_LIMIT", "종목 비중 상한을 초과합니다.")
    return quantity


def blocked(code, message):
    return {"status": "skipped", "quantity": 0, "code": code, "reason": message}


async def execute(intent, quantity, prepare, send, *, require_enabled=False):
    """prepare(db)는 잠금 안에서 신선한 서버 자료를 읽고, send(id)는 그 자료로 한 번만 전송한다."""
    if not intent.signal_key or not intent.account_ref or not intent.input_hash:
        return blocked("INVALID_INPUT", "판단 식별자·계좌 근거가 없습니다.")
    record = None
    send_started = False
    try:
        async with get_session_factory()() as db:
            async with account_lock(db, intent.account_ref) as acquired:
                if not acquired:
                    return blocked("ACCOUNT_BUSY", "같은 계좌의 다른 실행이 진행 중입니다.")
                previous = await db.get(OrderIntent, intent.key)
                if previous:
                    if previous.input_hash != intent.input_hash:
                        return blocked("INPUT_CONFLICT", "같은 판단의 입력이 달라 재주문하지 않습니다.")
                    return {**previous.result, "status": previous.status if previous.status != "PENDING" else "unknown",
                            "duplicate": True, "intent_id": intent.key}
                uncertain = await db.scalar(select(OrderIntent.intent_id).where(
                    OrderIntent.account_ref == intent.account_ref,
                    OrderIntent.status.in_(("PENDING", "unknown"))).limit(1))
                if uncertain:
                    raise Rejected("OPEN_ORDER", "같은 계좌의 전송 결과 미확인 의도가 있습니다.")
                v1_pending = await db.scalar(select(StrategyDecision.decision_key).where(
                    StrategyDecision.account_ref == intent.account_ref, StrategyDecision.status.in_(("PENDING", "unknown"))).limit(1))
                if v1_pending:
                    raise Rejected("OPEN_ORDER", "같은 계좌의 카드 점검 결과가 미확인입니다.")
                await coordination_ready()
                preparation_started = datetime.now(timezone.utc)
                basis = await prepare(db)
                quantity = min(quantity, basis.get("max_quantity", quantity))
                now = datetime.now(timezone.utc)
                checked = basis.get("checked_at")
                if (not isinstance(checked, datetime) or checked.tzinfo is None or not 0 <= (now - checked).total_seconds() <= 10
                        or (now - preparation_started).total_seconds() > 10):
                    raise Rejected("STALE_DATA", "주문 직전 자료의 조회 시각이 유효하지 않습니다.")
                day = now.astimezone(KST).date()
                if any(not isinstance(basis.get(k), (int, float)) or isinstance(basis[k], bool)
                       or not math.isfinite(basis[k]) or basis[k] < 0 for k in ("cash", "equity", "price")):
                    raise Rejected("ACCOUNT_UNAVAILABLE", "계좌 평가 근거가 유효하지 않습니다.")
                baseline = await db.get(RiskDay, (intent.account_ref, day))
                if baseline is None:
                    baseline = RiskDay(account_ref=intent.account_ref, day=day, equity=basis["equity"])
                    db.add(baseline)
                    await db.commit()
                start = datetime.combine(day, datetime.min.time(), KST)
                count = await db.scalar(select(func.count()).select_from(OrderIntent).where(
                    OrderIntent.account_ref == intent.account_ref, OrderIntent.created_at >= start,
                    OrderIntent.status.in_(("PENDING", "unknown", "submitted", "filled"))))
                if intent.book == "KIS":
                    legacy = await db.scalar(select(func.count()).select_from(LiveOrder).where(
                        (LiveOrder.account_ref == intent.account_ref) | LiveOrder.raw.contains(intent.account_ref),
                        ~LiveOrder.client_order_id.startswith("intent:"), LiveOrder.created_at >= start,
                        LiveOrder.status.notin_(("ERROR", "REJECTED"))))
                else:
                    legacy = await db.scalar(select(func.count()).select_from(Order).where(
                        Order.user_id == intent.user_id, Order.created_at >= start, Order.status == "filled",
                        Order.execution_intent_id.is_(None),
                        Order.source == "QUANT" if intent.book == "QUANT" else Order.source != "QUANT"))
                row = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == intent.user_id)
                                       .execution_options(populate_existing=True))).scalar_one_or_none()
                original_limits = risk_guard.RiskLimits.from_row(row)
                original_settings = settings_signature(row)
                if "settings" in basis and basis["settings"] != original_settings:
                    raise Rejected("SETTINGS_CHANGED", "자료 조회 중 주문 설정이 변경됐습니다.")
                check_limits(row=row, quantity=quantity, price=basis["price"], cash=basis["cash"],
                    equity=basis["equity"], start_equity=baseline.equity,
                    orders_today=int(count or 0) + int(legacy or 0),
                    position_value=basis.get("position_value", 0), owned_quantity=basis.get("owned_quantity"),
                    side=intent.side, require_enabled=require_enabled)
                if original_limits.cooldown_min > 0:
                    recent = await db.scalar(select(OrderIntent.intent_id).where(
                        OrderIntent.account_ref == intent.account_ref, OrderIntent.symbol == intent.symbol,
                        OrderIntent.side == intent.side,
                        OrderIntent.created_at >= now - timedelta(minutes=original_limits.cooldown_min),
                        OrderIntent.status.in_(("PENDING", "unknown", "submitted", "filled"))).limit(1))
                    if recent:
                        raise Rejected("COOLDOWN", "같은 종목·방향의 주문 대기 시간이 지나지 않았습니다.")
                record = OrderIntent(intent_id=intent.key, user_id=intent.user_id, account_ref=intent.account_ref,
                    book=intent.book, strategy_id=intent.strategy_id, strategy_version=intent.strategy_version,
                    symbol=intent.symbol, side=intent.side, source=intent.source, input_hash=intent.input_hash,
                    status="PENDING", result={"quantity": quantity, "price": basis["price"], "intent_id": intent.key})
                db.add(record)
                await db.commit()  # 외부 전송보다 먼저 저장한다.
                # 오래 걸린 준비·설정 변경·저장소 장애는 선점 후에도 차단한다.
                await coordination_ready()
                latest = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == intent.user_id)
                                          .execution_options(populate_existing=True))).scalar_one_or_none()
                if risk_guard.RiskLimits.from_row(latest) != original_limits or settings_signature(latest) != original_settings:
                    raise Rejected("SETTINGS_CHANGED", "전송 직전 위험 설정이 변경됐습니다.")
                if latest and latest.risk_kill_switch or require_enabled and (latest is None or not latest.quant_auto_enabled):
                    raise Rejected("KILL_SWITCH", "전송 직전 중지 상태를 확인했습니다.")
                if (datetime.now(timezone.utc) - preparation_started).total_seconds() > 10:
                    raise Rejected("STALE_DATA", "전송 직전 조회 유효 시간이 지났습니다.")
                token = current_intent.set(intent)
                try:
                    send_started = True
                    result = await send("intent:" + intent.key[:57], quantity, basis)
                except Exception:
                    result = {"status": "unknown", "code": "EXECUTION_UNKNOWN", "reason": "전송·정산 결과 확인이 필요합니다."}
                finally:
                    current_intent.reset(token)
                record.status = result.get("status", "unknown")
                if record.status == "ok":
                    record.status = "filled"
                # 증권사 원문·키·계좌번호를 공통 실행 기록에 복제하지 않는다.
                record.result = {k: v for k, v in result.items() if k in
                    ("status", "quantity", "price", "code", "reason", "cash", "cash_balance", "symbol", "name", "side", "action", "client_order_id", "net_amount", "cost", "quote_source", "quote_label", "quote_as_of", "market_open")}
                if (result.get("live_order") or {}).get("client_order_id"):
                    record.result["client_order_id"] = result["live_order"]["client_order_id"]
                await db.commit()
                return {**result, "intent_id": intent.key}
    except Rejected as exc:
        result = blocked(exc.code, str(exc))
        if record is not None:
            try:
                async with get_session_factory()() as failed_db:
                    failed = await failed_db.get(OrderIntent, intent.key)
                    if failed and failed.status == "PENDING":
                        failed.status, failed.result = "skipped", result
                        await failed_db.commit()
            except Exception:
                pass  # 저장 실패는 기존 PENDING을 유지한다. 주문 전송은 없었다.
        return result
    except Exception:
        # DB 실패 여부와 전송 여부를 호출자가 추정해 재시도하지 않도록 명시한다.
        result = blocked("EXECUTION_STORE_UNAVAILABLE", "실행 기록을 확인하지 못했습니다. 기존 의도를 조회한 뒤 재개하세요.")
        if send_started:
            result["status"] = "unknown"
        return result


def settings_signature(row):
    if row is None:
        return None
    # 저장·출력하지 않는다. 준비 도중 계좌·전략·수량 설정이 바뀌면 해당 의도는 보류한다.
    return tuple(getattr(row, key, None) for key in ("broker", "paper", "app_key", "app_secret", "account_no",
        "quant_mode", "quant_auto_enabled", "quant_strategy_id", "quant_strategy_version",
        "quant_per_trade_budget", "quant_buy_ratio", "quant_sell_ratio"))
