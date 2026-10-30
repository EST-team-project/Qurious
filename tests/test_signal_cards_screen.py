"""TC-SCD — 퀀트 대시보드 「규칙 신호」 카드 (public/js/quant.js `signalCardHtml` · 할 일 ②-21 · ②-22 · 2026-10-30)

화면만 고친다 — 서버 응답 · 판정(`_generate_signal` · 일지 판 지문)은 그대로다. 서버가 이미 주는 `signal.reasons` · `as_of` · `data_note` 를 보인다.
1. 카드가 「근거 n개」 · 근거 목록 · 출처 한 줄 · 「종가」 를 보이고, 기준일이 전 거래일보다 앞이면 경고한다(전 거래일을 모르면 경고하지 않는다). (TC-SCD-01)
2. 근거 없음 · 응답 실패(null)도 깨지지 않고, 글은 HTML 로 이스케이프된다. (TC-SCD-02)
3. 제목 · 도움말 낱말이 「규칙 신호」 로 맞고 「AI 매매 시그널」 이 남지 않으며, 제목의 종목 수는 실제 그리는 수다. (TC-SCD-03)
node 가 없으면 1 · 2 는 건너뛴다(구조 시험 3 은 항상 돈다).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUANT = (ROOT / "public" / "js" / "quant.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _extract(name_start: str, end_marker: str) -> str:
    i = QUANT.index(name_start)
    return QUANT[i:QUANT.index(end_marker, i)]


def _run_cards(cases: list[dict]) -> list[str]:
    """quant.js 의 카드 함수만 잘라 node 로 돌린다(`/js/common.js` 같은 브라우저 경로 import 는 쓰지 않는다)."""
    colors = _extract("const SIGNAL_COLORS", "/** 카드 하나의 HTML")
    display = _extract("function _displayAction", "async function loadMarketCards")
    card = _extract("export function signalCardHtml", "async function loadSignalCards").replace("export function", "function")
    js = textwrap.dedent("""
        const escHtml = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
        const fmt = n => n == null ? "-" : Number(n).toLocaleString("en-US");
    """) + colors + display + card + textwrap.dedent("""
        const cases = JSON.parse(process.argv[1]);
        console.log(JSON.stringify(cases.map(c => signalCardHtml(c.s, c.r, c.prev))));
    """)
    out = subprocess.run([NODE, "-e", js, json.dumps(cases, ensure_ascii=False)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


STOCK = {"name": "삼성전자", "symbol": "005930.KS"}


def _resp(as_of="2026-10-29", reasons=("RSI 중립 (55.0)", "단기 이평 > 중기 이평 (매수 우위)"), note="금융위원회 주식시세정보 · 2026-10-29 종가"):
    return {"signal": {"action": "매수", "reasons": list(reasons), "score": 1}, "current_price": 217000, "current_rsi": 55.04,
            "as_of": as_of, "data_note": note}


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_shows_reasons_note_close_and_flags_stale_data():
    """TC-SCD-01 · 근거 n개 · 근거 목록 · 출처 한 줄 · 종가 · 기준일이 전 거래일보다 앞이면 경고 · 전 거래일을 모르면 경고 안 함."""
    fresh, stale, unknown = _run_cards([
        {"s": STOCK, "r": _resp("2026-10-29"), "prev": "2026-10-29"},
        {"s": STOCK, "r": _resp("2026-10-28"), "prev": "2026-10-29"},
        {"s": STOCK, "r": _resp("2026-10-28"), "prev": ""},
    ])
    assert "근거 2개" in fresh and "RSI 중립 (55.0)" in fresh and "단기 이평 &gt; 중기 이평" in fresh and "금융위원회 주식시세정보" in fresh
    assert ">종가<" in fresh and "217,000" in fresh and "10-29 기준" in fresh and "최신 아님" not in fresh
    assert "매수" in fresh and "RSI: 55.0" in fresh
    assert "10-28 기준 · ⚠ 최신 아님" in stale and "var(--red)" in stale
    assert "최신 아님" not in unknown and "10-28 기준" in unknown, "전 거래일을 모르면 경고를 못 낸다(거짓 경고 금지)"


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_card_survives_missing_data_and_escapes_text():
    """TC-SCD-02 · 응답 실패(null) · 근거 없음도 깨지지 않고, 글은 이스케이프된다(`<script>` 가 그대로 안 나간다)."""
    failed, empty, evil = _run_cards([
        {"s": STOCK, "r": None, "prev": "2026-10-29"},
        {"s": STOCK, "r": {"signal": {"action": "관망", "reasons": []}, "current_price": 1000, "as_of": "2026-10-29"}, "prev": "2026-10-29"},
        {"s": {"name": "<b>x</b>", "symbol": "A&B"}, "r": _resp(reasons=("<script>alert(1)</script>",), note="<img src=x>"), "prev": "2026-10-29"},
    ])
    assert "근거 없음" in failed and "RSI: -" in failed and "기준" not in failed
    assert "근거 없음" in empty and "관망" in empty
    assert "<script>" not in evil and "&lt;script&gt;" in evil and "<img src=x>" not in evil and "&lt;b&gt;x" in evil and "A&amp;B" in evil


def test_labels_follow_the_decision_and_title_counts_what_it_draws():
    """TC-SCD-03 · 제목 · 도움말이 「규칙 신호」(결정 10-27 · 「AI 판단」 안 씀) · 「대표 5종목」 이 아니라 실제 그리는 수 · 서버 판정 코드는 그대로."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert 'id="signal-cards-title"' in html and "규칙 신호" in html and "AI 매매 시그널" not in html and "대표 5종목" not in html.split('id="signal-cards-title"')[1][:200]
    core = (ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8")
    m = re.search(r'signal:\s*\{ title: "([^"]+)"', core)
    assert m and m.group(1) == "규칙 신호"
    assert "stocks.length" in QUANT and "signal-cards-title" in QUANT, "제목의 종목 수는 실제 그리는 수"
    assert "previous_trading_day" in QUANT, "전 거래일은 서버(/api/data/status)가 알려 준 값"
    stock = (ROOT / "app" / "services" / "stock.py").read_text(encoding="utf-8")
    assert 'return {"action": action, "color": color, "score": score, "reasons": signals}' in stock, "서버 판정 응답은 그대로(일지 판 지문)"
