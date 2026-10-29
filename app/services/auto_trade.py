"""주기 자동매매(QUANT_CYCLE_SEC, 기본 10분) - PostgreSQL 기반.

실행 모델
  - 활성 여부는 BrokerSettings.quant_auto_enabled(DB)에 저장한다. 앱 재시작·다중 인스턴스에서도 상태가 유지된다.
  - 주기 실행은 Celery Beat(`quant.auto_trade_cycle`, QUANT_CYCLE_SEC 기본 10분)이 활성 사용자 전원에 대해 run_cycle_for_enabled_users()를 돌린다.
  - 시작 시에는 즉시 1회 사이클을 백그라운드로 실행해 화면 반응을 준다(인프로세스 루프는 더 이상 쓰지 않는다).
  - 사이클 로그는 data_cache(`quant:cycle_log:{uid}`)에 최근 50개를 남겨 API 프로세스와 워커가 공유한다.

장부 (강사님 원본 2026-09-29 방식 · Qurious 2026-09-30 반영)
  - 가상매매(paper)만 **자기 장부**를 쓴다: 현금 `QuantVirtualAccount`(초기 1천만 원) + 보유 `Portfolio.book = QUANT`.
    모의투자 · 직접매매 · 리밸런싱 · TradingView 는 `PaperAccount` + `book = PAPER` 다. 두 장부는 섞이지 않는다.
  - 예전(두 장부가 보유 표 하나를 같이 써서) 자동매매가 산 주식이 모의투자 화면에 「없는 수익」 으로 잡히던
    결함을, Qurious I14(2026-09-28)는 현금을 `PaperAccount` 하나로 합쳐 고쳤다. 강사님 원본은 장부를 나눠
    고쳤고, 기초 코드를 따르려고 이 방식을 택했다 — 장부를 하나로 둘지는 팀 논의 거리다(D7 ③).
  - Qurious 가 더한 것: 주문 비용(세금 · 수수료 · ETF 면세 — `trading_cost`) · 실거래 차단(`live_trading_allowed`)
    · 현금 행 잠금(FOR UPDATE — 즉시 1회 실행과 예약 사이클이 겹쳐도 차감이 덮어써지지 않게).
  - 강사님 9478811(2026-10-03 반영): 게이트웨이 실주문 · 합격 전략 · 실계좌 위험 한도 · 체결 확인은 그대로 받았다.
    바꾼 것 셋 — KIS 키는 사용자마다(`kis_credentials`) · 게이트웨이에도 실거래 승인 관문 · SageMaker 배치 점수 없음.
  - #212: KIS 연동(live)은 가상 장부를 변경하지 않는다. KIS 잔고로 판단하고 live_orders에
    접수·실패·응답 불명 상태를 남긴 뒤 별도 체결 조회로 수량·가격을 확인한다.
"""
import asyncio
import sqlite3
import json
import logging
import uuid
import math
from weakref import WeakValueDictionary
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.stock import get_quant_indicators, QUANT_STOCKS
from app.database.postgres import get_session_factory
from app.models import BrokerSettings, Order, Portfolio, QuantVirtualAccount, PORTFOLIO_BOOK_QUANT, LiveOrder, LIVE_ORDER_OPEN_STATUSES
from app.models.base import SYSTEM_USER_ID
from app.services import notification
from app.services import strategy_loader
from app.config import settings as app_settings
from datetime import timedelta
from app.services import risk_guard, quant_valuation
from app.services.audit import audit
from app.services.brokers.factory import get_broker_client, live_trading_allowed
from app.services import kis_credentials
from app.services.brokers import stock_coin_trade_gateway as gateway
from app.services.data_cache import cache_get, cache_set
from app.services import trading_cost
from app.services import aggressive_mode
from app.services.execution_policy import policy_for, risk_quantity
from app.services.trade_outcome import describe_trade, failure_message
from app.services import kis_execution, live_ownership, execution_control, order_preflight
from app.services.strategy_execution import card_symbols, validate_rule_input
from app.services.decision_signal_view import signal_view
from types import SimpleNamespace

logger = logging.getLogger(__name__)

_auto_trade_tasks: dict[uuid.UUID, asyncio.Task] = {}
_control_locks: WeakValueDictionary[uuid.UUID, asyncio.Lock] = WeakValueDictionary()
_INTERVAL_SEC = int(app_settings.QUANT_CYCLE_SEC)   # celery_app.beat_schedule 과 같은 값
_INITIAL_CAPITAL = 10_000_000


def _resolve_user_id(raw: str) -> uuid.UUID:
    if raw == "quant_system" or not raw:
        return SYSTEM_USER_ID
    return uuid.UUID(raw)


def _log_key(uid: uuid.UUID) -> str:
    return f"quant:cycle_log:{uid}"


async def _persist_cycle(uid: uuid.UUID, cycle_log: dict) -> None:
    """사용자별 DB 캐시에만 기록한다. 캐시가 비면 다른 사용자의 로그로 대체하지 않는다."""
    from app.services.execution_runs import cycle_result
    summary = cycle_result.get()
    if summary is not None:
        statuses = [t.get("status") for t in cycle_log.get("trades", [])]
        state = cycle_log.get("execution_state") or ("FAILED" if any(s in ("error", "unknown") for s in statuses)
            else "BLOCKED" if cycle_log.get("note") or (cycle_log.get("risk") or {}).get("halted")
            or any(s == "skipped" for s in statuses) else "COMPLETED")
        summary.update(status=state, orders=sum(s in ("submitted", "filled") for s in statuses),
                       note=cycle_log.get("note", ""))
    try:
        cached = await cache_get(_log_key(uid), max_age_hours=24 * 30) or {}
        cycles = (cached.get("cycles") or [])[-49:] + [cycle_log]
        await cache_set(_log_key(uid), {"cycles": cycles})
    except Exception:
        logger.exception("사이클 로그 저장 실패 user=%s", uid)
        if summary is not None:
            raise  # 실행 기록과 실패 알림에서 로그 장애를 확인할 수 있게 한다.


async def is_enabled(db: AsyncSession, uid: uuid.UUID) -> bool:
    row = (await db.execute(select(BrokerSettings.quant_auto_enabled).where(BrokerSettings.user_id == uid))).scalar_one_or_none()
    return bool(row)


async def set_enabled(db: AsyncSession, uid: uuid.UUID, enabled: bool) -> None:
    row = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))).scalar_one_or_none()
    if row is None:
        row = BrokerSettings(user_id=uid)
        db.add(row)
    row.quant_auto_enabled = enabled
    await db.commit()


async def get_status(db: AsyncSession, uid: uuid.UUID) -> dict:
    """DB 플래그 + 공유 캐시 로그 기반 상태 (프로세스에 무관)."""
    enabled = await is_enabled(db, uid)
    cached = await cache_get(_log_key(uid), max_age_hours=24 * 30) or {}
    cycles = cached.get("cycles") or []
    # 저장된 옛 filled는 가상 장부 기록이다. 응답에서는 증권사 근거와 분리한다.
    ids = {t["live_order"]["client_order_id"] for c in cycles for t in c.get("trades", [])
           if (t.get("live_order") or {}).get("client_order_id")}
    tracked = {}
    if ids:
        rows = (await db.execute(select(LiveOrder).where(
            LiveOrder.user_id == uid, LiveOrder.client_order_id.in_(ids)))).scalars().all()
        tracked = {r.client_order_id: {"status": r.status, "filled_quantity": r.filled_quantity,
                                      "avg_filled_price": r.avg_filled_price} for r in rows}
    output = []
    for c in cycles:
        trades = []
        for t in c.get("trades", []):
            proof = tracked.get((t.get("live_order") or {}).get("client_order_id"))
            execution = describe_trade(t, (c.get("settings") or {}).get("mode"), proof)
            trades.append({**t, "status": execution["status"], "virtual_status": execution["virtual_status"],
                           "execution": execution})
        output.append({**c, "trades": trades, "signals": [
            signal_view(sig, c.get("settings") or {}, c.get("time")) for sig in c.get("signals", [])
        ]})
    cycles = output
    last_risk = next((c.get("risk") for c in reversed(cycles) if c.get("risk")), {})
    return {
        "running":      enabled,
        "scheduler":    f"celery-beat ({max(1, _INTERVAL_SEC // 60)}분)",
        "user_id":      str(uid),
        "interval_sec": _INTERVAL_SEC,
        "risk":         last_risk,
        "log":          cycles[-50:],
        "last_cycle_at": cycles[-1]["time"] if cycles else None,
    }


def is_running(user_id: str | None = None) -> bool:
    """즉시 실행 작업 상태. 인자를 생략하면 프로세스 전체를 확인한다."""
    if user_id is not None:
        task = _auto_trade_tasks.get(_resolve_user_id(user_id))
        return bool(task and not task.done())
    return any(not task.done() for task in _auto_trade_tasks.values())


async def _execute_virtual_trade(
    db: AsyncSession,
    user_id: uuid.UUID,
    symbol: str,
    name: str,
    action: str,
    price: float,
    quantity: int,
    reason: str,
    *, filled_at: datetime | None = None, strict_quantity: bool = False,
) -> dict:
    """가상계좌 체결. 주문 삽입 + 포트폴리오 갱신 + 현금 갱신을 한 트랜잭션으로 커밋한다.

    장부는 자동매매 전용(`QuantVirtualAccount` 현금 + `book = QUANT` 보유 · 모듈 머리말).
    계좌 행을 FOR UPDATE 로 잠그므로, 아래 모든 반환 경로가 `commit` 으로 잠금을 푼다.
    """
    if filled_at is not None:
        intent = execution_control.current_intent.get()
        if (filled_at.tzinfo is None or filled_at > datetime.now(timezone.utc) or not intent
                or (intent.book, intent.strategy_id, intent.strategy_version, intent.source)
                != ("QUANT", "ma_cross_20_60", 2, "v2_next_open")):
            raise ValueError("판 2의 서버 확인된 다음 시가 체결 문맥이 필요합니다.")
    now = datetime.now(timezone.utc).isoformat()

    result = await db.execute(
        select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == user_id).with_for_update()
    )
    account = result.scalar_one_or_none()
    if not account:
        account = QuantVirtualAccount(
            user_id=user_id, initial_capital=float(_INITIAL_CAPITAL), cash_balance=float(_INITIAL_CAPITAL),
        )
        db.add(account)
        await db.flush()

    cash_balance = float(account.cash_balance)
    executed_quantity = quantity

    market = trading_cost.market_of(symbol)
    today = filled_at.astimezone(timezone(timedelta(hours=9))).date() if filled_at else trading_cost.today_kst()
    # ETF·ETN 은 증권거래세 과세대상이 아니다. 넘기지 않으면 기본값 False 가 되어
    # **매도 정산에서 0.20%p 를 더 떼게 된다** (2026-09-21 까지 그랬다).
    is_etf = trading_cost.is_etf_name(name)

    def _net(side: str, qty: int) -> float:
        """정산금액. 매수는 나가는 현금, 매도는 들어오는 현금."""
        return trading_cost.order_costs(
            side=side, price=price, quantity=qty, when=today, market=market, is_etf=is_etf,
        ).net_amount

    if action == "buy":
        cost = _net("buy", quantity)
        if cash_balance < cost:
            if strict_quantity:
                raise ValueError("예약한 전량의 비용 포함 현금이 부족합니다.")
            # 수수료까지 감당할 수 있는 수량을 구한다. 단가로만 나누면 수수료만큼
            # 초과해 주문이 잔고를 넘긴다.
            buy_rate = trading_cost.cost_rate("buy", today, slippage_bps=0.0, market=market)
            max_qty = int(cash_balance // (price * (1 + buy_rate))) if price > 0 else 0
            while max_qty > 0 and _net("buy", max_qty) > cash_balance:
                max_qty -= 1
            if max_qty <= 0:
                shortfall = cost - cash_balance
                await db.commit()
                return {
                    "time": now, "symbol": symbol, "name": name,
                    "action": action, "quantity": 0, "price": price,
                    "reason": (
                        f"{reason} | 잔고 부족으로 미체결 "
                        f"(필요 {cost:,.0f}원 / 부족 {shortfall:,.0f}원 / 가용현금 {cash_balance:,.0f}원)"
                    ),
                    "status": "skipped",
                    "cash_balance": round(cash_balance, 2),
                }
            executed_quantity = max_qty

    port_result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id, Portfolio.symbol == symbol, Portfolio.book == PORTFOLIO_BOOK_QUANT))
    existing = port_result.scalar_one_or_none()

    if action == "sell":
        if strict_quantity and (not existing or existing.quantity < quantity):
            raise ValueError("예약한 전략 전량의 장부 보유가 부족합니다.")
        if not existing or existing.quantity <= 0:
            await db.commit()
            return {
                "time": now, "symbol": symbol, "name": name,
                "action": action, "quantity": 0, "price": price,
                "reason": f"{reason} | 보유 수량 없음",
                "status": "skipped",
                "cash_balance": round(cash_balance, 2),
            }
        executed_quantity = min(quantity, existing.quantity)

    order_cost = trading_cost.order_costs(
        side=action, price=price, quantity=executed_quantity, when=today, market=market,
        is_etf=is_etf,
    )
    fields = trading_cost.order_fields(order_cost, price, executed_quantity)
    if filled_at is not None:
        fields["filled_at"] = filled_at
    db.add(Order(
        user_id=user_id, symbol=symbol, name=name, order_type=action,
        quantity=executed_quantity, price=price, status="filled", broker="quant_ai", source="QUANT",
        execution_intent_id=execution_control.current_intent.get().key if execution_control.current_intent.get() else None,
        **fields,
    ))

    if action == "buy":
        if existing:
            new_qty = existing.quantity + executed_quantity
            existing.avg_price = (existing.avg_price * existing.quantity + price * executed_quantity) / new_qty
            existing.quantity = new_qty
        else:
            db.add(Portfolio(user_id=user_id, symbol=symbol, name=name, quantity=executed_quantity, avg_price=price, book=PORTFOLIO_BOOK_QUANT))
        cash_balance -= order_cost.net_amount
    elif action == "sell":
        new_qty = max(0, existing.quantity - executed_quantity)
        if new_qty == 0:
            await db.delete(existing)
        else:
            existing.quantity = new_qty
        cash_balance += order_cost.net_amount

    account.cash_balance = float(cash_balance)
    await db.commit()

    return {
        "time": now, "symbol": symbol, "name": name,
        "action": action, "quantity": executed_quantity, "price": price, "reason": reason,
        "status": "filled",
        "cash_balance": round(cash_balance, 2),
        "cost": order_cost.as_dict(),
    }


async def _place_live_order(
    broker_row: BrokerSettings | None,
    symbol: str,
    name: str,
    side: str,
    quantity: int,
    price: float,
    user_id: str,
    db: AsyncSession | None = None,
    *, client_order_id: str | None = None, decision_record=None,
) -> dict | None:
    """KIS 연동(live) 모드의 증권사 주문. 가상 장부 체결은 만들지 않는다.

    접수 전 추적 행을 저장하고 실패·응답 불명·접수를 구분한다.
    체결은 별도 조회로 확인하며, 응답 불명 주문은 실패로 단정하지 않는다.

    ★ 실거래 주문은 rfp-2 §4.2 의 **제외 범위**다. 그래서 `quant_mode == "live"` 라
    해도 실계좌로 나가지 않는다 — `QURIOUS_ALLOW_LIVE_TRADING` 이 켜져 있지 않으면
    모의투자 경로로 요청한다. 팩토리에도 같은 관문이 있어 두 겹으로 막힌다
    (`app/services/brokers/factory.py` 모듈 설명 참조).
    """
    if not broker_row or broker_row.quant_mode != "live":
        return None
    intent = execution_control.current_intent.get()
    if intent:
        client_order_id = "intent:" + intent.key[:57]
    broker = (broker_row.broker or "mock").strip().lower()
    if broker == "kis" and gateway.is_configured():
        # 구축안 경로: stock-coin-trade Open API(승인 토큰 → 주문 → 감사로그) 경유. 체결은 quant.confirm_fills 가 확인한다.
        return await _place_live_order_via_gateway(db, broker_row, symbol, name, side, quantity, price, user_id)
    # 사용자 키 길은 실전을 「요청」 하는 길이다 — 승인 없이는 모의(아래 관문 · 팩토리). 우리 판은 서버 관리 증권사가 없다.
    paper = not live_trading_allowed()
    if kis_credentials.is_managed(broker):
        # KIS 자격증명은 서버(Secrets Manager)가 관리한다. DB 행의 키는 쓰지 않는다.
        creds = await kis_credentials.get_credentials()
        if creds is None:
            logger.warning("KIS 자격증명 미연동 — live 주문 생략 (%s %s)", side, symbol)
            return {"status": "skipped", "broker": broker, "reason": "kis_credentials_not_configured"}
        app_key, app_secret, account_no, paper = creds.app_key, creds.app_secret, creds.account_no, creds.paper
    else:
        app_key = broker_row.app_key
        app_secret = broker_row.app_secret
        account_no = broker_row.account_no
    if broker == "mock" or not app_key or not app_secret or not account_no:
        return {"status": "skipped", "broker": broker, "reason": "broker_not_configured"}

    # 3-way(강사님 9478811 · 2026-10-03): 강사님 판은 자격증명이 정한 `paper`, 우리 판은 실거래 승인 관문이다.
    # 둘 다 지킨다 — 모의로 정해졌으면 모의, 아니면 승인(QURIOUS_ALLOW_LIVE_TRADING) 없이는 모의(팩토리에도 같은 관문).
    client = get_broker_client(
        broker, app_key, app_secret, paper=paper or not live_trading_allowed()
    )
    env = "paper" if paper or not live_trading_allowed() else "real"
    direct_row = None
    if broker == "kis" and db is not None:
        direct_row = LiveOrder(user_id=_resolve_user_id(user_id), client_order_id=client_order_id or "direct:" + uuid.uuid4().hex,
                               environment=env, broker="kis-direct", symbol=symbol, name=name, side=side.upper(),
                               order_type="LIMIT", quantity=quantity, price=price, status="PENDING",
                               raw=json.dumps({"account_key": kis_execution.account_key(app_key, account_no, env)}))
        if intent:
            direct_row.account_ref = intent.account_ref
            direct_row.strategy_id = intent.strategy_id
            direct_row.strategy_version = intent.strategy_version
        db.add(direct_row)
        if decision_record is not None:
            await db.flush()
            decision_record.client_order_id = direct_row.client_order_id
        await db.commit()  # 추적 기록 저장에 실패하면 주문을 전송하지 않는다.

    async def record(outcome):
        if direct_row is not None:
            direct_row.status = {"submitted": "ACCEPTED", "error": "ERROR", "unknown": "UNKNOWN"}[outcome["status"]]
            direct_row.order_no = outcome.get("order_no", "")
            direct_row.message = failure_message(outcome) if outcome["status"] == "error" else "주문 응답·체결 확인 대기"
            await db.commit()
            outcome["client_order_id"] = direct_row.client_order_id
        return outcome

    try:
        result = await client.place_order(account_no, symbol, side, quantity, price)
        order_no = str((result.get("output") or {}).get("ODNO") or (result.get("output") or {}).get("odno") or "")
    except Exception as e:
        logger.warning("실전 자동매매 주문 실패 (%s, %s %s): %s", broker, side, symbol, e)
        code = getattr(e, "code", "")
        outcome = {"status": "unknown" if code == "ORDER_SUBMISSION_UNKNOWN" else "error",
                   "broker": broker, "code": code, "error": str(e)}
        message = "접수 여부 미확인 — 재주문 전에 증권사 주문 내역을 확인해 주세요." if outcome["status"] == "unknown" else failure_message(outcome)
        await record(outcome)
        try:
            await notification.notify_order_error(
                symbol=symbol, side=side, quantity=quantity, price=price,
                error=message, user_id=user_id,
            )
        except Exception:
            logger.exception("증권사 실패 알림 전송 실패 user=%s symbol=%s", user_id, symbol)
        return outcome
    if broker == "kis" and not order_no:
        return await record({"status": "unknown", "broker": broker, "code": "ORDER_SUBMISSION_UNKNOWN"})
    outcome = await record({"status": "submitted", "broker": broker, "response": result, "order_no": order_no,
                            "environment": env, "tracking": "direct" if direct_row else "unavailable"})
    # 알림 전송 장애를 이미 접수한 증권사 주문 실패로 바꾸지 않는다.
    try:
        await notification.notify_order_placed(
            symbol=symbol, side=side, quantity=quantity, price=price,
            broker=f"{broker.upper()} {'모의' if paper or not live_trading_allowed() else '실전'} · 체결 미확인", user_id=user_id)
    except Exception:
        logger.exception("증권사 접수 알림 전송 실패 user=%s symbol=%s", user_id, symbol)
    return outcome


async def _report_execution(db, broker_row, trade: dict, user_id: str, *, mode="paper") -> None:
    """KIS 주문 결과와 가상매매 알림을 모드에 맞게 처리한다."""
    if mode == "live":
        try:
            result = await _place_live_order(broker_row, trade["symbol"], trade.get("name", trade["symbol"]),
                                            trade["action"], trade["quantity"], trade["price"], user_id, db=db)
        except Exception:
            logger.exception("자동매매 주문 결과 저장 실패 user=%s symbol=%s", user_id, trade["symbol"])
            result = {"status": "unknown", "code": "ORDER_SUBMISSION_UNKNOWN"}
        trade["live_order"] = result or {"status": "skipped", "reason": "broker_not_configured"}
    else:
        await notification.notify_auto_trade_executed(
            symbol=trade["symbol"], name=trade.get("name", trade["symbol"]), action=trade["action"],
            quantity=trade["quantity"], price=trade["price"], reason=trade.get("reason", ""), user_id=user_id)


async def _execute_trade(db, uid, broker_row, mode, symbol, name, action, price, quantity, reason, *, decision=None):
    return await order_preflight.execute_quant(db, uid, broker_row, mode, symbol, name, action,
                                              quantity, reason, decision or {})


async def _execute_trade_unchecked(db, uid, broker_row, mode, symbol, name, action, price, quantity, reason):
    if mode == "paper":
        trade = await _execute_virtual_trade(db, uid, symbol, name, action, price, quantity, reason)
        if trade.get("status") == "filled":
            await _report_execution(db, None, trade, str(uid))
        return trade
    trade = {"time": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "name": name,
             "action": action, "quantity": quantity, "price": price, "reason": reason,
             "status": "pending", "virtual_status": "not_recorded"}
    await _report_execution(db, broker_row, trade, str(uid), mode="live")
    trade["status"] = trade["live_order"]["status"]
    return trade


_SIGNAL_SCORE_SCALE = 8.0   # stock.py 지표 점수(대략 -8~+8)를 스펙 임계값([-1,1])과 비교하기 위한 정규화 분모


def apply_strategy_spec_to_symbols(target_symbols: list[str], spec: dict) -> list[str]:
    """카드 universe 전체를 평가한다. AI 상위 목록이나 max_symbols로 잘라내지 않는다."""
    return card_symbols(spec, [s["symbol"] for s in QUANT_STOCKS] + target_symbols)


_ml_meta: dict = {}   # 마지막으로 로드한 배치 학습 메타(generated_at 등) — 사이클 로그에 기록


async def symbol_ml_score(symbol: str) -> float | None:
    """배치 점수가 없는 종목의 보조 ML 점수: 캔들로 Ridge 5일 수익률 예측(ml_symbol_score). 실패 시 None."""
    try:
        from app.services.stock import get_candles
        from app.services.ml_symbol_score import symbol_score

        data = await get_candles(symbol, period="2y")
        return symbol_score(data.get("candles") or [])
    except Exception as exc:
        logger.info("종목별 ML 점수 계산 생략 (%s): %s", symbol, exc)
        return None


async def ml_scores_by_symbol() -> dict[str, float]:
    """종목별 배치 ML 점수 — 우리 판은 늘 빈 dict.

    강사님 판은 SageMaker 배치 학습 결과(S3 의 scores.json · `quant_ai_scores`)를 [-1,1] 로 정규화해 돌려준다.
    Qurious 는 2026-09-15 에 AWS 를 걷어내 그 모듈이 없다 — 스펙에 LightGBM 가중이 있으면 사이클이
    캔들 Ridge 점수(`symbol_ml_score`)로 대신한다(tests/test_base_code_merge_guard.py).
    """
    _ml_meta.clear()
    return {}


def _sma_last(values: list[float], window: int, offset: int = 0) -> float | None:
    """values[-1-offset] 기준 단순이동평균. 데이터 부족이면 None."""
    end = len(values) - offset
    if window <= 0 or end - window < 0:
        return None
    seg = values[end - window:end]
    return sum(seg) / window


def evaluate_spec_rules(spec: dict, indicators: dict) -> dict | None:
    """스펙 entry/exit 규칙(ma_cross / momentum / buy_hold / dca)을 지표의 종가 시계열로 직접 평가한다.

    반환 {"entry": bool, "exit": bool, "detail": str} 또는 평가 불가(지원하지 않는 indicator·데이터 부족)면 None.
    """
    closes = [float(c) for c in (indicators.get("closes") or []) if c is not None]
    if not closes:
        return None

    def _eval(rule: dict) -> bool | None:
        ind = str(rule.get("indicator") or "")
        cond = str(rule.get("condition") or "")
        params = rule.get("params") or {}
        if cond == "always":
            return True
        if cond == "never":
            return False
        if ind == "ma_cross":
            s, l = int(params.get("short_window", 5)), int(params.get("long_window", 20))
            ss, ll = _sma_last(closes, s), _sma_last(closes, l)
            if ss is None or ll is None:
                return None
            return ss > ll if cond == "short_above_long" else ss < ll if cond == "short_below_long" else None
        if ind == "momentum":
            w = int(params.get("breakout_window", 20))
            if len(closes) < w + 1:
                return None
            window = closes[-w - 1:-1]
            return closes[-1] > max(window) if cond == "breakout_high" else closes[-1] < min(window) if cond == "breakdown_low" else None
        return None

    entry, exit_ = _eval(spec.get("entry") or {}), _eval(spec.get("exit") or {})
    if entry is None and exit_ is None:
        return None
    detail = f"규칙 {((spec.get('entry') or {}).get('indicator'))}: 진입={entry} 청산={exit_}"
    return {"entry": bool(entry), "exit": bool(exit_), "detail": detail}


def apply_strategy_spec_to_signal(signal: dict, spec: dict, ml_score: float | None = None, indicators: dict | None = None) -> dict:
    """지표 점수를 [-1,1]로 정규화하고(LightGBM 점수가 있으면 스펙 가중 합산) buy/sell 임계값으로 action 을 다시 판정한다."""
    weights = spec.get("signal_weights") or {}
    buy_th = float(weights.get("buy_threshold", 0.6))
    sell_th = float(weights.get("sell_threshold", -0.6))
    w_tech = float(weights.get("technical", 1.0))
    w_ml = float(weights.get("lightgbm", 0.0))
    score = float(signal.get("score", 0) or 0)
    technical = max(-1.0, min(1.0, score / _SIGNAL_SCORE_SCALE))
    if ml_score is not None and w_ml > 0 and (w_tech + w_ml) > 0:
        normalized = (w_tech * technical + w_ml * max(-1.0, min(1.0, float(ml_score)))) / (w_tech + w_ml)
        ml_tag = f", ML {float(ml_score):+.2f}×{w_ml:g} + 지표 {technical:+.2f}×{w_tech:g}"
    else:
        normalized = technical
        ml_tag = "" if w_ml <= 0 else " (ML 점수 없음 → 지표만)"
    normalized = round(max(-1.0, min(1.0, normalized)), 4)
    rules = evaluate_spec_rules(spec, indicators) if indicators else None
    if normalized >= buy_th:
        action = "강력 매수" if normalized >= min(1.0, buy_th + 0.25) else "매수"
    elif normalized <= sell_th:
        action = "강력 매도" if normalized <= max(-1.0, sell_th - 0.25) else "매도"
    else:
        action = "관망"
    tag = f"전략 {spec.get('strategy_id')} v{spec.get('version')}: 정규화 점수 {normalized:+.2f} (매수≥{buy_th:+.2f} / 매도≤{sell_th:+.2f}){ml_tag}"
    reasons = [*(signal.get("reasons") or []), tag]
    if rules is not None:
        # 스펙의 entry/exit 규칙을 직접 평가할 수 있으면 규칙이 action 을 결정한다(청산 우선). 임계값 점수는 참고로만 남긴다.
        action = "매도" if rules["exit"] else "매수" if rules["entry"] else "관망"
        reasons.append(rules["detail"] + " → " + action)
    return {**signal, "action": action, "normalized_score": normalized, "rule_based": rules is not None, "reasons": reasons}


async def _place_live_order_via_gateway(
    db: AsyncSession | None,
    broker_row: BrokerSettings,
    symbol: str,
    name: str,
    side: str,
    quantity: int,
    price: float,
    user_id: str,
) -> dict:
    """stock-coin-trade 게이트웨이로 KIS 주문을 내고 live_orders 에 추적 행을 남긴다.

    가상 장부는 변경하지 않는다. 확정 실패는 ERROR, 응답 불명은 UNKNOWN으로 남긴다.
    UNKNOWN은 열린 주문으로 유지하여 새 주문을 막고 체결 확인 작업에서 확인한다.
    """
    uid = _resolve_user_id(user_id)
    env = gateway.environment()
    if gateway.enforce_market_hours() and not gateway.is_krx_market_open():
        logger.info("장 운영시간 외 — 실주문 생략 (%s %s x%d)", side, symbol, quantity)
        return {"status": "skipped", "broker": "kis", "via": "stock-coin-trade", "environment": env, "reason": "market_closed"}
    if env == "real" and risk_guard._redis() is None:
        # 쿨다운·일 주문 수가 메모리 폴백(프로세스 재시작 시 초기화) 상태면 실전 주문은 내지 않는다. 모의(paper)는 허용.
        logger.warning("Redis 미연결(위험관리 메모리 폴백) — 실전 주문 생략 (%s %s x%d)", side, symbol, quantity)
        return {"status": "skipped", "broker": "kis", "via": "stock-coin-trade", "environment": env, "reason": "risk_store_unavailable"}
    try:
        client_order_id = gateway.make_client_order_id(str(uid), symbol, side)
    except gateway.GatewayError as e:
        return {"status": "error", "broker": "kis", "via": "stock-coin-trade", "error": str(e)}

    row: LiveOrder | None = None
    if db is not None:
        row = LiveOrder(
            user_id=uid, client_order_id=client_order_id, environment=env, broker="kis",
            symbol=symbol, name=name, side=side.upper(), order_type=_live_order_type(),
            quantity=quantity, price=float(price), status="PENDING",
        )
        db.add(row)
        await db.commit()

    try:
        result = await gateway.place_order(symbol, side, quantity, price, client_order_id=client_order_id, order_type=_live_order_type())
    except gateway.GatewayError as e:
        logger.warning("게이트웨이 실주문 실패 (%s %s x%d): [%s] %s", side, symbol, quantity, e.code, e)
        if row is not None:
            # UNREACHABLE 은 KIS가 받았을 수도 있으므로 UNKNOWN 으로 두고 confirm_fills 가 clientOrderId 로 확인한다.
            row.status = "UNKNOWN" if e.code == "GATEWAY_UNREACHABLE" else "ERROR"
            row.message = f"[{e.code}] {e}"[:300]
            row.raw = json.dumps(e.details, ensure_ascii=False)[:4000]
            await db.commit()
        detail = "접수 여부 미확인 — 재주문 전에 증권사 주문 내역을 확인해 주세요." if e.code == "GATEWAY_UNREACHABLE" else "증권사 주문 실패. " + failure_message({"code": e.code})
        await notification.notify_order_error(symbol=symbol, side=side, quantity=quantity, price=price, error=detail, user_id=user_id)
        return {"status": "unknown" if e.code == "GATEWAY_UNREACHABLE" else "error", "broker": "kis", "via": "stock-coin-trade", "environment": env, "code": e.code, "error": str(e), "client_order_id": client_order_id}

    order = result["order"]
    if row is not None:
        # 주문 응답의 FILLED 문자열만으로 체결 확인을 끝내지 않는다. 후속 체결 조회에 남긴다.
        row.status = "ACCEPTED" if order.get("status") == "FILLED" else str(order.get("status") or "ACCEPTED")
        row.order_no = str(order.get("orderNo") or "")
        row.price = float(result["intent"].get("price") or price)
        row.message = str(order.get("message") or "")[:300]
        row.raw = json.dumps(order, ensure_ascii=False)[:4000]
        await db.commit()
    if order.get("status") in ("ERROR", "REJECTED"):
        await notification.notify_order_error(symbol=symbol, side=side, quantity=quantity, price=price,
                                               error="증권사가 주문을 거절했습니다.", user_id=user_id)
        return {"status": "error", "broker": "kis", "via": "stock-coin-trade", "environment": env,
                "client_order_id": client_order_id, "code": "BROKER_REJECTED"}
    await notification.notify_order_placed(symbol=symbol, side=side, quantity=quantity, price=float(result["intent"].get("price") or price),
                                           broker=f"KIS({env}) via stock-coin-trade", user_id=user_id)
    return {"status": "submitted", "broker": "kis", "via": "stock-coin-trade", "environment": env,
            "order_no": order.get("orderNo"), "client_order_id": client_order_id, "duplicate": result["duplicate"], "response": order}


def _live_order_type() -> str:
    """게이트웨이 주문 유형: 공격 모드면 QUANT_AGGRESSIVE_ORDER_TYPE(기본 MARKET), 아니면 env 기본값."""
    if aggressive_mode.is_enabled():
        ot = aggressive_mode.order_type()
        if ot:
            return ot
    return gateway.default_order_type()


async def open_live_order_exposure(db: AsyncSession, uid: uuid.UUID) -> dict[str, float]:
    """미체결 매수 실주문의 (잔여수량 × 주문가) 합을 종목별로 돌려준다."""
    result = await db.execute(
        select(LiveOrder).where(LiveOrder.user_id == uid, LiveOrder.side == "BUY", LiveOrder.status.in_(LIVE_ORDER_OPEN_STATUSES))
    )
    exposure: dict[str, float] = {}
    for row in result.scalars().all():
        remaining = max(0, int(row.quantity) - int(row.filled_quantity or 0))
        if remaining and row.price:
            exposure[row.symbol] = exposure.get(row.symbol, 0.0) + remaining * float(row.price)
    return exposure


async def live_account_daily_loss(user_id: str, limit_pct: float) -> dict:
    """게이트웨이 잔고의 총평가액으로 실계좌 당일 손익률을 계산한다. 조회 실패 시 breached=False 로 사이클을 막지 않는다."""
    env = gateway.environment()
    try:
        balance = await gateway.get_balance()
    except gateway.GatewayError as e:
        logger.warning("실계좌 잔고 조회 실패 — 실계좌 일손실 점검 생략: [%s] %s", e.code, e)
        return {"environment": env, "error": f"[{e.code}] {e}", "breached": False}
    equity = float(balance.get("totalEvalAmount") or 0) or float(balance.get("cashBalance") or 0)
    if equity <= 0:
        return {"environment": env, "error": "평가액 0", "breached": False}
    start = await risk_guard.day_start_equity(f"{user_id}:live:{env}", equity)
    pnl = risk_guard.daily_pnl_pct(start, equity)
    return {"environment": env, "day_start_equity": round(start, 2), "equity": round(equity, 2), "day_pnl_pct": pnl,
            "breached": risk_guard.daily_loss_breached(start, equity, limit_pct)}


async def cancel_open_live_orders(db: AsyncSession, uid: uuid.UUID, reason: str = "") -> dict:
    """사용자의 미체결 실주문(ACCEPTED/PARTIALLY_FILLED)을 게이트웨이로 전량 취소 요청한다. kill switch 에서 호출."""
    summary = {"requested": 0, "failed": 0, "skipped": 0}
    result = await db.execute(
        select(LiveOrder).where(LiveOrder.user_id == uid, LiveOrder.status.in_(("ACCEPTED", "PARTIALLY_FILLED")))
    )
    for row in result.scalars().all():
        if not row.order_no or row.broker == "kis-direct" or not gateway.is_configured():
            if row.broker == "kis-direct":
                row.message = "자동매매는 중지됐습니다. 직접 주문의 취소는 KIS 주문 내역에서 확인해 주세요."
            summary["skipped"] += 1
            continue
        try:
            latest = await gateway.cancel_order(row.order_no, env=row.environment)
            row.status = str(latest.get("status") or "CANCEL_REQUESTED")
            row.message = (f"비상 정지 취소: {reason}" if reason else "비상 정지 취소")[:300]
            summary["requested"] += 1
        except gateway.GatewayError as e:
            row.message = f"취소 실패 [{e.code}] {e}"[:300]
            summary["failed"] += 1
            logger.warning("비상 정지 취소 실패 (%s): [%s] %s", row.client_order_id, e.code, e)
    await db.commit()
    return summary


async def confirm_live_fills(limit: int = 100) -> dict:
    """열린 live_orders 를 KIS 직접/게이트웨이 체결 조회로 갱신한다."""
    summary = {"checked": 0, "updated": 0, "filled": 0, "errors": 0, "skipped": 0}
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(
            select(LiveOrder).where(LiveOrder.status.in_(LIVE_ORDER_OPEN_STATUSES)).order_by(LiveOrder.created_at).limit(limit)
        )
        rows = list(result.scalars().all())
        for row in rows:
            summary["checked"] += 1
            try:
                if row.broker == "kis-direct":
                    broker = await db.scalar(select(BrokerSettings).where(BrokerSettings.user_id == row.user_id))
                    latest = await kis_execution.direct_status(row, broker)
                    if latest is None:
                        row.message = "접수·체결 근거 미확인 — KIS 주문 내역에서 확인 필요. 자동 재주문하지 않습니다."
                        summary["skipped"] += 1
                        continue
                elif not gateway.is_configured():
                    summary["skipped"] += 1
                    continue
                elif row.order_no:
                    latest = await gateway.get_order_status(row.order_no, env=row.environment)
                elif row.status == "UNKNOWN" and row.client_order_id:
                    # 조회 경로에서 재전송하면 원 요청이 도착하지 않은 경우 새 주문이 된다.
                    # 계좌·의도 확인이 끝날 때까지 UNKNOWN을 보존한다(시간 경과로 노출을 풀지 않음).
                    row.message = "접수 여부 미확인 — 조회 작업에서는 재전송하지 않습니다. 증권사 주문 내역 확인 필요"
                    summary["skipped"] += 1
                    continue
                else:
                    if row.retry_of is not None:
                        # 준비만 저장한 뒤 작업이 중단된 경우: 종목·수량 추정으로 다른 주문과 연결하지 않는다.
                        row.message = "재주문 준비 후 전송 미확인. 새 주문 없이 수동 확인 대기"
                        summary["skipped"] += 1
                        continue
                    # 같은 종목·수량은 다른 주문일 수 있다. 주문번호 없이 체결을 추정하지 않는다.
                    row.message = "주문번호 미확인 — KIS 주문 내역에서 확인 필요. 종목·수량으로 추정 연결하지 않습니다."
                    summary["skipped"] += 1
                    continue
            except Exception as e:
                summary["errors"] += 1
                logger.warning("체결 확인 실패 (%s): %s", row.client_order_id, e)
                continue
            if latest.get("lookup") not in (None, ""):
                row.message = "잔고 변화에 따른 추정은 체결 확정 근거가 아닙니다. 증권사 체결 내역 확인 대기"
                summary["skipped"] += 1
                continue
            new_status = str(latest.get("status") or row.status)
            try:
                fill_qty = int(latest.get("filledQuantity") or 0)
                fill_price = float(latest.get("avgFilledPrice") or 0)
            except (TypeError, ValueError, OverflowError):
                summary["errors"] += 1
                row.message = "체결 수량·가격 응답을 해석할 수 없어 상태 갱신을 보류합니다."
                continue
            if (not (int(row.filled_quantity or 0) <= fill_qty <= row.quantity)
                    or not math.isfinite(fill_price) or (fill_qty > 0 and fill_price <= 0)
                    or (new_status == "FILLED" and fill_qty != row.quantity)):
                summary["errors"] += 1
                row.message = "체결 수량·가격 응답이 불완전해 상태 갱신을 보류합니다."
                continue
            changed = new_status != row.status or int(latest.get("filledQuantity") or 0) != row.filled_quantity
            row.status = new_status
            row.filled_quantity = int(latest.get("filledQuantity") or 0)
            row.avg_filled_price = float(latest.get("avgFilledPrice") or 0)
            row.raw = json.dumps(latest, ensure_ascii=False)[:4000]
            if changed:
                summary["updated"] += 1
            if changed and new_status == "FILLED":
                summary["filled"] += 1
                # 주문 기준가(row.price) 대비 증권사 체결가의 괴리.
                if row.price and row.avg_filled_price:
                    slip = (row.avg_filled_price / row.price - 1) * 100
                    row.message = f"체결 완료 · 슬리피지 {slip:+.3f}% (주문 기준 {row.price:,.0f} → 증권사 체결 {row.avg_filled_price:,.0f})"[:300]
                    summary.setdefault("slippage_pct", []).append(round(slip, 3))
                await notification.notify_order_filled(
                    symbol=row.symbol, side=row.side.lower(), quantity=row.filled_quantity,
                    price=row.avg_filled_price, environment=row.environment, user_id=str(row.user_id),
                )
            # 미체결 N분 경과 → 취소 요청 (설정 0이면 끔)
            cancel_after = int(getattr(app_settings, "STOCK_COIN_TRADE_CANCEL_OPEN_AFTER_MIN", 0) or 0)
            if row.broker != "kis-direct" and cancel_after > 0 and new_status in ("ACCEPTED", "PARTIALLY_FILLED") and row.order_no and row.created_at:
                age = datetime.now(timezone.utc) - row.created_at.astimezone(timezone.utc)
                if age >= timedelta(minutes=cancel_after):
                    try:
                        cancelled = await gateway.cancel_order(row.order_no, env=row.environment)
                        row.status = str(cancelled.get("status") or "CANCEL_REQUESTED")
                        row.message = f"{cancel_after}분 미체결 자동 취소 요청"[:300]
                        summary["cancelled"] = summary.get("cancelled", 0) + 1
                    except gateway.GatewayError as e:
                        summary["errors"] += 1
                        logger.warning("미체결 자동 취소 실패 (%s): [%s] %s", row.client_order_id, e.code, e)
        await db.commit()
    return summary


async def emergency_halt(db: AsyncSession, broker_row: BrokerSettings | None, user_id: str, reason: str,
                         day_pnl_pct: float | None = None) -> None:
    """비상 정지: kill switch를 DB에 켜고 루프를 멈추고 알림을 보낸다."""
    if broker_row is not None:
        broker_row.risk_kill_switch = True
        broker_row.risk_halt_reason = reason[:300]
        broker_row.quant_auto_enabled = False
        await db.commit()
    stop_auto_trade(user_id)
    actions = {"auto_disabled": broker_row is not None, "kill_switch_set": broker_row is not None,
               "cancel_orders": {"status": "unknown"}, "notification": "pending"}
    try:
        cancelled = await cancel_open_live_orders(db, _resolve_user_id(user_id), reason)
        actions["cancel_orders"] = {"status": "checked", **cancelled,
                                     "confirmation": "취소 요청 결과이며 취소 확정은 별도 확인"}
        if cancelled.get("requested") or cancelled.get("failed"):
            logger.warning("비상 정지 — 미체결 실주문 취소 요청 %s", cancelled)
    except Exception as exc:  # 취소 실패가 비상 정지 자체를 막으면 안 된다
        actions["cancel_orders"] = {"status": "failed", "reason": "취소 요청 결과 확인 실패"}
        logger.exception("비상 정지 중 미체결 취소 실패: %s", exc)
    try:
        await notification.notify_risk_halt(reason, day_pnl_pct, user_id=user_id)
        actions["notification"] = "dispatched"
    except Exception:
        actions["notification"] = "failed"
        logger.exception("비상 정지 알림 실패 user=%s", user_id)
    await audit(user_id, "", "auto_trade.emergency_halt",
                {"reason": reason, "day_pnl_pct": day_pnl_pct, "actions": actions})
    logger.warning("자동매매 비상 정지 user=%s: %s", user_id, reason)


async def _run_quant_cycle(user_id: str = "quant_system") -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cycle_log: dict = {"time": now_str, "trades": [], "signals": []}

    try:
        session_factory = get_session_factory()
    except Exception:
        return  # PostgreSQL 미연결 시 스킵

    uid = _resolve_user_id(user_id)

    async with session_factory() as db:
        bs_result = await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))
        broker_row = bs_result.scalar_one_or_none()
        try:
            execution = policy_for(broker_row)
        except ValueError:
            await _persist_cycle(uid, {**cycle_log, "execution_state": "FAILED", "note": "주문 수량·재주문 설정 오류로 자동매매를 보류합니다."})
            return

        mode = broker_row.quant_mode if broker_row and broker_row.quant_mode in ("paper", "live") else (
            "live" if broker_row and broker_row.paper is False else "paper"
        )
        if broker_row and (broker_row.quant_strategy_id, broker_row.quant_strategy_version) == ("ma_cross_20_60", 2):
            from app.services import strategy_v2, strategy_v2_execution
            try:
                spec = await strategy_loader.get_strategy("ma_cross_20_60", 2)
                if spec is None:
                    raise ValueError("선택한 판 2 명세를 확인하지 못했습니다.")
                strategy_v2.validate_card(spec)
                result = await strategy_v2_execution.run(uid, execute=True, require_enabled=True)
            except ValueError as exc:
                result = {"status": "skipped", "code": "V2_INPUT_INVALID", "reason": str(exc)}
            cycle_log.update(strategy={"strategy_id": "ma_cross_20_60", "version": 2},
                execution_state="FAILED" if result.get("status") in ("unknown", "error") else "BLOCKED" if result.get("status") == "skipped" else "COMPLETED",
                note=result.get("reason", "판 2 다음 거래일 시가 가상 실행"), v2=result,
                trades=[result] if result.get("status") == "filled" and not result.get("duplicate") else [])
            await _persist_cycle(uid, cycle_log)
            return
        if mode == "paper":
            result = await db.execute(select(QuantVirtualAccount).where(QuantVirtualAccount.user_id == uid))
            if not result.scalar_one_or_none():
                db.add(QuantVirtualAccount(
                    user_id=uid, initial_capital=float(_INITIAL_CAPITAL), cash_balance=float(_INITIAL_CAPITAL),
                ))
                await db.commit()

        symbol_source = broker_row.quant_symbol_source if broker_row and broker_row.quant_symbol_source in ("ai", "manual") else "ai"
        selected_symbols = list(broker_row.quant_selected_symbols or []) if broker_row else []
        ai_top_n = max(1, min(int(broker_row.quant_ai_top_n if broker_row else 3), len(QUANT_STOCKS)))
        per_trade_budget = float(broker_row.quant_per_trade_budget if broker_row else 1_000_000)
        per_trade_budget = max(10_000.0, min(per_trade_budget, 10_000_000.0))
        buy_ratio = float(broker_row.quant_buy_ratio if broker_row else 1.0)
        buy_ratio = max(0.1, min(buy_ratio, 1.0))
        sell_ratio = float(broker_row.quant_sell_ratio if broker_row else 0.5)
        sell_ratio = max(0.1, min(sell_ratio, 1.0))

        limits = risk_guard.RiskLimits.from_row(broker_row)
        aggressive = aggressive_mode.is_enabled()
        if aggressive:
            limits = aggressive_mode.apply_limits(limits)   # 쿨다운·일 주문 수만 덮어씀
        if limits.kill_switch:
            cycle_log["risk"] = {"halted": True, "reason": (broker_row.risk_halt_reason if broker_row else "") or "비상 정지 스위치 ON"}
            cycle_log["note"] = "비상 정지 상태 — 주문을 내지 않습니다."
            await _persist_cycle(uid, cycle_log)
            await set_enabled(db, uid, False)   # 비상 정지 상태면 자동매매 플래그도 내린다
            return

        price_map: dict[str, float] = {}
        indicator_map: dict[str, dict] = {}
        stock_map = {s["symbol"]: s for s in QUANT_STOCKS}

        for stock in QUANT_STOCKS:
            try:
                indicators = (await aggressive_mode.get_intraday_indicators(stock["symbol"]) if aggressive
                              else await get_quant_indicators(stock["symbol"], "2y"))
                indicator_map[stock["symbol"]] = indicators
                signal = indicators.get("signal", {})
                price = indicators.get("current_price")
                if not price:
                    continue
                price_map[stock["symbol"]] = float(price)

            except Exception:
                logger.exception("자동매매 지표 계산 실패: %s", stock["symbol"])
                cycle_log["signals"].append({"symbol": stock["symbol"], "error": "지표 계산 실패"})

        if symbol_source == "manual":
            target_symbols = [s for s in selected_symbols if s in stock_map]
            if not target_symbols:
                target_symbols = [s["symbol"] for s in QUANT_STOCKS[:ai_top_n]]
        else:
            ranked = []
            for stock in QUANT_STOCKS:
                indicators = indicator_map.get(stock["symbol"], {})
                sig = indicators.get("signal", {})
                score = sig.get("score", 0)
                ranked.append((stock["symbol"], score))
            ranked.sort(key=lambda item: item[1], reverse=True)
            pool = max(ai_top_n, 2 * int(app_settings.QUANT_AGGRESSIVE_MAX_BUYS_PER_CYCLE), 5) if aggressive else ai_top_n
            target_symbols = [sym for sym, _ in ranked[:pool]]

        strategy_spec: dict | None = None
        ml_scores: dict[str, float] = {}
        ml_weight_on = False
        strategy_log = {"id": "", "version": 0, "applied": False}
        if broker_row and broker_row.quant_strategy_id:
            strategy_log.update(id=broker_row.quant_strategy_id, version=broker_row.quant_strategy_version or 0)
            strategy_spec = await strategy_loader.get_strategy(broker_row.quant_strategy_id, broker_row.quant_strategy_version or None)
            if strategy_spec:
                try:
                    target_symbols = apply_strategy_spec_to_symbols(target_symbols, strategy_spec)
                    if aggressive:
                        raise ValueError("카드 규칙과 공격 모드를 동시에 실행할 수 없습니다.")
                except (ValueError, TypeError, sqlite3.Error) as exc:
                    strategy_log["error"] = str(exc)
                    await _persist_cycle(uid, {**cycle_log, "strategy": strategy_log, "execution_state": "FAILED", "note": "전략 카드 검증 실패 — 주문 보류"})
                    return
                for symbol in target_symbols:
                    if symbol not in stock_map:
                        stock_map[symbol] = {"symbol": symbol, "name": symbol}
                    if symbol not in indicator_map:
                        try:
                            indicator_map[symbol] = await get_quant_indicators(symbol, "2y")
                            price_map[symbol] = float(indicator_map[symbol]["current_price"])
                        except Exception:
                            cycle_log["signals"].append({"symbol": symbol, "error": "카드 종목 지표 계산 실패"})
                strategy_log.update(version=int(strategy_spec.get("version") or strategy_log["version"]), applied=True)
                if float((strategy_spec.get("signal_weights") or {}).get("lightgbm", 0) or 0) > 0:
                    ml_weight_on = True
                    ml_scores = await ml_scores_by_symbol()
                    strategy_log["ml_scores_loaded"] = bool(ml_scores)
                    strategy_log["ml_generated_at"] = _ml_meta.get("generated_at")
                    strategy_log["ml_model"] = _ml_meta.get("model")
            else:
                strategy_log["error"] = "domain-rag-lab 에서 선택한 카드·판을 확인하지 못했습니다."
                await _persist_cycle(uid, {**cycle_log, "strategy": strategy_log, "execution_state": "FAILED", "note": "전략 카드 조회 실패 — 주문 보류"})
                return

        live_snapshot = None
        if mode == "live":
            try:
                live_snapshot = await kis_execution.account_snapshot(broker_row, gateway, stock_map)
            except Exception:
                logger.exception("KIS 잔고 확인 실패 user=%s", user_id)
                await _persist_cycle(uid, {**cycle_log, "execution_state": "FAILED", "note": "KIS 계좌 잔고를 확인하지 못해 주문을 보류합니다. 가상 장부로 대체하지 않습니다."})
                return
            try:
                ref = live_ownership.account_ref(broker_row, gateway)
                portfolio_rows, ownership_blocked = await live_ownership.reconcile(
                    db, ref, live_snapshot, uid, *live_ownership.strategy(broker_row))
            except (ValueError, RuntimeError):
                await _persist_cycle(uid, {**cycle_log, "execution_state": "FAILED", "note": "계좌 식별 근거가 없어 자동 주문을 보류합니다."})
                return
            cycle_log["ownership"] = {"blocked": ownership_blocked,
                                       "sellable": {p.symbol: p.quantity for p in portfolio_rows}}
        else:
            portfolio_rows = (await db.execute(select(Portfolio).where(
                Portfolio.user_id == uid, Portfolio.book == PORTFOLIO_BOOK_QUANT))).scalars().all()

        # ── 공격 모드: 보유분 점검 + 이번 사이클 매수/매도 계획 ──
        forced_action: dict[str, dict] = {}
        if aggressive:
            holdings: dict[str, tuple[int, float]] = {}
            for p in portfolio_rows:
                if p.quantity > 0:
                    holdings[p.symbol] = (int(p.quantity), float(p.avg_price or 0))
            ag_plan = aggressive_mode.plan(indicator_map, target_symbols, holdings, price_map)
            for sym in ag_plan["buy"]:
                forced_action[sym] = {"action": "매수", "ratio": None, "note": "공격 모드 매수"}
            for sym, info in ag_plan["sell"].items():
                forced_action[sym] = {"action": "매도", "ratio": info["ratio"], "note": info["reason"]}
            for sym in list(forced_action):
                if sym not in target_symbols and sym in stock_map:
                    target_symbols.append(sym)
            cycle_log["aggressive"] = {"buy": ag_plan["buy"], "sell": {k: v["reason"] for k, v in ag_plan["sell"].items()},
                                       "ranked": ag_plan["ranked"][:10], "notes": ag_plan["notes"],
                                       "interval": app_settings.QUANT_AGGRESSIVE_CANDLE_INTERVAL,
                                       "take_profit_pct": app_settings.QUANT_AGGRESSIVE_TAKE_PROFIT_PCT,
                                       "stop_loss_pct": app_settings.QUANT_AGGRESSIVE_STOP_LOSS_PCT}

        cycle_log["settings"] = {
            "mode": mode,
            "aggressive": aggressive,
            "symbol_source": symbol_source,
            "strategy": strategy_log,
            "symbols": target_symbols,
            "per_trade_budget": per_trade_budget,
            "buy_ratio": buy_ratio,
            "sell_ratio": sell_ratio,
            "execution_policy": execution.model_dump(),
        }

        risk_holdings = {}
        risk_stops = set()
        stop_unavailable = {}
        stop_quotes = {}
        if execution.size_kind == "risk_pct":
            for p in portfolio_rows:
                if p.quantity <= 0:
                    continue
                risk_holdings[p.symbol] = p
                try:
                    q = await order_preflight.current_quote(db, uid, broker_row, mode, p.symbol)
                    if q["source"] not in ("kis_user", "kis_gateway") or not p.avg_price:
                        raise ValueError("현재 원주가·귀속 평단가 확인 불가")
                    price = q["price"]
                    stop_quotes[p.symbol] = {"quote": q, "average_price": float(p.avg_price),
                                             "stop_price": float(p.avg_price) * (1 - execution.stop_loss_pct / 100)}
                except Exception:
                    stop_unavailable[p.symbol] = "현재 원주가·귀속 평단가를 확인하지 못해 손절 판단과 주문을 보류합니다."
                    continue
                if price and p.avg_price and price <= float(p.avg_price) * (1 - execution.stop_loss_pct / 100):
                    if (aggressive and forced_action.get(p.symbol, {}).get("action") != "매도"
                            and sum(v["action"] == "매도" for v in forced_action.values())
                            >= max(0, int(app_settings.QUANT_AGGRESSIVE_MAX_SELLS_PER_CYCLE))):
                        continue  # 선택 기능도 기존 사이클별 매도 수 상한을 우회하지 않는다.
                    risk_stops.add(p.symbol)
                    forced_action[p.symbol] = {"action": "매도", "ratio": 1.0,
                                              "note": f"위험 수량 설정 손절 {execution.stop_loss_pct}% 도달"}
                    if p.symbol in stock_map and p.symbol not in target_symbols:
                        target_symbols.append(p.symbol)

        # ── 위험관리 사전 점검: 일손실 한도 ───────────────────────────────
        if live_snapshot is not None:
            cash_now, equity_now = live_snapshot["cash"], live_snapshot["equity"]
            position_values = {s: h["value"] for s, h in live_snapshot["holdings"].items()}
        else:
            valuation = await quant_valuation.snapshot(db, uid)
            if not valuation["complete"]:
                cycle_log["risk"] = {"valuation": quant_valuation.basis(valuation), "day_pnl_pct": None}
                cycle_log["note"] = valuation["label"] + " — 주문 보류"
                await _persist_cycle(uid, cycle_log)
                return
            cash_now, equity_now, position_values = valuation["cash"], valuation["equity"], valuation["values"]
            price_map.update({sym: q["price"] for sym, q in valuation["quotes"].items()})
        # 이슈 #297 — 자동매매 장부는 :quant 접미사. 모의계좌(paper)와 키 안 섞이게
        risk_account_key = f"{user_id}:quant"
        if mode == "live":
            account_env = gateway.environment() if gateway.is_configured() else ("real" if live_trading_allowed() else "paper")
            account_scope = "gateway" if gateway.is_configured() else kis_execution.account_key(broker_row.app_key, broker_row.account_no, account_env)
            risk_account_key = f"{user_id}:live:{account_env}" + ("" if gateway.is_configured() else f":{account_scope}")
        start_equity = await risk_guard.day_start_equity(risk_account_key, equity_now)
        day_pnl = risk_guard.daily_pnl_pct(start_equity, equity_now)
        cycle_log["risk"] = {
            "day_start_equity": round(start_equity, 2), "equity": round(equity_now, 2), "day_pnl_pct": day_pnl,
            "orders_today": await risk_guard.orders_today(user_id), "limits": limits.to_dict(), "skipped": [],
        }
        cycle_log["risk"]["stop_checks"] = stop_quotes
        cycle_log["risk"]["stop_unavailable"] = stop_unavailable
        if mode == "paper":
            cycle_log["risk"]["valuation"] = quant_valuation.basis(valuation)
        if risk_guard.daily_loss_breached(start_equity, equity_now, limits.daily_loss_limit_pct):
            reason = f"일손실 한도 초과: 당일 {day_pnl:+.2f}% ≤ -{limits.daily_loss_limit_pct}%"
            cycle_log["risk"]["halted"] = True
            cycle_log["risk"]["reason"] = reason
            await _persist_cycle(uid, cycle_log)
            await emergency_halt(db, broker_row, user_id, reason, day_pnl)
            return

        # KIS 계좌의 미체결 매수 금액을 현금·종목 비중 한도에 예약한다.
        if mode == "live":
            # 미체결 매수 실주문은 체결되면 비중이 되므로 종목 비중 한도 계산에 미리 포함한다.
            open_exposure = await open_live_order_exposure(db, uid)
            cash_now = max(0.0, cash_now - sum(open_exposure.values()))
            for sym, value in open_exposure.items():
                position_values[sym] = position_values.get(sym, 0.0) + value
            if open_exposure:
                cycle_log["risk"]["open_live_exposure"] = {k: round(v, 2) for k, v in open_exposure.items()}
            live_risk = {"environment": account_env, "day_pnl_pct": day_pnl,
                         "equity": equity_now, "day_start_equity": start_equity, "breached": False}
            cycle_log["risk"]["live"] = live_risk

        async def _risk_gate(symbol: str, name: str, side: str, qty: int, price: float) -> tuple[int, str | None]:
            """주문 직전 위험관리 게이트. (허용 수량, 생략/조정 사유)

            게이트웨이 경로는 같은 사용자의 같은 종목에 열린 주문이 있으면
            비중 여유·매수/매도 방향·선택 재주문 활성 여부와 무관하게 먼저 보류한다.
            미체결 매수 노출 계산은 이 보류 정책과 별도로 유지한다(#183).
            """
            if mode == "live":
                opened = (await db.execute(select(LiveOrder).where(LiveOrder.user_id == uid, LiveOrder.symbol == symbol,
                                              LiveOrder.status.in_(LIVE_ORDER_OPEN_STATUSES)))).scalars().all()
                if opened:
                    return 0, "같은 종목의 접수·체결 미확인 주문이 있어 새 주문을 보류합니다."
                if execution.retry_enabled:
                    from app.services.order_retry import coordination_ready
                    if not await coordination_ready():
                        return 0, "재주문 중복 방지 저장소 연결을 확인할 수 없습니다."
            if limits.max_orders_per_day > 0 and await risk_guard.orders_today(user_id) >= limits.max_orders_per_day:
                return 0, f"일 주문 수 한도 {limits.max_orders_per_day}건 도달"
            if side == "buy":
                if strategy_spec:
                    sizing = strategy_spec.get("position_sizing") or {}
                    max_symbols = int(sizing.get("max_symbols") or 0)
                    if max_symbols > 0 and position_values.get(symbol, 0) <= 0 and sum(v > 0 for v in position_values.values()) >= max_symbols:
                        return 0, f"카드 보유 종목 수 상한 {max_symbols}개 도달"
                if mode == "live":
                    rate = trading_cost.cost_rate("buy", trading_cost.today_kst(), slippage_bps=0,
                                                  market=trading_cost.market_of(symbol))
                    qty = min(qty, int(cash_now / (price * (1 + rate))))
                    if qty <= 0:
                        return 0, "KIS 현금과 접수 대기 주문을 고려하면 매수 가능한 수량이 없습니다."
                cap = limits.max_position_pct
                if strategy_spec:
                    card_cap = float((strategy_spec.get("position_sizing") or {}).get("max_position_pct", cap))
                    cap = min(cap, card_cap) if cap > 0 else card_cap
                qty, note = risk_guard.cap_buy_quantity(qty, price, position_values.get(symbol, 0.0), equity_now, cap)
                if qty <= 0:
                    return 0, note
            else:
                note = None
            cooldown = max(1, limits.cooldown_min) if execution.retry_enabled else limits.cooldown_min
            if not await risk_guard.acquire_order_slot(user_id, symbol, side, cooldown):
                return 0, f"중복 주문 방지: {limits.cooldown_min}분 내 동일 종목·방향 주문 존재"
            return qty, note

        async def _risk_skip(symbol: str, name: str, side: str, price: float, reason: str) -> None:
            cycle_log["risk"]["skipped"].append({"symbol": symbol, "name": name, "side": side, "reason": reason})
            cycle_log["trades"].append({
                "time": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "name": name, "action": side,
                "quantity": 0, "price": price, "reason": f"[위험관리] {reason}", "status": "skipped", "type": "risk",
            })
            await notification.notify_risk_skip(symbol, name, side, reason, user_id=user_id)

        for symbol in target_symbols:
            if strategy_spec and symbol not in card_symbols(strategy_spec, list(stock_map)):
                continue  # 손절 등 추가 경로도 선택 카드의 universe를 벗어나지 않는다.
            stock = stock_map.get(symbol)
            if not stock:
                continue
            indicators = indicator_map.get(symbol) or {}
            signal = indicators.get("signal", {})
            if strategy_spec:
                try:
                    validate_rule_input(strategy_spec, indicators)
                except (ValueError, TypeError) as exc:
                    cycle_log["signals"].append({"symbol": symbol, "action": "관망", "error": str(exc)})
                    continue
                ml_score = ml_scores.get(symbol, ml_scores.get(str(symbol)[:6]))
                if ml_score is None and ml_weight_on:
                    ml_score = await symbol_ml_score(symbol)
                    if ml_score is not None:
                        strategy_log["ml_source"] = "symbol_ridge"
                signal = apply_strategy_spec_to_signal(signal, strategy_spec, ml_score, indicators)
            price = indicators.get("current_price")
            if not price:
                continue

            action = signal.get("action", "관망")
            reasons = signal.get("reasons", [])
            score = signal.get("score", 0)
            sell_ratio_here = sell_ratio
            if aggressive:
                forced = forced_action.get(symbol)
                if forced:
                    action = forced["action"]
                    reasons = [forced["note"], *reasons]
                    if forced["ratio"] is not None:
                        sell_ratio_here = float(forced["ratio"])
                else:
                    action = "관망"   # 공격 모드에서는 plan 이 정한 종목만 거래한다(사이클당 매수·매도 수 한도)
            if symbol in risk_stops:
                forced = forced_action[symbol]
                if forced["action"] == "매도":
                    action, sell_ratio_here = "매도", 1.0
                    reasons = [forced["note"], *reasons]
            cycle_log["signals"].append({
                "symbol": stock["symbol"], "name": stock["name"],
                "price": price, "action": action, "score": score,
                "basis": {"as_of": indicators.get("as_of"),
                          "interval": indicators.get("interval") or (None if aggressive else "1d"),
                          "normalized_score": signal.get("normalized_score")},
                "reasons": [str(r) for r in list(reasons)[:6]],   # 의사결정 화면 「판단 근거」 카드에 실제 사유를 보여 준다
            })

            if symbol in stop_unavailable:
                await _risk_skip(symbol, stock["name"], "sell", price, stop_unavailable[symbol])
                continue
            execution_basis = {}
            decision = {"signal_key": str((indicators.get("times") or [None])[-1] or indicators.get("as_of") or ""),
                        "signal_price": price, "signal_as_of": indicators.get("as_of"),
                        "size_from_budget": True, "risk_stop": symbol in risk_stops,
                        "position_cap_pct": (strategy_spec or {}).get("position_sizing", {}).get("max_position_pct"),
                        "input_hash": execution_control.digest({"strategy": strategy_spec,
                            "signal": signal, "closes": indicators.get("closes"), "times": indicators.get("times")})}
            if action in ("강력 매수", "매수", "강력 매도", "매도"):
                try:
                    q = await order_preflight.current_quote(db, uid, broker_row, mode, symbol)
                except Exception:
                    await _risk_skip(symbol, stock["name"], "buy" if "매수" in action else "sell", price, "주문 직전 가격·출처·기준 시각 확인 불가")
                    continue
                execution_basis = {"signal_price": price, "signal_as_of": indicators.get("as_of"),
                                   "quote": q, "price_delta_pct": round((q["price"] / price - 1) * 100, 4)}
                reasons = [*reasons, f"판단 {price:,.0f}원({indicators.get('as_of') or '기준일 미확인'}) → 주문 전 조회 {q['price']:,.0f}원 · {q['label']}"]
                price = q["price"]
                price_map[symbol] = price
                held = next((p for p in portfolio_rows if p.symbol == symbol), None)
                account_quantity = (live_snapshot['holdings'].get(symbol, {}).get('quantity', 0)
                                    if mode == 'live' else held.quantity if held else 0)
                if account_quantity > 0:
                    new_value = account_quantity * price
                    equity_now += new_value - position_values.get(symbol, 0)
                    position_values[symbol] = new_value
                if risk_guard.daily_loss_breached(start_equity, equity_now, limits.daily_loss_limit_pct):
                    await _risk_skip(symbol, stock["name"], "buy" if "매수" in action else "sell", price, "체결 직전 평가액의 일손실 한도 초과")
                    continue

            if action in ("강력 매수", "매수"):
                budget = per_trade_budget * buy_ratio
                qty = max(0, int(budget / price))
                if qty == 0:
                    await _risk_skip(symbol, stock["name"], "buy", price, "1회 예산으로 1주를 매수할 수 없습니다.")
                    continue
                if execution.size_kind == "risk_pct":
                    # 추가 매수는 평균단가·기존 손절 위험을 바꾸므로 첫 진입만 지원한다.
                    if symbol in risk_holdings:
                        await _risk_skip(symbol, stock["name"], "buy", price, "위험 기준 수량은 보유 종목 추가 매수를 하지 않습니다.")
                        continue
                    try:
                        sizing = risk_quantity(equity=equity_now, cash=cash_now, price=price,
                            stop_price=float(price) * (1 - execution.stop_loss_pct / 100), budget=budget,
                            existing_value=position_values.get(symbol, 0), position_cap_pct=limits.max_position_pct,
                            risk_pct=execution.risk_pct, slippage_bps=execution.slippage_bps,
                            when=trading_cost.today_kst(), market=trading_cost.market_of(symbol),
                            is_etf=trading_cost.is_etf_name(stock["name"]))
                    except ValueError as exc:
                        await _risk_skip(symbol, stock["name"], "buy", price, str(exc))
                        continue
                    qty = sizing["quantity"]
                    if qty == 0:
                        await _risk_skip(symbol, stock["name"], "buy", price, "위험·현금·예산·비중 상한으로 1주도 매수할 수 없습니다.")
                        continue
                    reasons = [*reasons, f"위험 기준 {qty}주 · 손절 기준 {sizing['stop_price']:,.0f}원 · 비용 포함 예상 손실 {sizing['estimated_loss']:,.0f}원"]
                qty, risk_note = await _risk_gate(stock["symbol"], stock["name"], "buy", qty, price)
                if qty <= 0:
                    await _risk_skip(stock["symbol"], stock["name"], "buy", price, risk_note or "위험관리 규칙")
                    continue
                if risk_note:
                    reasons = [*reasons, f"위험관리: {risk_note}"]
                trade = await _execute_trade(
                    db, uid, broker_row, mode, stock["symbol"], stock["name"],
                    "buy", price, qty, f"[{mode}] " + " | ".join(reasons),
                    decision=decision,
                )
                cycle_log["trades"].append({**trade, "type": "auto", "price_basis": trade.get("price_basis", execution_basis)})
                if trade.get("status") not in ("filled", "submitted", "unknown"):
                    await risk_guard.release_order_slot(user_id, stock["symbol"], "buy")
                if trade.get("status") in ("filled", "submitted", "unknown"):
                    cash_now = float(trade.get("cash_balance", max(0, cash_now - price * trade.get("quantity", qty))))
                    cycle_log["risk"]["orders_today"] = await risk_guard.increment_orders_today(user_id)
                    position_values[stock["symbol"]] = position_values.get(stock["symbol"], 0.0) + price * trade.get("quantity", qty)

            elif action in ("강력 매도", "매도"):
                if mode == "live":
                    existing = next((p for p in portfolio_rows if p.symbol == stock["symbol"]), None)
                else:
                    port_result = await db.execute(
                        select(Portfolio).where(Portfolio.user_id == uid, Portfolio.symbol == stock["symbol"], Portfolio.book == PORTFOLIO_BOOK_QUANT)
                    )
                    existing = port_result.scalar_one_or_none()
                if existing and existing.quantity > 0:
                    qty = max(1, int(existing.quantity * sell_ratio_here))
                    if sell_ratio_here >= 1.0:
                        qty = int(existing.quantity)
                    qty, risk_note = await _risk_gate(stock["symbol"], stock["name"], "sell", qty, price)
                    if qty <= 0:
                        await _risk_skip(stock["symbol"], stock["name"], "sell", price, risk_note or "위험관리 규칙")
                        continue
                    trade = await _execute_trade(
                        db, uid, broker_row, mode, stock["symbol"], stock["name"],
                        "sell", price, qty, f"[{mode}] " + " | ".join(reasons),
                        decision=decision,
                    )
                    cycle_log["trades"].append({**trade, "type": "auto", "price_basis": trade.get("price_basis", execution_basis)})
                    if trade.get("status") not in ("filled", "submitted", "unknown"):
                        await risk_guard.release_order_slot(user_id, stock["symbol"], "sell")
                    if trade.get("status") in ("filled", "submitted", "unknown"):
                        cycle_log["risk"]["orders_today"] = await risk_guard.increment_orders_today(user_id)
                        position_values[stock["symbol"]] = max(0.0, position_values.get(stock["symbol"], 0.0) - price * trade.get("quantity", qty))

        if live_snapshot is None:
            after = await quant_valuation.snapshot(db, uid)
            cycle_log["risk"]["valuation"] = quant_valuation.basis(after)
            if not after["complete"]:
                cycle_log["risk"].update(equity=None, day_pnl_pct=None)
                cycle_log["note"] = after["label"] + " — 체결 후 손익 미확인"
                await _persist_cycle(uid, cycle_log)
                return
            cash_balance, initial_capital = after["cash"], after["initial"]
            holdings_value = sum(after["values"].values())

    if live_snapshot is not None:
        # 주문 전 증권사 조회값이다. 접수 수량을 보유·현금에 성공 체결로 더하지 않는다.
        cash_balance = live_snapshot["cash"]
        holdings_value = live_snapshot["equity"] - cash_balance
        initial_capital = start_equity
    total_equity = cash_balance + holdings_value
    pnl_pct = round((total_equity / initial_capital - 1) * 100, 2) if initial_capital > 0 else None
    cycle_log["account"] = {
        "ledger": "kis_account" if live_snapshot is not None else "quant_virtual_accounts (book=QUANT)",
        "checked_at": live_snapshot["checked_at"] if live_snapshot is not None else now_str,
        "initial_capital": initial_capital,
        "cash_balance": round(cash_balance, 2),
        "holdings_value": round(holdings_value, 2),
        "total_equity": round(total_equity, 2),
        "pnl_pct": pnl_pct,
    }

    # ── 위험관리 사후 점검: 체결 후 일손실 한도 재확인 ────────────────────
    day_pnl_after = risk_guard.daily_pnl_pct(start_equity, total_equity)
    cycle_log["risk"].update({"equity": round(total_equity, 2), "day_pnl_pct": day_pnl_after})
    await _persist_cycle(uid, cycle_log)
    if risk_guard.daily_loss_breached(start_equity, total_equity, limits.daily_loss_limit_pct):
        async with session_factory() as db2:
            row2 = (await db2.execute(select(BrokerSettings).where(BrokerSettings.user_id == uid))).scalar_one_or_none()
            await emergency_halt(db2, row2, user_id,
                                 f"일손실 한도 초과(체결 후): 당일 {day_pnl_after:+.2f}% ≤ -{limits.daily_loss_limit_pct}%", day_pnl_after)


def _control_lock(uid: uuid.UUID) -> asyncio.Lock:
    # 같은 프로세스에서 같은 사용자의 시작/중지가 교차하지 않게 한다.
    # 진행 중인 호출만 lock을 보유하여 사용자가 늘어도 항목이 계속 쌓이지 않는다.
    lock = _control_locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _control_locks[uid] = lock
    return lock


def _forget_task(uid: uuid.UUID, task: asyncio.Task) -> None:
    # 이전 작업의 종료 콜백이 재시작한 새 작업을 지우지 않게 한다.
    if _auto_trade_tasks.get(uid) is task:
        del _auto_trade_tasks[uid]


async def _run_once(user_id: str) -> None:
    try:
        from app.services import execution_runs
        await execution_runs.run(_resolve_user_id(user_id), _INTERVAL_SEC,
                                 lambda: _run_quant_cycle(user_id), source="immediate")
    except Exception:
        logger.exception("자동매매 즉시 실행 실패 user=%s", user_id)


async def start_auto_trade(db: AsyncSession, user_id: str) -> bool:
    """사용자별 활성화 + 즉시 1회 실행. 이후 주기 실행은 Celery Beat."""
    uid = _resolve_user_id(user_id)
    user_id = str(uid)
    async with _control_lock(uid):
        if await is_enabled(db, uid):
            return False
        await set_enabled(db, uid, True)
        if not is_running(user_id):
            task = asyncio.create_task(_run_once(user_id))
            _auto_trade_tasks[uid] = task
            task.add_done_callback(lambda done: _forget_task(uid, done))
        asyncio.create_task(notification.notify_auto_trade_started(user_id=user_id))
        asyncio.create_task(audit(user_id, "", "auto_trade.start", {"scheduler": "celery-beat"}))
        return True


async def stop_auto_trade_for(db: AsyncSession, user_id: str) -> bool:
    uid = _resolve_user_id(user_id)
    async with _control_lock(uid):
        was = await is_enabled(db, uid)
        await set_enabled(db, uid, False)
        task = _auto_trade_tasks.get(uid)
        stop_auto_trade(user_id)
        if task is not None and task is not asyncio.current_task():
            # 취소 정리가 끝나기 전에 재시작하여 이전 작업과 겹치지 않게 한다.
            await asyncio.gather(task, return_exceptions=True)
        if was:
            asyncio.create_task(notification.notify_auto_trade_stopped(user_id=user_id))
            asyncio.create_task(audit(user_id, "", "auto_trade.stop", {}))
        return was


def stop_auto_trade(user_id: str | None = None) -> bool:
    """해당 사용자의 즉시 실행만 취소. 인자 생략은 프로세스 종료 시 전체 정리용.

    자기 사이클의 손실 한도에서 호출되면 자신을 취소하지 않는다. DB 정지 상태를
    저장한 뒤 미체결 취소·감사 기록·최종 사이클 기록까지 마치고 정상 반환해야 한다.
    """
    tasks = list(_auto_trade_tasks.values()) if user_id is None else [
        _auto_trade_tasks.get(_resolve_user_id(user_id))
    ]
    cancelled = False
    for task in tasks:
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            cancelled = True
    return cancelled


async def run_cycle_for_enabled_users() -> dict:
    """Celery Beat 진입점: quant_auto_enabled=true 인 사용자 전원의 사이클을 순차 실행.

    먼저 kis_batch.ensure_system_batch 로 KIS 모의투자 백그라운드 배치(시스템 사용자 행)를 켜거나 끈다.
    그래서 KIS_PAPER_BATCH_ENABLED=true 이면 로그인·대시보드 조작 없이도 사이클이 돈다.
    """
    from app.services import kis_batch  # 지연 import (kis_batch → kis_quickstart → auto_trade 순환 방지)

    session_factory = get_session_factory()
    async with session_factory() as db:
        try:
            batch = await kis_batch.ensure_system_batch(db)
        except Exception as exc:  # 배치 점검 실패가 사용자 계정 사이클을 막으면 안 된다
            logger.exception("KIS 모의투자 배치 점검 실패: %s", exc)
            batch = {"enabled": kis_batch.is_configured(), "running": False, "error": str(exc)}
            try:
                await db.rollback()   # 실패한 트랜잭션을 정리하지 않으면 아래 select 가 PendingRollbackError 로 전체 사이클을 막는다
            except Exception:
                pass
        uids = (await db.execute(select(BrokerSettings.user_id).where(BrokerSettings.quant_auto_enabled.is_(True)))).scalars().all()
    ran, failed = 0, 0
    for uid in uids:
        try:
            from app.services import execution_runs
            result = await execution_runs.run(uid, _INTERVAL_SEC, lambda: _run_quant_cycle(str(uid)))
            if result["status"] == "FAILED":
                failed += 1
            elif result["status"] == "COMPLETED" and not result.get("duplicate"):
                ran += 1
        except Exception:
            failed += 1
            logger.exception("자동매매 사이클 실패 user=%s", uid)
    return {"enabled_users": len(uids), "ran": ran, "failed": failed, "kis_batch": batch}
