"""TC-PW — 비밀번호 보기 버튼(public/js/pwtoggle.js · login.html · register.html · mypage.js) · 2026-10-29 · 할 일 ①-09

약속: 입력 칸의 이름 · 자동완성 · 필수 속성은 건드리지 않고 버튼만 더한다 · 뒤로가기 캐시로 되살아나거나 닫힐 때 다시 가린다 ·
로그인 · 가입 · 마이페이지(비밀번호 바꾸기 · 탈퇴)의 비밀번호 칸이 모두 쓴다. 눈으로 보는 모양은 브라우저 확인(1280 · 390)으로 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

PUB = Path(__file__).resolve().parents[1] / "public"
PW = (PUB / "js" / "pwtoggle.js").read_text(encoding="utf-8")
LOGIN = (PUB / "login.html").read_text(encoding="utf-8")
REGISTER = (PUB / "register.html").read_text(encoding="utf-8")
MYPAGE = (PUB / "js" / "mypage.js").read_text(encoding="utf-8")


def test_module_adds_button_without_touching_the_input_contract():
    """TC-PW-01 · 버튼에 aria-label · aria-pressed · 입력 칸의 name · autocomplete · required 는 안 건드림 · 다시 가림(pagehide · pageshow) · 두 번 붙지 않음."""
    assert 'aria-label", "비밀번호 보기"' in PW and "aria-pressed" in PW and 'btn.type = "button"' in PW   # 폼 제출 단추가 아니다
    assert 'input.dataset.pwToggle === "1"' in PW                                                        # 두 번 붙지 않는다
    assert '"pagehide"' in PW and '"pageshow"' in PW and "set(false)" in PW
    for attr in ("autocomplete", "required", ".name", "minLength", "maxLength"):
        assert f"input{attr}" not in PW.replace(" ", ""), f"입력 칸의 {attr} 을 건드린다"


def test_screens_use_it():
    """TC-PW-02 · 로그인 · 가입은 폼의 비밀번호 칸 전부에, 마이페이지는 칸 넷(현재 · 새 · 새 확인 · 탈퇴)에 붙인다."""
    assert 'from "/js/pwtoggle.js"' in LOGIN and "attachPasswordToggles(document.getElementById(\"f\"))" in LOGIN
    assert 'from "/js/pwtoggle.js"' in REGISTER and 'attachPasswordToggles(document.querySelector("form"))' in REGISTER
    assert 'from "/js/pwtoggle.js"' in MYPAGE
    ids = re.search(r'\[("mp-pw-current"[^\]]*)\]\.forEach\(id => attachPasswordToggle', MYPAGE)
    assert ids and re.findall(r'"([a-z0-9-]+)"', ids.group(1)) == ["mp-pw-current", "mp-pw-new", "mp-pw-new2", "mp-del-pw"]
    # 칸 id 는 그대로 — 마이페이지 시험(TC-MP-01)이 문서 안 한 번씩을 본다
    for html in (LOGIN, REGISTER):
        assert html.count('type="password"') >= 1
