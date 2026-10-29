"""#314 판 2 실행 상태. 주문 전송·잔고를 체결로 간주하지 않는다.

다음 시가 가상 체결과 KIS 장중 경로는 별도 book으로 호출한다. 이 모듈은
서버 내부 실행기용이며 공개 API가 아니다. 실제 주문 어댑터는 공통 위험 관문과
귀속 대조를 거친 뒤 reserve하고, 증권사의 확정 누적 체결만 fill에 전달해야 한다.
판 1 공통 판단 함수·그림자 일지는 수정하지 않는다.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import re
import math
import sqlite3

import pandas as pd
from sqlalchemy import text

from app.models import StrategyRuntime, StrategyRuntimeEvent
from app.services import auto_trade, ta_utils, market_calendar, collector_db
from app.services.execution_control import digest
from app.services.execution_policy import risk_quantity
from app.services.price_basis import adjustment_changed, adjusted_to_raw, positive

KST = timezone(timedelta(hours=9))
CONTRACT = {
    "strategy_id": "ma_cross_20_60", "version": 2, "universe": ["005930"], "timeframe": "1d",
    "entry": {"indicator": "ma_cross", "params": {"short_window": 20, "long_window": 60}, "condition": "short_above_long"},
    "exit": {"indicator": "ma_cross", "params": {"short_window": 20, "long_window": 60}, "condition": "short_below_long"},
    "signal_weights": {"technical": 1.0, "lightgbm": 0.0, "buy_threshold": 0.6, "sell_threshold": -0.6},
    "position_sizing": {"max_position_pct": 30.0, "max_symbols": 5, "size_kind": "risk_pct", "risk_pct": 1.0},
    "entry_mode": "open", "exit_mode": "open",
    "stops": {"stop_kind": "atr", "atr_period": 14, "atr_mult": 2.0, "take_kind": "rr", "take_rr": 2.0, "judge": "close", "lock": "entry"},
    "reentry": "new_signal", "warmup_bars": 60, "price_basis": "adj_base",
}


def validate_card(spec):
    execution = {k: v for k, v in spec.items() if k != "name"}
    # JSON 지문 비교는 True == 1 같은 파이썬 느슨한 동등성도 막는다.
    if digest(execution) != digest(CONTRACT):
        raise ValueError("이 실행기는 고정 ma_cross_20_60 판 2 계약만 지원합니다.")
    return digest(execution)


def initial_state():
    return {"quantity": 0, "avg_price": None, "stop_price": None, "take_price": None,
            "reentry_armed": True, "last_bar": None, "last_factor": None,
            "pending": None, "blocked": None}


def _timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("체결 시각에는 시간대가 필요합니다.")
    return dt


def _integer(value, label, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{label}이 유효하지 않습니다.")
    return value


def judgment(spec, bars):
    """확정 일봉 원 OHLC와 그날 계수만 받아 수정 ATR/판단일 계수로 환산한다."""
    validate_card(spec)
    if len(bars) < 60:
        raise ValueError("판단에는 확정 일봉 60개 이상이 필요합니다.")
    dates, adjusted = [], []
    for b in bars:
        d = date.fromisoformat(b["date"])
        if dates and d <= dates[-1]:
            raise ValueError("일봉 날짜가 중복되거나 역순입니다.")
        dates.append(d)
        o, h, l, c, f = [positive(b[k], k) for k in ("open", "high", "low", "close", "factor")]
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("일봉 OHLC 범위가 잘못되었습니다.")
        adj = {k: positive(b["adjusted_" + k], "수정 " + k) for k in ("open", "high", "low", "close")}
        if any(not math.isclose(raw * f, adj[k], rel_tol=1e-6, abs_tol=1.0)
               for k, raw in zip(("open", "high", "low", "close"), (o, h, l, c))):
            raise ValueError("원주가·수정주가·판단일 계수의 단위가 일치하지 않습니다.")
        adjusted.append(adj)
    now = datetime.now(KST)
    if datetime.combine(dates[-1], time(15, 30), KST) > now:
        raise ValueError("아직 마감하지 않은 판단 봉입니다.")
    df = pd.DataFrame(adjusted)
    rule = auto_trade.evaluate_spec_rules(spec, {"closes": df.close.tolist()})
    atr = float(ta_utils.atr(df.high, df.low, df.close, 14).iloc[-1])
    distance = adjusted_to_raw(atr, bars[-1]["factor"]) * 2.0
    return {"date": dates[-1].isoformat(), "entry": rule["entry"], "exit": rule["exit"],
            "raw_close": float(bars[-1]["close"]), "factor": float(bars[-1]["factor"]),
            "atr_adjusted": atr, "distance_raw": distance}


def observe(state, spec, bars):
    state = deepcopy(state)
    j = judgment(spec, bars)
    if state["last_bar"] and j["date"] <= state["last_bar"]:
        raise ValueError("처리한 판단 봉 이전으로 상태를 되돌릴 수 없습니다.")
    changed = state["last_factor"] is not None and adjustment_changed(state["last_factor"], j["factor"])
    # 첫 실행에도 마지막 두 봉 사이의 조정 사건을 확인한다.
    changed |= adjustment_changed(bars[-2]["factor"], j["factor"])
    if state["pending"] and not changed and not state["blocked"]:
        # 늦은 체결 확인 뒤 같은 종가의 손절을 다시 판단할 수 있어야 한다.
        # 미확인 주문 때문에 판단을 미룬 봉은 처리 완료로 소비하지 않는다.
        return state, {"action": "HOLD", "reason": "기존 주문의 접수·최종 체결 확인 대기",
                       "judgment": j, "deferred": True}
    state.update(last_bar=j["date"], last_factor=j["factor"])
    action, reason = "HOLD", "진입 조건 없음"
    if changed and (state["quantity"] or state["pending"]):
        state["blocked"] = "CORPORATE_ACTION_RECONCILIATION"
    if state["blocked"]:
        reason = state["blocked"]
    elif state["pending"]:
        reason = "기존 주문의 접수·최종 체결 확인 대기"
    elif bars[-1].get("halted"):
        reason = "거래정지 판단 봉 신규 주문 보류"
    elif state["quantity"]:
        reason = "보유 중 추가 매수 없음"
        if j["raw_close"] <= state["stop_price"]:
            action, reason = "SELL", "STOP_CLOSE"
        elif j["raw_close"] >= state["take_price"]:
            action, reason = "SELL", "TAKE_CLOSE"
        elif j["exit"]:
            action, reason = "SELL", "EXIT_SIGNAL"
    else:
        if not j["entry"]:
            state["reentry_armed"] = True
        if changed:
            reason = "조정 사건 당일 신규 진입 보류"
        elif j["entry"] and not j["exit"] and state["reentry_armed"]:
            action, reason = "BUY", "ENTRY_SIGNAL"
        elif j["entry"]:
            reason = "청산 뒤 진입 조건 해제 대기"
    if action != "HOLD":
        state["pending"] = {"side": action, "signal_date": j["date"], "factor": j["factor"],
                            "distance_raw": j["distance_raw"], "reason": reason, "phase": "planned",
                            "base_quantity": state["quantity"], "filled_quantity": 0, "avg_filled_price": None}
    return state, {"action": action, "reason": reason, "judgment": j}


def size_entry(state, *, equity, cash, price, budget, existing_value, position_cap_pct,
               slippage_bps, when):
    """최종 주문 가격에서 위험·현금·예산·계정/카드 비중을 함께 제한한다."""
    pending = state["pending"]
    if not pending or pending["side"] != "BUY" or state["quantity"] or state["blocked"]:
        raise ValueError("크기를 계산할 신규 진입이 없습니다.")
    if isinstance(position_cap_pct, bool) or not isinstance(position_cap_pct, (int, float)) or not math.isfinite(position_cap_pct) or not 0 <= position_cap_pct <= 100:
        raise ValueError("계정 비중 상한이 잘못되었습니다.")
    cap = min(30.0, position_cap_pct) if position_cap_pct else 30.0
    return risk_quantity(equity=equity, cash=cash, price=price,
        stop_price=price - pending["distance_raw"], budget=budget, existing_value=existing_value,
        position_cap_pct=cap, risk_pct=1.0, slippage_bps=slippage_bps, when=when, market="KOSPI")


def reserve(state, *, order_key, quantity, mode, target_date):
    """외부 전송보다 먼저 영속 저장할 예약. UNKNOWN/PARTIAL을 새 주문으로 대체하지 않는다."""
    state = deepcopy(state)
    p = state["pending"]
    if state["blocked"] or not p or p["phase"] != "planned":
        raise ValueError("새로 예약할 주문이 없거나 대조가 필요합니다.")
    _integer(quantity, "주문 수량")
    if not isinstance(order_key, str) or not order_key or len(order_key) > 100:
        raise ValueError("주문 식별자가 필요합니다.")
    if mode not in ("virtual_next_open", "kis_intraday_probe"):
        raise ValueError("가상 다음 시가와 KIS 장중 점검을 구분해야 합니다.")
    target = date.fromisoformat(target_date)
    if target <= date.fromisoformat(p["signal_date"]):
        raise ValueError("판단 다음 거래일 이후만 실행할 수 있습니다.")
    calendar = market_calendar.trading_days(date.fromisoformat(p["signal_date"]) + timedelta(days=1), target)
    days = [d["date"] for d in calendar.get("days", []) if d["is_trading_day"]]
    if calendar.get("partial") or not days or min(days) != target_date:
        raise ValueError("판단 바로 다음 거래일을 확인하지 못했습니다.")
    if p["side"] == "SELL" and quantity != state["quantity"]:
        raise ValueError("판 2 청산은 전략에 귀속된 확정 보유 전량이어야 합니다.")
    p.update(phase="reserved", order_key=order_key, quantity=quantity, mode=mode, target_date=target_date)
    return state, {"status": "reserved", "order_key": order_key, "quantity": quantity}


def fill(state, *, order_key, cumulative_quantity, average_price, status, filled_at=None):
    """확정 체결의 누적량·가중 평균가만 반영한다. 접수·응답 불명은 수량 0이다.

    부분 체결 중 평균가가 바뀌면 확정된 부분의 손절선도 그 평균가로 갱신한다.
    최종 체결/취소 이후에는 손절 거리와 체결 원가를 새 ATR로 바꾸지 않는다.
    """
    state = deepcopy(state)
    p = state["pending"]
    if not p or p.get("order_key") != order_key or p["phase"] == "planned":
        raise ValueError("해당 전략의 예약 주문과 일치하지 않습니다.")
    if status not in ("ACCEPTED", "UNKNOWN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"):
        raise ValueError("확인할 수 없는 주문 상태입니다.")
    qty = _integer(cumulative_quantity, "누적 체결 수량", zero=True)
    if not p["filled_quantity"] <= qty <= p["quantity"]:
        raise ValueError("누적 체결 수량이 줄었거나 주문 수량을 초과했습니다.")
    if status == "FILLED" and qty != p["quantity"] or status == "PARTIALLY_FILLED" and not 0 < qty < p["quantity"]:
        raise ValueError("주문 상태와 누적 체결 수량이 다릅니다.")
    if status == "REJECTED" and qty or status in ("ACCEPTED", "UNKNOWN") and qty != p["filled_quantity"]:
        raise ValueError("접수·불명·거절 응답으로 체결을 추정할 수 없습니다.")
    if qty:
        avg = positive(average_price, "확정 체결 평균가")
        at = _timestamp(filled_at)
        if at.astimezone(KST).date() != date.fromisoformat(p["target_date"]):
            raise ValueError("예약 실행일과 확정 체결일이 다릅니다.")
        if p["mode"] == "virtual_next_open" and at.astimezone(KST).time().replace(tzinfo=None) != time(9):
            raise ValueError("가상 다음 시가 체결을 장중 현재가로 바꿀 수 없습니다.")
        if qty == p["filled_quantity"] and avg != p["avg_filled_price"]:
            raise ValueError("같은 누적 체결량의 평균가가 달라 대조가 필요합니다.")
        if p["side"] == "BUY":
            stop = avg - p["distance_raw"]
            if stop <= 0:
                raise ValueError("체결가 기준 손절선이 유효하지 않습니다.")
            state.update(quantity=qty, avg_price=avg, stop_price=stop, take_price=avg + 2 * p["distance_raw"])
        else:
            state["quantity"] = p["base_quantity"] - qty
        p.update(filled_quantity=qty, avg_filled_price=avg, filled_at=filled_at)
    elif average_price is not None or filled_at is not None:
        raise ValueError("체결 0주에는 체결가·시각을 기록하지 않습니다.")
    p["phase"] = status
    if status in ("FILLED", "CANCELLED", "REJECTED"):
        if p["side"] == "SELL" and state["quantity"] == 0:
            state.update(avg_price=None, stop_price=None, take_price=None, reentry_armed=False)
        state["pending"] = None
    return state, {"status": status, "order_key": order_key, "cumulative_quantity": qty,
                   "confirmed_quantity": state["quantity"]}


def reduce_event(state, spec, event):
    kind = event.get("kind")
    args = {k: v for k, v in event.items() if k != "kind"}
    if kind == "bar":
        return observe(state, spec, **args)
    if kind == "reserve":
        return reserve(state, **args)
    if kind == "fill":
        return fill(state, **args)
    if kind == "cancel_plan":
        if not state["pending"] or state["pending"]["phase"] != "planned" or not args.get("reason"):
            raise ValueError("전송 예약 전 계획만 보류할 수 있습니다.")
        state = deepcopy(state)
        state["pending"] = None
        return state, {"status": "blocked", "reason": args["reason"]}
    raise ValueError("지원하지 않는 실행 사건입니다.")


async def apply_event(db, *, user_id, account_ref, book, symbol, spec, event_key, event):
    """한 DB 트랜잭션의 상태+사건 기록. 호출자가 commit한 뒤 외부 전송한다.

    중복 호출은 저장한 결과를 돌려주며 상태를 되돌리지 않는다. 같은 사건 키의
    입력 변경은 오류다. book과 계좌/사용자/전략/판/종목마다 상태를 분리한다.
    """
    spec_hash = validate_card(spec)
    if not re.fullmatch(r"[a-f0-9]{64}", account_ref) or symbol != "005930.KS" or book not in ("V2_VIRTUAL", "V2_KIS_PROBE"):
        raise ValueError("판 2 계좌 식별자·장부·종목을 확인하세요.")
    if not isinstance(event_key, str) or not 1 <= len(event_key) <= 160:
        raise ValueError("실행 사건 식별자가 필요합니다.")
    if event.get("kind") == "reserve" and event.get("mode") != {"V2_VIRTUAL": "virtual_next_open", "V2_KIS_PROBE": "kis_intraday_probe"}[book]:
        raise ValueError("장부와 체결 경로가 다릅니다.")
    key = digest([str(user_id), account_ref, book, spec["strategy_id"], spec["version"], symbol])
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(bytes.fromhex(key[:16]), "big", signed=True)})
    row = await db.get(StrategyRuntime, key, populate_existing=True)
    if row and row.spec_hash != spec_hash:
        raise ValueError("진행 중인 전략 판의 계약이 변경됐습니다.")
    previous = await db.get(StrategyRuntimeEvent, (key, event_key))
    input_hash = digest(event)
    if previous:
        if previous.input_hash != input_hash:
            raise ValueError("같은 사건 키의 입력이 변경됐습니다.")
        return {**previous.result, "duplicate": True}
    state, outcome = reduce_event(row.state if row else initial_state(), spec, event)
    if outcome.get("deferred"):
        return {"runtime_id": key, "event_key": event_key, "outcome": outcome,
                "state": state, "duplicate": False, "deferred": True}
    now = datetime.now(timezone.utc)
    if row is None:
        row = StrategyRuntime(runtime_id=key, user_id=user_id, account_ref=account_ref, book=book,
            strategy_id=spec["strategy_id"], strategy_version=spec["version"], symbol=symbol,
            spec_hash=spec_hash, state=state, updated_at=now)
        db.add(row)
        await db.flush()
    else:
        row.state, row.updated_at = state, now
    result = {"runtime_id": key, "event_key": event_key, "outcome": outcome, "state": state}
    db.add(StrategyRuntimeEvent(runtime_id=key, event_key=event_key, input_hash=input_hash, result=result))
    await db.flush()
    return {**result, "duplicate": False}


def load_bars(symbol, through, *, path=None):
    """수집 DB의 동일 날짜 원/수정 OHLC를 읽는다. 최신 계수로 대체하지 않는다."""
    if symbol != "005930.KS":
        raise ValueError("고정 카드 종목이 아닙니다.")
    path = path or collector_db.db_path()
    if path is None:
        raise ValueError("수집 DB가 없습니다.")
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT p.bas_dt,p.mkp,p.hipr,p.lopr,p.clpr,a.cum_factor,"
            "a.adj_mkp,a.adj_hipr,a.adj_lopr,a.adj_clpr,p.halted FROM price_daily p "
            "LEFT JOIN price_adjusted a USING (bas_dt,srtn_cd) WHERE p.srtn_cd=? AND p.bas_dt>=? AND p.bas_dt<=? ORDER BY p.bas_dt",
            (symbol[:6], (through - timedelta(days=730)).strftime("%Y%m%d"), through.strftime("%Y%m%d"))).fetchall()
    if not rows or rows[-1][0] != through.strftime("%Y%m%d"):
        raise ValueError("해당 판단일의 확정 일봉이 없습니다.")
    keys = ("date", "open", "high", "low", "close", "factor", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "halted")
    bars = [dict(zip(keys, row)) for row in rows]
    for b in bars:
        b["date"] = datetime.strptime(b["date"], "%Y%m%d").date().isoformat()
    return bars
