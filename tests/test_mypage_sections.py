"""내 계정(마이페이지) 구역 목록 시험 (TC-MP) — 설계 v0.1 ㉯ · 1차 (2026-10-29).

마이페이지를 「왼쪽 구역 목록 + 본문」 으로 나눌 때 지킬 약속을 파일에서 본다.
  - 기존 칸 id 는 그대로, 문서 안에 한 번씩만 (다른 화면의 스크립트가 같은 이름으로 칸을 찾는다)
  - 증권사 · 알림 · 외부 연동은 요약 + 링크만 — 설정 화면 셋은 한 글자도 안 바뀌고 링크가 가리키는 화면이 실제로 있다
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
    """TC-MP-03 · 요약 구역의 링크가 가리키는 설정 화면 셋이 실제로 있고, 요약 칸 id 는 다른 화면의 칸과 겹치지 않는다."""
    view = _mypage_view()
    for href in ("#settings", "#notification-settings", "#paper-openapi"):
        assert f'href="{href}"' in view, f"{href} 링크가 없다"
        assert f'data-view="{href[1:]}"' in APP, f"{href[1:]} 화면이 없다"
    # 요약 칸은 mp-sum- 접두사만 — mypage view 가 문서 앞쪽이라 다른 화면 스크립트의 getElementById 가 먼저 잡으면 안 된다
    for foreign in ('id="trading-broker-status"', 'id="broker-app-key"', 'id="noti-', 'id="po-'):
        assert foreign not in view, f"마이페이지 view 에 다른 화면의 칸 {foreign} 이 있다"
    assert re.findall(r'id="(mp-sum-[a-z]+)"', view) == ["mp-sum-broker", "mp-sum-notify", "mp-sum-external"]


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
    """TC-MP-06 · 설정 화면 셋(칸 id 포함)은 이번 1차에서 그대로 있다 — 본체 이동은 2차."""
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
