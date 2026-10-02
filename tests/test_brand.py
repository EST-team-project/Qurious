"""화면의 서비스 이름 시험 (TC-BR) — 이름 · 부제 · 바닥글은 한 곳(public/js/brand.js)에서 온다 (2026-10-02).

기초 코드(강사님 lumina-invest)의 「Lumina Invest」 · 회사 표기(이름 · 메일 · 누리집)를 화면에서 Qurious 로 바꿨다.
원저작자 표시는 화면이 아니라 NOTICE.md · README 에 있다 — 이 시험은 그 둘도 함께 본다(출처를 지운 것이 아님을 지킨다).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
SCREENS = ("app.html", "login.html", "register.html")
OLD_MARKS = ("Lumina Invest", "에듀엠지티", "edumgt.co.kr")


def test_screens_show_qurious_from_one_place():
    """TC-BR-01 · 앱 · 로그인 · 가입 화면에 옛 이름 · 회사 표기가 없고, 이름 자리는 brand.js 가 채운다."""
    brand = (PUB / "js" / "brand.js").read_text(encoding="utf-8")
    assert 'name: "Qurious"' in brand and 'tagline: "AI Financial Quant Platform"' in brand
    for screen in SCREENS:
        html = (PUB / screen).read_text(encoding="utf-8")
        for mark in OLD_MARKS:
            assert mark not in html, f"{screen} 에 「{mark}」 가 남았다"
        assert '/js/brand.js' in html, f"{screen} 이 brand.js 를 싣지 않는다"
        assert 'data-brand="name"' in html and 'data-brand="tagline"' in html, f"{screen} 의 이름 자리"


def test_original_author_is_still_credited():
    """TC-BR-02 · 화면에서 이름을 바꿔도 원저작자(edumgt/lumina-invest) 표시는 NOTICE.md 에 남아 있다."""
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "edumgt/lumina-invest" in notice and "원저작자" in notice
