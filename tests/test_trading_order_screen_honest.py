"""TC-TOS · 직접매매 › 주문/매매 · 포트폴리오 화면의 정직한 표시 (3차 ①-17 · 2026-10-30).

무엇이 틀렸었나 —
1. 「증권사 API 연동 (Mockup)」 카드의 「설정 저장」 단추가 주문 칸의 증권사 선택값(「가상 매매」 → mock)과
   마이페이지 입력칸(broker-app-key 등)을 **몰래 읽어** /api/broker/settings 로 보냈다. 서버는 mock · 관리형(KIS)으로
   저장하면 저장된 키 · 계좌를 비운다(`_apply_credentials`) — 증권사 설정이 말없이 지워질 수 있었다.
2. 이 화면의 주문(POST /api/orders)은 증권사를 부르지 않고 앱 안에 「체결」 로만 기록하는데, 화면은 「주문 완료 (kis)」 라고 했다.
3. 포트폴리오 현재가에 출처 · 시각이 없다는 말이 없었고, 불러오기 실패는 조용히 빈 화면이었다.

여기서는 화면 파일(app.html · js/trading.js)의 연결을 글자로 맞댄다 — 네트워크 · DB 없이 돈다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
TRADING = (ROOT / "public" / "js" / "trading.js").read_text(encoding="utf-8")


def _view(name: str) -> str:
    m = re.search(rf'data-view="{name}">(.*?)data-view=', APP, flags=re.S)
    assert m, f"app.html 에서 {name} 화면을 찾지 못했다"
    return m.group(1)


def _code(js: str) -> str:
    """주석을 뺀 코드 — 없앤 이유를 적은 주석 때문에 시험이 헛걸리지 않게."""
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


def test_order_screen_has_no_broker_key_inputs_or_save_button():
    view = _view("trading-order")
    for gone in ("kiwoom-key", "kiwoom-secret", "toss-key", "toss-secret", "trading-broker-save", "(Mockup)"):
        assert gone not in view, f"{gone} — 주문 화면에서 증권사 설정을 건드리던 칸"
    assert 'id="trading-broker-status"' in view, "연동 상태(읽기 전용)는 남긴다"
    assert 'href="#mypage"' in view, "증권사 키 · 계좌는 마이페이지에서만 바꾼다고 길을 안내한다"


def test_trading_js_never_posts_broker_settings():
    code = _code(TRADING)
    assert "/api/broker/settings" in code and "trading-broker-save" not in code
    # 읽기(GET)만 — body 를 싣는 POST 가 남아 있으면 안 된다
    for m in re.finditer(r'api\("/api/broker/settings"([^)]*)\)', code):
        assert "POST" not in m.group(1)
    assert "broker-app-key" not in code and "broker-app-secret" not in code and "broker-account" not in code, \
        "마이페이지 입력칸을 이 파일이 읽으면 안 된다(숨은 의존)"


def test_order_screen_says_orders_stay_inside_the_app():
    view = _view("trading-order")
    assert "증권사로 나가지 않고" in view and "가상 매매" in view and "현금은 그대로" in view
    code = _code(TRADING)
    assert "주문 완료" not in code, "증권사로 나가지 않는 기록을 「주문 완료」 라 부르지 않는다"
    assert "기록 완료" in code


def test_portfolio_says_price_basis_and_shows_load_errors():
    code = _code(TRADING)
    assert "data-pf-basis" in code and "출처 · 시각이 없어" in code and "평단가로 대신하지 않습니다" in code
    body = re.search(r"async function loadPortfolio\(\) \{.*?\n\}\n", code, flags=re.S).group(0)
    assert "catch {}" not in body and "보유 종목을 불러오지 못했습니다" in body
