import pytest
from app.services import crypto_trading_cost as ct


def test_buy_cost_applies_slippage_before_fee():
    c = ct.order_costs("BUY", 100_000_000, 0.1)
    assert c.execution_price == pytest.approx(100_100_000)
    assert c.gross_amount == pytest.approx(10_010_000)
    assert c.commission == pytest.approx(5_005)
    assert c.net_amount == pytest.approx(10_015_005)
    assert c.slippage_amount == pytest.approx(10_000)


def test_sell_cost_deducts_fee_from_adjusted_fill():
    c = ct.order_costs("SELL", 100_000_000, 0.1)
    assert c.execution_price == pytest.approx(99_900_000)
    assert c.gross_amount == pytest.approx(9_990_000)
    assert c.commission == pytest.approx(4_995)
    assert c.net_amount == pytest.approx(9_985_005)


def test_slippage_is_not_double_charged():
    c = ct.order_costs("BUY", 100_000_000, 0.1)
    assert c.net_amount == pytest.approx(c.gross_amount + c.commission)


def test_order_fields_match_execution_record():
    c = ct.order_costs("BUY", 100_000_000, 0.1)
    f = ct.order_fields(c)
    assert f["price"] == c.execution_price
    assert f["reference_price"] == c.reference_price
    assert f["net_amount"] == c.net_amount
    assert f["cost_basis"] == "estimated"


@pytest.mark.parametrize("side,price,quantity", [
    ("OTHER", 100, 1),
    ("BUY", 0, 1),
    ("SELL", 100, 0),
    ("SELL", 100, 1),
])
def test_invalid_cost_inputs(side, price, quantity):
    kwargs = {"slippage_bps": 10_000} if side == "SELL" else {}
    with pytest.raises(ValueError):
        ct.order_costs(side, price, quantity, **kwargs)
