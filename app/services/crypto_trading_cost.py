"""업비트 KRW 코인 모의매매 거래비용.

수수료는 거래소 기본 요율, 슬리피지는 추정 가정으로 분리한다.
슬리피지는 체결가격에 먼저 반영하며 net_amount에서 중복 차감하지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.services.trading_cost import DEFAULT_SLIPPAGE_BPS as BASE_SLIPPAGE_BPS

UPBIT_KRW_FEE_RATE = 0.0005
DEFAULT_SLIPPAGE_BPS = BASE_SLIPPAGE_BPS
COST_BASIS_ESTIMATED = "estimated"
COST_BASIS_NONE = "none"


@dataclass(frozen=True)
class CryptoOrderCost:
    side: str
    reference_price: float
    execution_price: float
    quantity: float
    gross_amount: float
    commission: float
    fee_rate: float
    slippage_bps: float
    slippage_amount: float
    net_amount: float
    cost_basis: str = COST_BASIS_ESTIMATED

    @property
    def total_cost(self) -> float:
        return self.commission + self.slippage_amount

    @property
    def cost_pct(self) -> float:
        return self.total_cost / self.gross_amount * 100 if self.gross_amount else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "reference_price": self.reference_price,
            "execution_price": self.execution_price,
            "quantity": self.quantity,
            "gross_amount": self.gross_amount,
            "commission": self.commission,
            "fee_rate": self.fee_rate,
            "slippage_bps": self.slippage_bps,
            "slippage_amount": self.slippage_amount,
            "total_cost": self.total_cost,
            "cost_pct": self.cost_pct,
            "net_amount": self.net_amount,
            "cost_basis": self.cost_basis,
        }


def order_costs(
    side: str,
    reference_price: float,
    quantity: float,
    *,
    fee_rate: float = UPBIT_KRW_FEE_RATE,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    cost_basis: str = COST_BASIS_ESTIMATED,
) -> CryptoOrderCost:
    """기준 시세 → 불리한 방향 슬리피지 → 체결금액 기준 수수료."""
    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side는 BUY 또는 SELL이어야 합니다.")

    values = (reference_price, quantity, fee_rate, slippage_bps)
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("거래비용 계산 입력값은 유한한 숫자여야 합니다.")
    reference_price = float(reference_price)
    quantity = float(quantity)
    fee_rate = float(fee_rate)
    slippage_bps = float(slippage_bps)

    if reference_price <= 0 or quantity <= 0:
        raise ValueError("기준가격과 수량은 0보다 커야 합니다.")
    if fee_rate < 0 or slippage_bps < 0 or (side == "SELL" and slippage_bps >= 10_000):
        raise ValueError("수수료율 또는 슬리피지 값이 유효하지 않습니다.")

    factor = 1 + slippage_bps / 10_000 if side == "BUY" else 1 - slippage_bps / 10_000
    execution_price = reference_price * factor
    gross_amount = execution_price * quantity
    commission = gross_amount * fee_rate
    slippage_amount = abs(execution_price - reference_price) * quantity
    net_amount = gross_amount + commission if side == "BUY" else gross_amount - commission

    return CryptoOrderCost(
        side=side,
        reference_price=reference_price,
        execution_price=execution_price,
        quantity=quantity,
        gross_amount=gross_amount,
        commission=commission,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        slippage_amount=slippage_amount,
        net_amount=net_amount,
        cost_basis=cost_basis,
    )


def order_fields(cost: CryptoOrderCost) -> dict[str, Any]:
    """CryptoOrder 모델에 기록할 비용 필드."""
    return {
        "reference_price": cost.reference_price,
        "price": cost.execution_price,
        "amount": cost.gross_amount,
        "commission": cost.commission,
        "fee_rate": cost.fee_rate,
        "slippage_bps": cost.slippage_bps,
        "slippage_amount": cost.slippage_amount,
        "net_amount": cost.net_amount,
        "cost_basis": cost.cost_basis,
    }
