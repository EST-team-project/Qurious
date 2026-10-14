"""#162 선택 기능 계약. 생략한 기존 설정은 고정 예산·재주문 꺼짐이다."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services import trading_cost


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    size_kind: Literal["fixed_budget", "risk_pct"] = "fixed_budget"
    risk_pct: float = Field(1, gt=0, le=5)
    stop_loss_pct: float = Field(1, gt=0, le=50)
    slippage_bps: float = Field(10, ge=0, le=100)
    retry_enabled: bool = False
    retry_max_attempts: int = Field(1, ge=1, le=3)
    retry_window_min: int = Field(15, ge=1, le=120)
    retry_price_deviation_pct: float = Field(1, gt=0, le=5)


def policy_for(row):
    return ExecutionPolicy.model_validate(getattr(row, "quant_execution_policy", None) or {})


def risk_quantity(*, equity, cash, price, stop_price, budget, existing_value, position_cap_pct,
                  risk_pct, slippage_bps, when, market="KOSPI", is_etf=False):
    """비용 포함 예상 1주 손실과 현금·예산·종목 상한으로 수량을 내린다. 0주도 정상 결과."""
    def number(value):
        try:
            value = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("수치가 필요합니다.") from exc
        if not value.is_finite():
            raise ValueError("유한한 수치가 필요합니다.")
        return value
    equity, cash, price, stop, budget, held, cap, risk, slip = map(number, (
        equity, cash, price, stop_price, budget, existing_value, position_cap_pct, risk_pct, slippage_bps))
    if not (equity > 0 and cash >= 0 and budget >= 0 and price > stop > 0 and held >= 0
            and 0 < risk <= 5 and 0 <= cap <= 100 and 0 <= slip <= 100):
        raise ValueError("위험 수량 계산의 가격·자산·한도를 확인하세요.")
    buy = number(trading_cost.cost_rate("buy", when, float(slip), market, is_etf))
    sell = number(trading_cost.cost_rate("sell", when, float(slip), market, is_etf))
    per_share_cash = price * (1 + buy)
    per_share_loss = per_share_cash - stop * (1 - sell)
    risk_budget = equity * risk / 100
    limits = [risk_budget / per_share_loss, cash / per_share_cash, budget / per_share_cash]
    if cap > 0:
        limits.append(max(Decimal(0), equity * cap / 100 - held) / price)
    qty = max(0, int(min(limits).to_integral_value(rounding=ROUND_FLOOR)))
    return {"quantity": qty, "risk_budget": float(risk_budget), "stop_price": float(stop),
            "estimated_loss": float(per_share_loss * qty), "estimated_cash": float(per_share_cash * qty),
            "loss_per_share": float(per_share_loss)}
