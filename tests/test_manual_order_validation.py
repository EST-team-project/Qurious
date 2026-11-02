import pytest
from pydantic import ValidationError
from app.routes.stocks import OrderBody

@pytest.mark.parametrize("field,value", [("broker", "kis"), ("broker", "kb"), ("broker", "unknown"), ("quantity", 0), ("quantity", -1), ("quantity", 1.5), ("quantity", True), ("price", 0), ("price", -1), ("price", True), ("price", float("nan")), ("price", float("inf")), ("order_type", "short")])
def test_invalid_manual_order_rejected_before_ledger(field, value):
    body = dict(symbol="005930", name="삼성전자", quantity=1, price=70000, order_type="buy")
    body[field] = value
    with pytest.raises(ValidationError):
        OrderBody(**body)

def test_manual_order_defaults_to_virtual():
    assert OrderBody(symbol="005930", name="삼성전자", quantity=1, price=70000, order_type="buy").broker == "virtual"
