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
    # 서버가 아는 현재 판이 화면 문구 파일의 판과 같다 — 다르면 가입이 「약관이 바뀌었습니다」 로 막힌다
    assert re.search(r'export const TERMS_VERSION = "([^"]+)"', TERMS_JS).group(1) == auth.TERMS_VERSION


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
    """TC-TM-05 · 서버가 동의를 강제한다(판 번호 · 필수 셋 없으면 422) · 필수가 빠지면 422 · 이상한 값은 걸러 판과 항목만 남긴다 · register 가 감사 기록을 남기는 줄이 있다."""
    ok = auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=["invest", "service", "privacy", "service"]))
    assert ok == {"version": auth.TERMS_VERSION, "agreed": ["invest", "privacy", "service"], "optional": []}
    # 강제다 — 판 번호 · 동의 목록이 없는 직접 호출도 막는다(S162 · 이전에는 None 으로 통과)
    for kw in ({}, {"terms_version": auth.TERMS_VERSION}, {"agreed": list(auth.REQUIRED_AGREEMENTS)},
               {"terms_version": "  ", "agreed": list(auth.REQUIRED_AGREEMENTS)}):
        with pytest.raises(HTTPException) as e:
            auth._check_agreements(_body(**kw))
        assert e.value.status_code == 422 and "동의해야 가입" in e.value.detail
    for agreed in ([], ["service"], ["service", "privacy"], ["x" * 50, "service", "privacy"], ["nope", "service", "privacy"]):
        with pytest.raises(HTTPException) as e:
            auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=agreed))
        assert e.value.status_code == 422 and "모두 동의해야" in e.value.detail
    # 모르는 항목은 버린다 · 앞에 쓰레기를 많이 붙여도 필수 항목이 잘려 나가지 않는다
    padded = ["junk%d" % i for i in range(30)] + list(auth.REQUIRED_AGREEMENTS)
    assert auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=padded))["agreed"] == sorted(auth.REQUIRED_AGREEMENTS)
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


def test_optional_agreements_are_separate_from_required_and_empty_today():
    """TC-TM-09 · 필수와 선택이 섞이지 않는다 — 선택 항목은 필수 목록에 없고, 안 동의해도 가입이 되며, 지금은 비어 있다
    (앱이 하지 않는 광고성 정보 전송 같은 동의를 약관에 만들어 넣지 않는다 · 항목을 더할 때 이 시험이 분리를 지킨다)."""
    assert not set(auth.OPTIONAL_AGREEMENTS) & set(auth.REQUIRED_AGREEMENTS)
    assert auth.OPTIONAL_AGREEMENTS == ()
    ok = auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=list(auth.REQUIRED_AGREEMENTS)))
    assert ok["optional"] == []
    # 선택 항목이 생기면 — 필수만 동의해도 통과하고, 선택에 동의한 것만 optional 로 남는다
    auth.OPTIONAL_AGREEMENTS = ("alerts_sms",)
    try:
        assert auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=list(auth.REQUIRED_AGREEMENTS)))["optional"] == []
        both = auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=list(auth.REQUIRED_AGREEMENTS) + ["alerts_sms"]))
        assert both["optional"] == ["alerts_sms"] and "alerts_sms" in both["agreed"]
        with pytest.raises(HTTPException):  # 선택에만 동의하고 필수가 빠지면 막는다
            auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=["alerts_sms"]))
    finally:
        auth.OPTIONAL_AGREEMENTS = ()



def test_server_rejects_a_different_terms_version():
    """TC-TM-11 · 서버가 아는 판과 다른 판 번호는 거절한다 — 오래된 화면이 옛 문구에 동의하고 새 판 동의로 기록되지 않게."""
    agreed = list(auth.REQUIRED_AGREEMENTS)
    with pytest.raises(HTTPException) as e:
        auth._check_agreements(_body(terms_version="2020-01-01-v0.0", agreed=agreed))
    assert e.value.status_code == 422 and "새로고침" in e.value.detail
    assert auth._check_agreements(_body(terms_version=auth.TERMS_VERSION, agreed=agreed))["version"] == auth.TERMS_VERSION


def _age_ok(birth, today):
    try:
        auth._check_age(birth, today)
        return True
    except HTTPException as exc:
        assert exc.status_code == 422
        if birth:
            assert birth not in exc.detail                      # 오류 문구에 생년월일을 되돌리지 않는다
        return False


def test_age_check_is_full_years_and_rejects_bad_dates():
    """TC-TM-10 · 만 14세 — 생일 당일부터 가입 가능, 하루 모자라면 거절 · 미래 · 형식 오류 · 너무 먼 과거 · 빈 값 거절 · 2월 29일생."""
    from datetime import date
    today = date(2026, 10, 29)
    assert _age_ok("2012-10-29", today) is True        # 오늘이 만 14세 생일
    assert _age_ok("2012-10-30", today) is False       # 내일이 생일 → 아직 13세
    assert _age_ok("2000-01-31", today) is True
    assert _age_ok("2026-10-29", today) is False       # 오늘 태어남
    assert _age_ok("2027-01-01", today) is False       # 미래
    assert _age_ok("1890-01-01", today) is False       # 120년 넘게 과거
    for bad in ("", "abc", "2012-13-40", "2012/10/29", None):
        assert _age_ok(bad, today) is False
    # 2월 29일생은 평년에는 3월 1일에 한 살을 더한다(안전한 쪽)
    assert _age_ok("2012-02-29", date(2026, 2, 28)) is False
    assert _age_ok("2012-02-29", date(2026, 3, 1)) is True


def test_birth_date_is_never_stored_or_logged_or_echoed():
    """TC-TM-10b · 생년월일은 약관 · 처리방침이 「저장하지 않는다」 고 약속한다 — 사용자 행 · 감사 기록 · 다른 함수로 넘어가지 않는다."""
    src = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
    register = src.split('@router.post("/auth/register")', 1)[1].split("async def _guard_check", 1)[0]
    assert "_check_age(body.birth_date)" in register
    assert "birth_date" not in register.replace("_check_age(body.birth_date)", "")     # 다른 곳으로 넘기지 않는다
    assert 'consent["age_check"]' in register
    user_ctor = register.split("User(", 1)[1].split(")", 1)[0]
    assert "birth" not in user_ctor
    for model in (ROOT / "app" / "models").glob("*.py"):
        assert "birth" not in model.read_text(encoding="utf-8").lower(), f"{model.name} 에 생년월일 칸이 있다"


def test_register_screen_asks_birth_date_and_sends_it():
    """TC-TM-12 · 가입 화면이 생년월일 칸(필수)을 두고 만 14세 미만을 미리 안내하며 서버로 보낸다 · 처리방침 링크가 있다."""
    tag = REGISTER.split('name="birth_date"', 1)[1].split(">", 1)[0]
    assert 'type="date"' in tag and "required" in tag
    assert 'birth_date: fd.get("birth_date")' in REGISTER and "isUnder14" in REGISTER
    assert "저장하지 않습니다" in REGISTER
    assert 'href="/privacy.html"' in REGISTER


# ── 개인정보 처리방침 (TC-PP) ───────────────────────────────────────────

PRIVACY_HTML = (PUB / "privacy.html").read_text(encoding="utf-8")
POLICY_TEXT = TERMS_JS.split("export const POLICY = {", 1)[1].split("/** 한 항목 → HTML.", 1)[0]


def test_policy_has_the_items_of_pipa_30_and_the_officer():
    """TC-PP-01 · 처리방침 제30조 ① 의 항목(목적 · 항목 · 보유 · 제3자 제공 · 위탁 · 국외 이전 · 파기 · 권리 · 안전조치 · 쿠키 · 책임자)과 14세 · 변경이 있다."""
    heads = re.findall(r'h: "(\d+)\. ([^"]+)"', POLICY_TEXT)
    names = [h[1] for h in heads]
    for needed in ("처리 목적", "처리하는 개인정보 항목", "처리 및 보유 기간", "제3자 제공", "처리 위탁", "국외 이전",
                   "파기 절차와 방법", "이용자의 권리와 행사 방법", "안전성 확보조치", "쿠키 같은 자동 수집 장치",
                   "만 14세 미만", "개인정보 보호책임자", "처리방침의 변경"):
        assert needed in names, f"처리방침에 「{needed}」 가 없다"
    assert [int(h[0]) for h in heads] == list(range(1, len(heads) + 1))
    assert 'name: "이동원 (팀장)"' in TERMS_JS and 'email: "example@example.com"' in TERMS_JS and "placeholder: true" in TERMS_JS


def test_policy_does_not_promise_what_the_app_does_not_do():
    """TC-PP-02 · 앱에 없는 일을 쓰지 않는다(TC-TM-03 과 같은 금지어) · 숫자는 코드와 같다 · 자리표시 연락처는 보이는 곳마다 알린다."""
    for banned in ("암호화해", "암호화되어", "안전하게 보관", "다시 동의를 받", "추천합니다", "수익을 보장합니다"):
        assert banned not in POLICY_TEXT, f"「{banned}」 는 앱의 실제 동작과 맞지 않는다"
    assert f"{login_guard.MAX_FAILS}번 연속 실패하면 {login_guard.WINDOW_SEC // 60}분 동안 로그인이 잠깁니다" in POLICY_TEXT
    assert "암호화 저장은 하지 않습니다" in POLICY_TEXT and "저장하지 않습니다" in POLICY_TEXT
    assert "자리표시" in POLICY_TEXT and "PRIVACY_OFFICER.placeholder" in PRIVACY_HTML and "자리표시" in PRIVACY_HTML
    assert "광고 · 분석용 쿠키나 스크립트는 쓰지 않습니다" in POLICY_TEXT
    # 그 말이 사실인지 — 공개 화면에 분석 · 광고 스크립트가 없다
    for page in PUB.glob("*.html"):
        body = page.read_text(encoding="utf-8").lower()
        for tracker in ("googletagmanager", "google-analytics", "gtag(", "hotjar", "fbq("):
            assert tracker not in body, f"{page.name} 에 {tracker} 가 있다 — 처리방침의 「쓰지 않는다」 와 어긋난다"


def test_privacy_page_is_public_and_linked_from_signup_login_terms_and_landing():
    """TC-PP-03 · /privacy.html 이 로그인 없이 열리고 가입 · 로그인 · 약관 · 랜딩에서 이어진다 · 문구는 terms.js 한 곳에서 그린다."""
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    block = main.split('@app.get("/privacy.html"', 1)[1].split("@app.get(", 1)[0]
    assert 'FileResponse(os.path.join(_public, "privacy.html"))' in block
    assert "_logged_in" not in block and "RedirectResponse" not in block
    assert 'from "/js/terms.js"' in PRIVACY_HTML and "renderTerm(POLICY, esc)" in PRIVACY_HTML and "window.print()" in PRIVACY_HTML
    for name in ("register.html", "login.html", "terms.html", "index.html"):
        assert 'href="/privacy.html"' in (PUB / name).read_text(encoding="utf-8"), f"{name} 에 처리방침 링크가 없다"


def test_policy_and_consent_say_the_same_about_data_the_app_keeps():
    """TC-PP-04 · 처리방침의 보유 · 수집 문장이 개인정보 동의 문구와 같은 말이다 — 한쪽만 고쳐 어긋나는 일을 막는다."""
    privacy = TERMS_JS.split('id: "privacy"', 1)[1].split('id: "invest"', 1)[0]
    for sentence in ("탈퇴할 때까지 보관하고, 탈퇴하면 바로 삭제합니다.",
                     "이름 · 이메일 등 계정 정보와의 연결을 끊은 채 남기며, 이때 고객번호는 기록에 남습니다.",
                     "로그인 상태는 마지막 이용 뒤 30일이 지나면 만료되고",
                     "가입 화면에 입력하는 생년월일은 만 14세 이상인지 확인하는 데만 쓰고 저장하지 않습니다."):
        assert sentence in privacy and sentence in POLICY_TEXT, sentence
