"""TC-TVK — TradingView 대사 화면의 안내 문구(public/app.html) · 2026-10-29 · 화면 벤치마킹 조사 A묶음 S1 · S2 · S10

1. 안내 문구는 TradingView 공식 이름(Strategy Report · Metrics · Trades · Download)을 앞에 두고 옛 이름(Overview · List of Trades)은 병기하며
   확인일을 붙인다 — 문서판마다 이름이 달라서 고정 사실처럼 쓰지 않는다. (TC-TVK-01)
2. 「이 화면이 말하는 것 / 말하지 않는 것」 한 줄이 대사 카드 위에 있다 — 수익률 유사성만으로 통과로 보지 않는다. (TC-TVK-02)
3. Pine 코드 칸 위에 「표시용 indicator 라 대사에는 쓸 수 없음」 이 있고, 그 코드는 실제로 indicator() 다(코드가 strategy() 로 바뀌면 이 시험이 문구를 다시 보게 한다). (TC-TVK-03)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
IND = (ROOT / "public" / "js" / "indicator.js").read_text(encoding="utf-8")


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_official_names_first_with_check_date():
    """TC-TVK-01"""
    h = _flat(HTML)
    assert "Strategy Report › Metrics 탭 값 입력 — 옛 이름 Overview · 확인일 2026-10-29" in h
    assert "Strategy Report › Trades 탭 › Download — 옛 이름 List of Trades › Export · 확인일 2026-10-29" in h
    assert "Strategy Tester › Overview" not in h and "Strategy Tester › List of" not in h


def test_says_and_does_not_say_line():
    """TC-TVK-02"""
    h = _flat(HTML)
    assert "data-tv-says" in h
    i = h.index("data-tv-says")
    line = h[i:i + 400]
    assert "이 화면이 말하는 것" in line and "말하지 않는 것" in line and "「검증 통과」" in line
    assert h.index("data-tv-says") < h.index('id="tvc-ticker"')                      # 입력칸보다 위


def test_pine_panel_says_it_is_not_for_reconciliation():
    """TC-TVK-03"""
    h = _flat(HTML)
    i = h.index("data-pine-kind")
    assert "지표(indicator)용" in h[i:i + 300] and "대사에는 쓸 수 없습니다" in h[i:i + 400]
    assert i < h.index('id="ci-pine-code"')                                          # 코드 칸 위
    assert "//@version=5" in IND and 'indicator("${name}"' in IND and "strategy(" not in IND
