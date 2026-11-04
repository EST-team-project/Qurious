"""내 계정(마이페이지) 구역 목록 시험 (TC-MP) — 설계 v0.1 ㉯ · 1차 (2026-10-29).

마이페이지를 「왼쪽 구역 목록 + 본문」 으로 나눌 때 지킬 약속을 파일에서 본다.
  - 기존 칸 id 는 그대로, 문서 안에 한 번씩만 (다른 화면의 스크립트가 같은 이름으로 칸을 찾는다)
  - 증권사 · 알림 · 외부 연동(Open API) 설정 본체는 모두 이 화면 안 구역에 있다(알림 2026-11-03 ②-31 · Open API 같은 날 S195). 옛 화면 키는 빈 껍데기로 남는다
  - 구역 전환은 주소 해시를 건드리지 않는다 (해시는 화면 키 자리 — 겹치면 새로고침 때 마이페이지를 잃는다)
화면이 실제로 바뀌는 모습(1280 · 390 폭)은 브라우저로 확인한다 — 여기서는 그 동작이 기대는 약속을 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
APP = (PUB / "app.html").read_text(encoding="utf-8")
MYPAGE_JS = (PUB / "js" / "mypage.js").read_text(encoding="utf-8")
CSS = (PUB / "css" / "qurious.css").read_text(encoding="utf-8")

# 이 화면이 가졌던 칸 — 이름을 바꾸면 안 된다
LEGACY_IDS = [
    "mp-name", "mp-email", "mp-created", "mp-roles", "mp-name-form", "mp-name-input",
    "mp-pw-rules", "mp-pw-form", "mp-pw-current", "mp-pw-new", "mp-pw-new2",
    "mp-sessions", "mp-logout-all", "mp-delete-form", "mp-del-pw", "mp-del-confirm",
]
SECTION_KEYS = ["profile", "security", "broker", "notify", "external", "display", "danger"]


def _mypage_view() -> str:
    m = re.search(r'<div class="view" data-view="mypage">(.*?)\n          <div class="view" data-view="notification-settings">', APP, re.S)
    assert m, "app.html 에 마이페이지 view 가 없다"
    return m.group(1)


def test_legacy_ids_kept_once():
    """TC-MP-01 · 기존 칸 id 열여섯이 문서 전체에서 정확히 한 번씩 있고, 새 mp- id 도 겹치지 않는다."""
    ids = re.findall(r'id="(mp-[a-z0-9-]+)"', APP)
    for legacy in LEGACY_IDS:
        assert ids.count(legacy) == 1, f"{legacy} 가 {ids.count(legacy)}번 있다"
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"겹치는 id: {dup}"
    # 기존 칸은 모두 마이페이지 view 안에 있다
    view = _mypage_view()
    for legacy in LEGACY_IDS:
        assert f'id="{legacy}"' in view, f"{legacy} 가 마이페이지 view 밖에 있다"


def test_sections_match_nav():
    """TC-MP-02 · 구역 목록의 버튼마다 본문 구역이 하나씩 있고, mypage.js 의 SECTIONS 와 같은 일곱 개다."""
    view = _mypage_view()
    navs = re.findall(r'data-mp-go="([a-z]+)"', view)
    secs = re.findall(r'<section id="mp-sec-([a-z]+)"', view)
    assert navs == SECTION_KEYS and secs == SECTION_KEYS, (navs, secs)
    m = re.search(r"const SECTIONS = \[([^\]]*)\]", MYPAGE_JS)
    assert m and re.findall(r'"([a-z]+)"', m.group(1)) == SECTION_KEYS, "mypage.js SECTIONS 가 목록과 다르다"


def test_summary_links_point_to_real_views():
    """TC-MP-03 · 알림 · Open API 설정 본체는 이 화면 안에 있어 다른 화면으로 보내는 링크가 없고(옛 주소는 구역을 여는 주소로 남는다),
    요약 칸 id 는 다른 화면의 칸과 겹치지 않는다."""
    view = _mypage_view()
    assert 'data-view="paper-openapi"' in APP and 'data-view="notification-settings"' in APP   # 빈 껍데기 — 주소 · 점수 · 사용법 키
    assert 'href="#notification-settings"' not in view, "알림은 구역 안에 있으니 다른 화면으로 보내는 링크가 없다"
    assert 'href="#paper-openapi"' not in view, "Open API 도 구역 안에 있으니 다른 화면으로 보내는 링크가 없다"
    # 요약 칸은 mp-sum- 접두사만 — mypage view 가 문서 앞쪽이라 다른 화면 스크립트의 getElementById 가 먼저 잡으면 안 된다
    assert 'id="trading-broker-status"' not in view, "마이페이지 view 에 다른 화면의 칸이 있다"
    assert 'id="broker-app-key"' in view
    assert re.findall(r'id="(mp-sum-[a-z]+)"', view) == ["mp-sum-broker", "mp-sum-notify", "mp-sum-external"]


def _notify_section() -> str:
    m = re.search(r'<section id="mp-sec-notify".*?</section>', APP, re.S)
    assert m, "마이페이지에 알림 구역이 없다"
    return m.group(0)


def test_notification_settings_body_lives_in_notify_section():
    """TC-MP-08 · 알림 설정 본체(②-31)는 알림 구역 안에 한 번씩만 있고, 옛 화면 키는 빈 껍데기로 남으며, 주소는 구역을 연다."""
    body = _notify_section()
    for cid in ("noti-save", "noti-test", "noti-status", "noti-history", "noti-consent", "noti-telegram-token", "noti-quiet-start"):
        assert body.count(f'id="{cid}"') == 1 and APP.count(f'id="{cid}"') == 1, cid
    # 껍데기 — 처음 주소 이동 검사(main.js)와 점수 · 사용법 키가 이 화면 키를 찾는다
    assert '<div class="view" data-view="notification-settings"></div>' in APP
    alias = (PUB / "js" / "viewalias.js").read_text(encoding="utf-8")
    assert re.search(r'MYPAGE_HOSTED = Object\.freeze\(\{[^}]*"notification-settings":\s*"notify"', alias)
    # 구역을 보일 때 알림 설정을 불러오고, main.js 가 따로 부르지 않는다(두 번 불러오지 않게)
    assert 'if (key === "notify") loadNotificationSettings();' in MYPAGE_JS
    assert "!MYPAGE_HOSTED[view]" in MYPAGE_JS
    main_js = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    assert "loadNotificationSettings" not in main_js
    core_js = (PUB / "js" / "core.js").read_text(encoding="utf-8")
    assert "MYPAGE_HOSTED[shownView]" in core_js


def _external_section() -> str:
    m = re.search(r'<section id="mp-sec-external".*?</section>', APP, re.S)
    assert m, "마이페이지에 외부 연동 구역이 없다"
    return m.group(0)


def test_openapi_settings_body_lives_in_external_section():
    """TC-MP-09 · Open API 설정 본체(S195)는 외부 연동 구역 안에 한 번씩만 있고, 옛 화면 키는 빈 껍데기로 남으며, 주소는 구역을 연다."""
    body = _external_section()
    ids = ("po-label", "po-create", "po-new-key", "po-keys", "po-docs", "po-alpaca-key", "po-alpaca-secret",
           "po-alpaca-account", "po-alpaca-positions", "po-alpaca-result")
    for cid in ids:
        assert body.count(f'id="{cid}"') == 1 and APP.count(f'id="{cid}"') == 1, cid
    assert re.findall(r'id="(po-[a-z-]+)"', APP) == list(ids), "po- 칸은 모두 외부 연동 구역 안에만 있다"
    # 껍데기 — 처음 주소 이동 검사(main.js) · 점수 · 사용법 키가 이 화면 키를 찾는다
    assert '<div class="view" data-view="paper-openapi"></div>' in APP
    alias = (PUB / "js" / "viewalias.js").read_text(encoding="utf-8")
    assert re.search(r'MYPAGE_HOSTED = Object\.freeze\(\{[^}]*"paper-openapi":\s*"external"', alias)
    # 구역을 보일 때 불러오고, 화면 활성화 쪽(paper.js onPaperViewActivated)은 따로 부르지 않는다(두 번 불러오지 않게)
    assert 'if (key === "external") loadPaperOpenApi();' in MYPAGE_JS
    paper_js = (PUB / "js" / "paper.js").read_text(encoding="utf-8")
    assert "export async function loadPaperOpenApi()" in paper_js
    activated = paper_js.split("export function onPaperViewActivated(view) {", 1)[1].split("\n}\n", 1)[0]
    assert "loadPaperOpenApi" not in activated and "paper-openapi" not in activated


def test_openapi_key_is_never_put_in_html_unescaped():
    """TC-MP-10 · 새로 발급한 Open API 키 원문은 escHtml 을 거쳐서만 HTML 에 들어가고, URL · 저장소 · 로그로 새지 않는다."""
    paper_js = (PUB / "js" / "paper.js").read_text(encoding="utf-8")
    body = paper_js.split("async function createApiKey()", 1)[1].split("\n}\n", 1)[0]
    assert "escHtml(k.apiKey)" in body
    assert body.count("k.apiKey") == 2, "키 원문은 화면에 보이는 한 곳과 복사 한 곳에서만 쓴다"
    for leak in ("localStorage", "sessionStorage", "console.", "location.", "history."):
        assert leak not in body, leak


def test_display_card_goes_to_named_section():
    """TC-MP-04 · 화면 설정 카드는 이름으로 지정한 구역에 붙고, 용어 풀이 위치 목록(TC-GL-28)은 그대로 쓴다."""
    assert 'getElementById(id)' in MYPAGE_JS or "const $ = (id) => document.getElementById(id);" in MYPAGE_JS
    assert '$("mp-sec-display")' in MYPAGE_JS, "화면 설정 카드를 붙일 자리를 이름으로 지정해야 한다"
    assert ".space-y-4" not in MYPAGE_JS, "첫 .space-y-4 를 찾는 옛 방식이 남아 있다"
    assert "TERM_VIEWS" in MYPAGE_JS and "setTermView" in MYPAGE_JS


def test_section_switch_does_not_touch_hash_and_summary_reads_only_needed_fields():
    """TC-MP-05 · 구역 전환은 주소 해시를 안 건드린다. 알림 응답에서는 channels 만 읽는다(토큰 · 비밀번호 원문은 변수에도 담지 않는다)."""
    assert "location.hash" not in MYPAGE_JS and "history." not in MYPAGE_JS
    for secret in ("telegram_token", "slack_webhook_url", "email_password", "kakao_api_secret", "sms_api_secret"):
        assert secret not in MYPAGE_JS, f"mypage.js 가 {secret} 을 읽는다"
    # 세 요약 요청은 따로 실패한다
    body = MYPAGE_JS.split("async function loadSummaries()", 1)[1].split("\n}\n", 1)[0]
    assert body.count(".catch(() => null)") == 3


def test_settings_views_untouched():
    """TC-MP-06 · 설정 화면 셋의 화면 키는 그대로 있다 — 알림 · Open API 는 본체가 마이페이지 구역으로 옮겨 가 빈 껍데기다."""
    for key in ("settings", "notification-settings", "paper-openapi"):
        assert f'<div class="view" data-view="{key}">' in APP, key
    # trading.js 가 읽는 증권사 칸 4개(앱 키 · 비밀키 · 계좌 · 모의 여부)가 settings 화면에 한 번씩
    for cid in ("broker-app-key", "broker-app-secret", "broker-account", "broker-paper"):
        assert APP.count(f'id="{cid}"') == 1, cid


def test_css_has_list_to_body_for_narrow_screens():
    """TC-MP-07 · 좁은 화면(≤768)에서 목록 → 본문 한 번에 하나만 보이는 규칙이 있다."""
    assert ".mp-shell[data-mp-pane=\"list\"] .mp-body { display: none; }" in CSS
    assert ".mp-shell[data-mp-pane=\"body\"] .mp-nav { display: none; }" in CSS
    assert ".mp-sec { display: none; }" in CSS and ".mp-sec.active { display: block; }" in CSS


def test_openapi_secret_hardening():
    """TC-MP-11 — 보안 검수(S195 · 11-03): Alpaca 시크릿 칸은 브라우저 저장 제안을 막고(`autocomplete`) 칸마다 이름표가 있고 ·
    마이페이지 다른 구역으로 가면 한 번 보여 준 새 Open API 키 원문을 DOM 에서 치운다.
    입력칸은 호출 뒤에 비우지 **않는다** — 서버는 키 칸이 비면 서버 환경변수 키로 대신 조회해(`app/routes/paper.py`) 비우면 두 번째 조회가
    사용자가 넣은 계정이 아닌 다른 계정 것이 된다(코드 검수 S195)."""
    html = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    key = re.search(r'<input id="po-alpaca-key"[^>]*>', html).group(0)
    secret = re.search(r'<input id="po-alpaca-secret"[^>]*>', html).group(0)
    assert 'autocomplete="off"' in key and 'autocomplete="new-password"' in secret and 'type="password"' in secret
    for tag in (key, secret, re.search(r'<input id="po-label"[^>]*>', html).group(0)):
        assert "aria-label=" in tag
    paper = (ROOT / "public" / "js" / "paper.js").read_text(encoding="utf-8")
    assert '$("po-alpaca-secret").value = ""' not in paper and '$("po-alpaca-key").value = ""' not in paper
    assert '$("po-new-key").innerHTML = "";' not in paper          # 같은 구역을 다시 눌러도 발급 직후 키 원문이 사라지지 않는다(구역이 바뀔 때만 치움)
    mypage = (ROOT / "public" / "js" / "mypage.js").read_text(encoding="utf-8")
    assert re.search(r'if \(key === "external"\) loadPaperOpenApi\(\);[^\n]*\r?\n\s*else \{ const nk = document\.getElementById\("po-new-key"\); if \(nk\) nk\.innerHTML = ""; \}', mypage)
