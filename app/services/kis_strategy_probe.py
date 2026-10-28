"""#314 판 1 카드의 수동 KIS 모의 경로 점검. 스케줄러·합격 전략 등록과 독립적이다."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select, text, func

from app.models import BrokerSettings, LiveOrder, StrategyDecision, OrderIntent, RiskDay, LIVE_ORDER_OPEN_STATUSES
from app.services import auto_trade, kis_execution, market_calendar, risk_guard, trading_cost, execution_control
from app.services.brokers.factory import live_trading_allowed
from app.services.brokers import stock_coin_trade_gateway as gateway
from app.services.stock import get_quant_indicators
from app.services.strategy_execution import validate_rule_input

KST = timezone(timedelta(hours=9))
SYMBOL = "005930.KS"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def prepare(spec: dict, indicators: dict, now: datetime, calendar: dict) -> dict:
    """고정 v1 규칙을 확정 일봉에만 적용한다. 부족·미래·오래된 봉은 거부한다."""
    for key, expected in {"strategy_id": "ma_cross_20_60", "version": 1, "universe": ["005930"], "timeframe": "1d"}.items():
        if spec.get(key) != expected or (key == "version" and type(spec.get(key)) is not int):
            raise ValueError("이 점검 경로는 ma_cross_20_60 판 1, 005930 일봉만 받습니다.")
    for side, condition in (("entry", "short_above_long"), ("exit", "short_below_long")):
        if spec.get(side) != {"indicator": "ma_cross", "params": {"short_window": 20, "long_window": 60}, "condition": condition}:
            raise ValueError("고정 카드 판 1 규칙과 다릅니다.")
    if spec.get("signal_weights") != {"technical": 1.0, "lightgbm": 0.0, "buy_threshold": 0.6, "sell_threshold": -0.6}:
        raise ValueError("고정 카드 판 1 가중치와 다릅니다.")
    if spec.get("position_sizing") != {"max_position_pct": 30.0, "max_symbols": 5}:
        raise ValueError("고정 카드 판 1 수량 한도와 다릅니다.")
    if any(key in spec for key in ("stops", "judge", "lock", "reentry", "entry_mode", "exit_mode", "warmup_bars", "price_basis")):
        raise ValueError("판 2의 추가 규칙은 이 점검 경로에서 실행하지 않습니다.")
    local = now.astimezone(KST)
    today = local.date().isoformat()
    days = calendar.get("days") or []
    if calendar.get("partial") or not any(d["date"] == today and d["is_trading_day"] for d in days):
        raise ValueError("오늘의 거래일 여부를 확인하지 못했습니다.")
    previous = [d["date"] for d in days if d["date"] < today and d["is_trading_day"]]
    if not previous:
        raise ValueError("직전 거래일을 확인하지 못했습니다.")
    closes, times = indicators.get("closes") or [], indicators.get("times") or []
    if len(closes) != len(times) or not times:
        raise ValueError("종가와 판단 봉 시각을 확인하지 못했습니다.")
    if any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("판단 봉 시각이 중복되거나 잘못되었습니다.")
    # 국내 일봉은 UTC 자정 epoch로 날짜를 표시한다. 오늘 진행 봉은 제외한다.
    dated = [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), c) for t, c in zip(times, closes)]
    if any(d > today for d, _ in dated):
        raise ValueError("미래 판단 봉을 받았습니다.")
    closed = [(d, c) for d, c in dated if d < today]
    if not closed or closed[-1][0] != max(previous):
        raise ValueError("직전 거래일의 확정 종가가 아직 없습니다.")
    if len({d for d, _ in closed}) != len(closed):
        raise ValueError("같은 날짜의 일봉이 중복되었습니다.")
    data = {"closes": [c for _, c in closed]}
    validate_rule_input(spec, data)
    result = auto_trade.evaluate_spec_rules(spec, data)
    action = "SELL" if result["exit"] else "BUY" if result["entry"] else "HOLD"
    bar_end = datetime.combine(datetime.fromisoformat(closed[-1][0]).date(), time(15, 30), KST)
    return {"strategy_id": spec["strategy_id"], "version": spec["version"], "symbol": SYMBOL,
            "bar_end_at": bar_end.isoformat(), "action": action,
            "input_hash": digest({"spec": spec, "bars": closed}), "rule": result["detail"],
            "market_open": time(9, 0) <= local.time().replace(tzinfo=None) < time(15, 20)}


def result_view(row: StrategyDecision, duplicate=False) -> dict:
    return {"decision_key": row.decision_key, "action": row.action, "status": row.status,
            "client_order_id": row.client_order_id, "duplicate": duplicate, **row.detail}


async def run(db, user_id: uuid.UUID, spec: dict, *, execute: bool = False) -> dict:
    """명시적으로 지정한 사용자 설정만 사용. dry-run은 조회만 하며 선점을 소비하지 않는다."""
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    calendar = market_calendar.trading_days(today - timedelta(days=14), today)
    decision = prepare(spec, await get_quant_indicators(SYMBOL, "2y"), now, calendar)
    row = (await db.execute(select(BrokerSettings).where(BrokerSettings.user_id == user_id))).scalar_one_or_none()
    if row is None or row.broker != "kis" or live_trading_allowed() or gateway.is_configured():
        raise ValueError("사용자별 KIS 직접 모의 연결과 실전 허용 꺼짐 상태가 필요합니다.")
    if row.quant_auto_enabled or row.risk_kill_switch:
        raise ValueError("자동매매가 켜져 있거나 비상 정지 상태여서 점검 주문을 보류합니다.")
    risk_fields = ("quant_per_trade_budget", "quant_buy_ratio", "risk_daily_loss_limit_pct",
                   "risk_max_position_pct", "risk_max_orders_per_day")
    risk_settings = tuple(getattr(row, field) for field in risk_fields)
    client, creds = kis_execution.client_for(row)
    if not client.paper or not creds.paper:
        raise ValueError("KIS 모의 계좌만 점검할 수 있습니다.")
    account_ref = kis_execution.account_key(creds.app_key, creds.account_no, "paper")
    key = digest([str(user_id), account_ref, decision["strategy_id"], decision["version"], SYMBOL,
                  decision["bar_end_at"], decision["action"]])
    # 같은 계좌를 등록한 다른 사용자·다른 판단도 하루 한도 계산과 선점을 직렬화한다.
    if execute:
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                         {"key": int.from_bytes(bytes.fromhex(account_ref[:16]), "big", signed=True)})
    existing = await db.get(StrategyDecision, key)
    if existing:
        if existing.input_hash != decision["input_hash"]:
            raise ValueError("같은 판단 키의 입력이 변경되었습니다. 재주문하지 않습니다.")
        return result_view(existing, True)
    detail = {"bar_end_at": decision["bar_end_at"], "rule": decision["rule"],
              "environment": "paper", "quantity": 0, "price": None, "reason": "관망 판단"}
    state = "HOLD"
    quantity, price = 0, 0.0
    if decision["action"] != "HOLD":
        state = "BLOCKED"
        detail["reason"] = "정규장 점검 시간 밖입니다(09:00~15:20 KST)."
        if decision["market_open"]:
            snapshot = await kis_execution.account_snapshot(row, gateway, {SYMBOL: {"symbol": SYMBOL}})
            quote = await client.get_price(SYMBOL)
            price = float(quote.current)
            if not math.isfinite(price) or price <= 0 or not price.is_integer():
                raise ValueError("KIS 현재가를 확인하지 못했습니다.")
            quote_at = datetime.now(timezone.utc)
            detail.update(price=price, quote_at=quote_at.isoformat(), equity=snapshot["equity"])
            start = datetime.combine(today, time.min, KST)
            prior = (await db.execute(select(StrategyDecision).where(
                StrategyDecision.account_ref == account_ref, StrategyDecision.created_at >= start
            ).order_by(StrategyDecision.created_at))).scalars().all()
            opened = (await db.execute(select(LiveOrder).where(
                LiveOrder.user_id == user_id, LiveOrder.symbol == SYMBOL,
                LiveOrder.status.in_(LIVE_ORDER_OPEN_STATUSES)))).scalars().all()
            limits = risk_guard.RiskLimits.from_row(row)
            first_equity = next((r.detail["equity"] for r in prior if "equity" in r.detail), snapshot["equity"])
            shared_day = await db.get(RiskDay, (account_ref, today))
            if shared_day is not None:
                first_equity = shared_day.equity
            elif execute:
                db.add(RiskDay(account_ref=account_ref, day=today, equity=first_equity))
            used = sum(r.status in ("PENDING", "submitted", "unknown", "error") for r in prior)
            used += int(await db.scalar(select(func.count()).select_from(OrderIntent).where(
                OrderIntent.account_ref == account_ref, OrderIntent.created_at >= start,
                OrderIntent.status.in_(("PENDING", "unknown", "submitted", "filled")))) or 0)
            cap_orders = min(3, limits.max_orders_per_day) if limits.max_orders_per_day > 0 else 3
            uncertain = await db.scalar(select(OrderIntent.intent_id).where(
                OrderIntent.account_ref == account_ref, OrderIntent.status.in_(("PENDING", "unknown"))).limit(1))
            if opened or uncertain:
                detail["reason"] = "같은 종목의 접수·체결 미확인 주문이 있습니다."
            elif used >= cap_orders:
                detail["reason"] = "하루 모의 점검 주문 한도에 도달했습니다."
            elif risk_guard.daily_loss_breached(first_equity, snapshot["equity"], limits.daily_loss_limit_pct):
                detail["reason"] = "일손실 한도 초과"
            elif decision["action"] == "BUY":
                power = await client.get_buying_power(creds.account_no, SYMBOL, price)
                budget = float(row.quant_per_trade_budget) * float(row.quant_buy_ratio)
                if not math.isfinite(budget) or budget <= 0:
                    raise ValueError("1회 예산이 잘못되었습니다.")
                rate = trading_cost.cost_rate("buy", today, slippage_bps=0, market=trading_cost.market_of(SYMBOL))
                cash = min(snapshot["cash"], power["amount"])
                held = snapshot["holdings"].get(SYMBOL, {}).get("value", 0)
                cap_pct = min(30.0, limits.max_position_pct) if limits.max_position_pct > 0 else 30.0
                quantity = max(0, min(1, power["quantity"], int(min(cash, budget) / (price * (1 + rate))),
                                      int(max(0, snapshot["equity"] * cap_pct / 100 - held) / price)))
                detail["reason"] = "1주 모의 연결 점검" if quantity else "예산·미수 없는 매수 가능 수량·현금·비중 상한으로 0주"
            else:
                # 수동 보유를 팔지 않는다. 이 경로의 계좌별 확정 체결 순수량만 허용한다.
                orders = (await db.execute(select(LiveOrder).join(
                    StrategyDecision, StrategyDecision.client_order_id == LiveOrder.client_order_id
                ).where(StrategyDecision.account_ref == account_ref, StrategyDecision.user_id == user_id,
                        LiveOrder.symbol == SYMBOL))).scalars().all()
                owned = sum(o.filled_quantity * (1 if o.side.upper() == "BUY" else -1) for o in orders)
                quantity = max(0, min(1, owned, int(snapshot["holdings"].get(SYMBOL, {}).get("quantity", 0))))
                detail["reason"] = "점검 경로의 확정 보유 1주 매도" if quantity else "점검 경로에서 확정 체결된 보유가 없어 매도 보류"
            detail["quantity"] = quantity
            if quantity:
                await execution_control.coordination_ready()
                execution_control.check_limits(row=row, quantity=quantity, price=price,
                    cash=snapshot["cash"], equity=snapshot["equity"], start_equity=first_equity,
                    orders_today=used, position_value=snapshot["holdings"].get(SYMBOL, {}).get("value", 0),
                    owned_quantity=quantity if decision["action"] == "SELL" else None, side=decision["action"])
                state = "PENDING"
    if not execute:
        await db.rollback()
        return {"decision_key": key, "action": decision["action"], "status": "DRY_RUN", "would_status": state, **detail}
    record = StrategyDecision(decision_key=key, user_id=user_id, account_ref=account_ref,
        input_hash=decision["input_hash"], strategy_id=decision["strategy_id"], strategy_version=1,
        symbol=SYMBOL, bar_end_at=datetime.fromisoformat(decision["bar_end_at"]), action=decision["action"],
        status=state, detail=detail)
    db.add(record)
    await db.commit()  # 성공하기 전에는 외부 주문을 보내지 않는다.
    if state != "PENDING":
        return result_view(record)
    # 위험 설정·계좌 변경과 느린 조회를 전송 직전에 다시 검사한다.
    await db.refresh(row)
    await execution_control.coordination_ready()
    _, current_creds = kis_execution.client_for(row)
    current_ref = kis_execution.account_key(current_creds.app_key, current_creds.account_no, "paper")
    send_time = datetime.now(timezone.utc)
    if (row.quant_auto_enabled or row.risk_kill_switch or live_trading_allowed() or gateway.is_configured()
            or not current_creds.paper or current_ref != account_ref
            or risk_settings != tuple(getattr(row, field) for field in risk_fields)
            or not time(9, 0) <= send_time.astimezone(KST).time().replace(tzinfo=None) < time(15, 20)
            or (send_time - quote_at).total_seconds() > 10):
        record.status = "BLOCKED"
        record.detail = {**detail, "reason": "전송 직전 설정 변경 또는 시세 유효 시간 초과"}
        await db.commit()
        return result_view(record)
    # 설정은 저장하지 않는다. 기존 직접 주문 추적·알림 경로만 재사용한다.
    send_row = SimpleNamespace(**{c.name: getattr(row, c.name) for c in BrokerSettings.__table__.columns})
    send_row.quant_mode = "live"
    order_id = "card:" + key[:59]
    outcome = await auto_trade._place_live_order(send_row, SYMBOL, "삼성전자", decision["action"].lower(),
        quantity, price, str(user_id), db=db, client_order_id=order_id, decision_record=record)
    record.status = outcome["status"]
    if outcome.get("client_order_id"):
        record.client_order_id = outcome["client_order_id"]
    record.detail = {**detail, "order_no": outcome.get("order_no", ""),
                     "reason": "주문 응답 기록 — 체결은 별도 조회"}
    await db.commit()
    return result_view(record)
