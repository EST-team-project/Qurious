"""자산군 비중의 정본과 국내주식 목표 편집안. 주문·플랜은 변경하지 않는다."""
from decimal import Decimal, ROUND_DOWN
import re

PROFILES = {
    "conservative": {"국내주식": 15, "해외주식": 10, "국내채권": 50, "대체자산": 10, "현금": 15},
    "moderate": {"국내주식": 30, "해외주식": 25, "국내채권": 30, "대체자산": 10, "현금": 5},
    "aggressive": {"국내주식": 45, "해외주식": 35, "국내채권": 10, "대체자산": 8, "현금": 2},
}
POLICY = "domestic_equity_only_v1"


def asset_allocation(risk_profile: str, horizon_years: int) -> dict[str, float]:
    if risk_profile not in PROFILES or type(horizon_years) is not int or not 1 <= horizon_years <= 10:
        raise ValueError("성향과 투자기간(1~10년)을 확인하세요.")
    weights = PROFILES[risk_profile].copy()
    # 현금·채권에서 같은 양을 옮기는 기존 규칙을 유지하되 재원이 있는 만큼만 옮긴다.
    boost = min(6, max(0, horizon_years - 3), weights["현금"], weights["국내채권"])
    for key in ("국내주식", "해외주식"):
        weights[key] += boost
    for key in ("국내채권", "현금"):
        weights[key] -= boost
    return {key: float(value) for key, value in weights.items()}


def rebalance_draft(result: dict) -> dict:
    """국내주식 자산군만 종목으로 나눈다. 미지원 종목은 조용히 제외하지 않는다."""
    alloc = result["allocations"]
    weights = result["optimization"]["weights"]
    names = {p["code"]: p["name"] for p in result["stock_picks"]}
    if not weights or any(not re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ|KN)", s) for s in weights):
        raise ValueError("국내주식 종목으로 구성된 배분만 가져올 수 있습니다.")
    values = {s: Decimal(str(w)) for s, w in weights.items()}
    if any(not w.is_finite() or w < 0 for w in values.values()) or sum(values.values()) <= 0:
        raise ValueError("배분 종목 비중을 확인하세요.")
    budget = Decimal(str(alloc["국내주식"]))
    if not budget.is_finite() or not 0 < budget <= 100:
        raise ValueError("국내주식 비중을 확인하세요.")
    # 종목 비중을 소수 둘째 자리로 내림하고 남은 0.01%p는 큰 나머지부터 배정한다.
    exact = {s: budget * w / sum(values.values()) for s, w in values.items()}
    units = {s: int((w * 100).to_integral_value(rounding=ROUND_DOWN)) for s, w in exact.items()}
    rest = int(budget * 100) - sum(units.values())
    for s in sorted(units, key=lambda s: (-(exact[s] * 100 - units[s]), s))[:rest]:
        units[s] += 1
    return {
        "policy": POLICY,
        "targets": [{"symbol": s, "name": names.get(s, s), "weight_pct": n / 100}
                    for s, n in units.items() if n > 0],
        "domestic_weight_pct": float(budget),
        "cash_weight_pct": float(100 - budget),
        "unapplied_allocations": {k: alloc[k] for k in ("해외주식", "국내채권", "대체자산")},
        "original_cash_weight_pct": alloc["현금"],
        "message": "국내주식 부분만 가져옵니다. 해외주식·채권·대체자산은 매수하지 않고 해당 비중도 현금으로 남깁니다. 목표와 현금 비중을 확인한 뒤 저장하세요.",
    }
