"""고정 판 2 다음 시가 가상 체결 재현. 운영 장부/그림자 판 1/KIS는 쓰지 않는다."""
from datetime import date, datetime, time
import math

from app.services import strategy_v2 as v2, trading_cost, execution_control, risk_guard


def replay(spec, bars, *, start, initial_cash, budget, slippage_bps=10.0, risk_row=None):
    """직전 종가 판단 → 다음 거래일 시가 체결 → 당일 종가 판단 순서.

    주문 전송·유동성·부분 체결은 재현하지 않는다. 슬리피지는 명시적 가정이고
    비용은 기존 공통 모델이다. 가격 조정 보유 대조가 필요하면 부분 결과로 멈춘다.
    """
    v2.judgment(spec, bars)  # 진행 봉·단위 오류를 결과 생성 전에 거부
    cash = v2.positive(initial_cash, "초기 자금")
    v2.positive(budget, "1회 예산")
    if isinstance(slippage_bps, bool) or not math.isfinite(slippage_bps) or not 0 <= slippage_bps <= 100:
        raise ValueError("슬리피지 가정은 0~100bp여야 합니다.")
    state, rows, fills = v2.initial_state(), [], []
    equity = cash
    limits = risk_guard.RiskLimits.from_row(risk_row)
    for i, bar in enumerate(bars):
        day = date.fromisoformat(bar["date"])
        if day < start:
            continue
        if i < 59:
            raise ValueError("재현 시작일의 준비 봉이 60개 미만입니다.")
        filled, skipped = None, None
        pending = state["pending"]
        changed = state["last_factor"] is not None and v2.adjustment_changed(state["last_factor"], bar["factor"])
        if changed and state["quantity"]:
            state["blocked"] = "CORPORATE_ACTION_RECONCILIATION"
            return _report(spec, bars, rows, fills, cash, state, "partial", "CORPORATE_ACTION_RECONCILIATION", slippage_bps)
        if pending:
            if changed or bar.get("halted"):
                state, skipped = v2.reduce_event(state, spec, {"kind": "cancel_plan", "reason": "CORPORATE_ACTION_OR_HALT"})
            else:
                side = pending["side"]
                price = v2.positive(bar["open"], "체결일 원주가 시가") * (1 + (1 if side == "BUY" else -1) * slippage_bps / 10000)
                open_equity = cash + state["quantity"] * price
                try:
                    quantity = state["quantity"] if side == "SELL" else v2.size_entry(state,
                        equity=open_equity, cash=cash, price=price, budget=budget,
                        existing_value=state["quantity"] * price, position_cap_pct=limits.max_position_pct,
                        slippage_bps=0, when=day)["quantity"]
                    execution_control.check_limits(row=risk_row, quantity=quantity, price=price,
                        cash=cash, equity=open_equity, start_equity=equity, orders_today=0,
                        position_value=state["quantity"] * price, owned_quantity=state["quantity"], side=side)
                    state, _ = v2.reserve(state, order_key="virtual:" + pending["signal_date"] + ":" + side,
                        quantity=quantity, mode="virtual_next_open", target_date=day.isoformat())
                except ValueError as exc:
                    state, skipped = v2.reduce_event(state, spec, {"kind": "cancel_plan", "reason": str(exc)})
                else:
                    at = datetime.combine(day, time(9), v2.KST).isoformat()
                    costs = trading_cost.order_costs(side.lower(), price, quantity, day, market="KOSPI")
                    if side == "BUY" and costs.net_amount > cash:
                        raise ValueError("가상 체결의 비용 포함 현금 검산에 실패했습니다.")
                    state, _ = v2.fill(state, order_key=state["pending"]["order_key"],
                        cumulative_quantity=quantity, average_price=price, status="FILLED", filled_at=at)
                    cash += costs.net_amount * (-1 if side == "BUY" else 1)
                    filled = {"signal_date": pending["signal_date"], "filled_at": at, "side": side,
                        "quantity": quantity, "raw_open": bar["open"], "price": price,
                        "cost": costs.as_dict(), "reason": pending["reason"], "distance_raw": pending["distance_raw"]}
                    fills.append(filled)
        state, decision = v2.observe(state, spec, bars[:i + 1])
        equity = cash + state["quantity"] * bar["close"]
        rows.append({"date": bar["date"], "cash": cash, "equity": equity, "quantity": state["quantity"],
            "avg_price": state["avg_price"], "stop_price": state["stop_price"], "take_price": state["take_price"],
            "reentry_armed": state["reentry_armed"], "decision": decision, "fill": filled, "skipped": skipped})
    if not rows:
        raise ValueError("재현 구간에 확정 판단 봉이 없습니다.")
    return _report(spec, bars, rows, fills, cash, state, "ok", None, slippage_bps)


def _report(spec, bars, rows, fills, cash, state, status, reason, slip):
    return {"mode": "virtual_next_open", "status": status, "reason": reason,
        "spec_hash": v2.validate_card(spec), "input_hash": v2.digest(bars),
        "data_as_of": bars[-1]["date"], "slippage_bps": slip, "cash": cash,
        "state": state, "rows": rows, "fills": fills,
        "note": "다음 거래일 시가·비용 가정의 가상 재현. KIS 체결 증거나 판 1 그림자 일지가 아님."}
