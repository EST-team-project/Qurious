"""TC-TM — 가입 약관 · 개인정보 수집·이용 동의 · 투자 유의사항 (public/js/terms.js · register.html · terms.html · app/routes/auth.py) · 2026-10-29 · 할 일 ①-09

근거: docs/phase-3/01-analysis/research/배경조사/2026-10-29-가입-약관-동의/결과.md. 법률 자문이 아니라 「이 앱이 실제로 하는 일과 문구가 어긋나지 않게」 지키는 시험이다.
약속:
1. 필수 항목 목록이 화면(terms.js)과 서버(auth.REQUIRED_AGREEMENTS)에서 같다. (TC-TM-01)
2. 개인정보 동의 글에 개인정보 보호법 제15조 ② 의 네 가지(목적 · 항목 · 보유와 이용 기간 · 거부권과 불이익)가 모두 있다. (TC-TM-02)
3. 앱에 없는 일을 약속하지 않는다 — 「암호화해 보관」 · 「다시 동의」 가 없다 · 로그인 잠금 숫자는 코드(login_guard)와 같다 · 탈퇴 뒤 고객번호가 남는다는 사실을 적는다. (TC-TM-03)
4. 가입 화면: 체크박스 세 개가 필수 · 모달 · 전문 페이지가 같은 글을 쓴다 · 서버에 판과 항목을 보낸다. (TC-TM-04)
5. 서버: 동의 항목을 검사하고(빠지면 422) 감사 기록에 판과 항목만 남긴다 · 비워 두면 이전처럼 받는다. (TC-TM-05)
6. 마이페이지 탈퇴 안내문이 같은 사실을 말한다. (TC-TM-06)
7. 그리는 함수가 글을 이스케이프한다. (TC-TM-07)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routes import auth
from app.services import login_guard

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
TERMS_JS = (PUB / "js" / "terms.js").read_text(encoding="utf-8")
REGISTER = (PUB / "register.html").read_text(encoding="utf-8")
TERMS_HTML = (PUB / "terms.html").read_text(encoding="utf-8")
APP = (PUB / "app.html").read_text(encoding="utf-8")


# 사용자에게 보이는 글(TERMS 데이터)만 — 머리말 주석은 「쓰지 않는 말」 을 설명하느라 그 말을 담고 있다
SHOWN = TERMS_JS.split("export const TERMS = [", 1)[1].split("export const TERMS_FOOTER", 1)[0]


def _ids() -> list[str]:
    block = SHOWN
    return re.findall(r'^\s{4}id: "([a-z]+)",', block, re.M)


def test_required_ids_match_screen_and_server():
    """TC-TM-01 · terms.js 의 항목 id 셋이 서버의 REQUIRED_AGREEMENTS 와 같다 — 어긋나면 화면은 통과인데 서버가 422 로 막는다."""
    assert _ids() == list(auth.REQUIRED_AGREEMENTS) == ["service", "privacy", "invest"]
    assert re.search(r'export const TERMS_VERSION = "[0-9]{4}-[0-9]{2}-[0-9]{2}-v[0-9.]+"', TERMS_JS)


def test_privacy_has_the_four_notices_of_pipa_15_2():
    """TC-TM-02 · 개인정보 보호법 제15조 ② 네 가지 — 목적 · 항목 · 보유·이용 기간 · 거부권과 불이익 — 가 이 차례로 있다 · 거부 불이익(가입 불가)을 적는다."""
    privacy = TERMS_JS.split('id: "privacy"', 1)[1].split('id: "invest"', 1)[0]
    heads = re.findall(r'h: "(\d\. [^"]+)"', privacy)
    assert heads == ["1. 수집 · 이용 목적", "2. 수집하는 항목", "3. 보유 · 이용 기간", "4. 동의를 거부할 권리와 불이익"], heads
    assert "동의하지 않으시면 가입할 수 없습니다" in privacy
    assert "제15조 제2항" in privacy                                                   # 근거 조문을 밝힌다
    # 선택 동의는 두지 않는다 — 가입 때 선택 항목을 받지 않는다(제22조 ⑤ 때문에 받지도 않는 목적을 적게 된다)
    assert "[선택]" not in SHOWN and "마케팅" not in SHOWN


def test_no_promises_the_app_does_not_keep():
    """TC-TM-03 · 앱에 없는 일을 쓰지 않는다 · 숫자는 코드와 같다 · 탈퇴 뒤 고객번호가 남는다는 사실을 적는다."""
    for banned in ("암호화해", "암호화되어", "안전하게 보관", "다시 동의를 받", "추천합니다", "수익을 보장합니다"):
        assert banned not in SHOWN, f"「{banned}」 는 앱의 실제 동작과 맞지 않는다(결과.md D.2 · E.1)"
    assert f"{login_guard.MAX_FAILS}번 연속 실패하면 {login_guard.WINDOW_SEC // 60}분 동안 로그인이 잠깁니다" in SHOWN
    assert "고객번호는 기록에 남습니다" in SHOWN and "연결을 끊은 채 남" in SHOWN
    assert "서비스 데이터베이스에 저장됩니다" in SHOWN                                  # 증권사 키 · 알림 토큰은 평문 칸 — 사실대로
    assert "OpenAI" in SHOWN and "이용 중 따로 알리는 것" in SHOWN                          # 국외 이전은 이용 중 화면에서 따로 알린다고 적는다


def test_register_screen_wires_checkboxes_modal_and_payload():
    """TC-TM-04 · 가입 화면이 terms.js 로 체크박스(필수)를 만들고 모달 · 전체 동의 · 서버로 판과 항목을 보낸다 · 전문 페이지가 같은 모듈을 쓴다."""
    assert 'from "/js/terms.js"' in REGISTER and 'id="consent-rows"' in REGISTER and 'id="agree-all"' in REGISTER
    assert 'type="checkbox" required' in REGISTER and "dialog.showModal()" in REGISTER
    assert 'id="terms-dialog"' in REGISTER and 'href="/terms.html"' in REGISTER
    assert "terms_version: TERMS_VERSION" in REGISTER and "agreed: boxes().map(b => b.dataset.id)" in REGISTER
    assert "boxes().every(b => b.checked)" in REGISTER                                  # required 를 우회해도 한 번 더
    assert 'from "/js/terms.js"' in TERMS_HTML and "renderTerm(t, esc)" in TERMS_HTML and "window.print()" in TERMS_HTML
    assert REGISTER.count('id="agree-all"') == 1


def _body(**kw):
    base = dict(name="홍", email="a@x.com", password="Correct-Horse-9")
    return auth.RegisterBody(**{**base, **kw})


def test_server_checks_agreements_and_records_only_version_and_items():
    """TC-TM-05 · 빈 값은 이전처럼 받는다 · 필수가 빠지면 422 · 이상한 값은 걸러 판과 항목만 남긴다 · register 가 감사 기록을 남기는 줄이 있다."""
    assert auth._check_agreements(_body()) is None
    ok = auth._check_agreements(_body(terms_version="2026-10-29-v0.1", agreed=["invest", "service", "privacy", "service"]))
    assert ok == {"version": "2026-10-29-v0.1", "agreed": ["invest", "privacy", "service"]}
    for agreed in ([], ["service"], ["service", "privacy"], ["x" * 50, "service", "privacy"]):
        with pytest.raises(HTTPException) as e:
            auth._check_agreements(_body(terms_version="v", agreed=agreed))
        assert e.value.status_code == 422 and "모두 동의해야" in e.value.detail
    assert auth._check_agreements(_body(terms_version="v" * 100, agreed=list(auth.REQUIRED_AGREEMENTS)))["version"] == "v" * 40
    src = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
    assert 'await audit(user_id, client_id, "terms.agree", consent)' in src
    assert "이름 · 이메일은 싣지 않는다" in src                                          # 감사 기록에 개인정보를 늘리지 않는다


def test_terms_page_is_served_without_login():
    """TC-TM-04b · /terms.html 이 로그인 여부와 상관없이 열리는 라우트가 있다(가입 전 사람이 전문을 읽는다) — 없으면 404 였다."""
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    block = main.split('@app.get("/terms.html"', 1)[1].split("@app.get(", 1)[0]
    assert 'FileResponse(os.path.join(_public, "terms.html"))' in block
    assert "_logged_in" not in block and "RedirectResponse" not in block


def test_mypage_withdraw_notice_matches_what_happens():
    """TC-TM-06 · 탈퇴 안내문이 「누구였는지 지운 채」 (고객번호가 남는 사실과 어긋남) 대신 약관과 같은 말을 한다."""
    assert "누구였는지 지운 채" not in APP
    assert "이름 · 이메일 등 계정 정보와의 연결을 끊은 채 남습니다. 이때 고객번호는 기록에 남습니다." in APP


def test_render_escapes(tmp_path):
    """TC-TM-07 · renderTerm 이 제목 · 문단을 이스케이프하고 항목 id 로 앵커를 만든다."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(
        f'import * as t from "{(PUB / "js" / "terms.js").resolve().as_uri()}";\n'
        'const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");\n'
        'const html = t.renderTerm({id: "x", title: "<b>제목</b>", lead: "a&b", clauses: [{h: "h<1>", b: ["p<script>"]}]}, esc);\n'
        'process.stdout.write(JSON.stringify({html, n: t.TERMS.length, byId: t.termById("privacy")?.title, none: t.termById("nope")}));\n',
        encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert "&lt;b&gt;제목&lt;/b&gt;" in out["html"] and "<script>" not in out["html"] and 'id="terms-x"' in out["html"]
    assert out["n"] == 3 and out["byId"] == "개인정보 수집 · 이용 동의" and out["none"] is None
