"""#314: 연결용 고정 카드 판 1을 기존 앱 판단 함수에 넣는 준비 시험. 주문하지 않는다."""
import json
from pathlib import Path

import pytest

from app.services.auto_trade import apply_strategy_spec_to_signal, evaluate_spec_rules

CARD = Path(__file__).resolve().parents[1] / "docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v1.json"


@pytest.mark.parametrize("closes,expected", [
    ([100.0] * 40 + [200.0] * 20, "매수"),
    ([200.0] * 40 + [100.0] * 20, "매도"),
    ([100.0] * 60, "관망"),
])
def test_agreed_card_drives_action_without_lean_or_orders(closes, expected):
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert (card["strategy_id"], card["version"], card["universe"]) == ("ma_cross_20_60", 1, ["005930"])
    assert "acceptance" not in card and "backtest_result" not in card
    result = apply_strategy_spec_to_signal({"action": "관망", "score": 0}, card,
                                          indicators={"closes": closes})
    assert result["action"] == expected


def test_insufficient_history_is_not_a_card_rule_result():
    card = json.loads(CARD.read_text(encoding="utf-8"))
    assert evaluate_spec_rules(card, {"closes": [100.0] * 59}) is None
