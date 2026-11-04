from decimal import Decimal

import pytest

from app.services import rebalance as rb


@pytest.mark.parametrize("values", [
    [33.335, 33.335, 33.33], [16.665] * 6, [.005] * 5,
    [20.004, 30.004, 49.992], [49.995, 49.995], [60, 25, 10],
])
def test_rounding_preserves_total_and_nonnegative_cash(values):
    targets = [{"symbol": f"{i+1:06}.KS", "weight_pct": w} for i, w in enumerate(values)]
    normalized = rb.normalize_targets(targets)
    total = sum(Decimal(str(row["weight_pct"])) for row in normalized)
    expected = sum(Decimal(str(w)) for w in values).quantize(Decimal(".01"), rounding="ROUND_HALF_UP")
    assert total == expected
    assert total <= 100
    assert rb.normalize_targets(normalized) == normalized
    assert {r["symbol"]: r["weight_pct"] for r in rb.normalize_targets(targets[::-1])} == {
        r["symbol"]: r["weight_pct"] for r in normalized}


def test_duplicate_symbols_merge_before_rounding():
    rows = rb.normalize_targets([{"symbol":"005930.KS", "weight_pct":33.335},
                                 {"symbol":"005930.KS", "weight_pct":33.335},
                                 {"symbol":"000660.KS", "weight_pct":33.33}])
    assert {r["symbol"]:r["weight_pct"] for r in rows} == {"005930.KS":66.67, "000660.KS":33.33}


def test_excess_total_is_rejected_without_rescaling_user_intent():
    with pytest.raises(rb.RebalanceError):
        rb.normalize_targets([{"symbol":"005930.KS", "weight_pct":60}, {"symbol":"000660.KS", "weight_pct":41}])
