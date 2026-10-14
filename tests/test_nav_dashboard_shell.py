"""위 메뉴 · 전체 메뉴 · 첫 화면 시험 (TC-NV) — 강사님 기초 코드 9478811 화면 쪽 반영 (2026-10-03).

화면 결정 셋(Figma 「Qurious · 투자 대시보드 · 메뉴 정리」 05 결정 기록)을 다음 강사님 반영 · 팀원 수정에서도 지킨다.
  ① C  첫 화면 = 투자 대시보드 + 우리 서비스 맞춤(KIS 키는 사용자마다 · 서버 설정 이름을 화면에 내지 않음)
  ② D  위 메뉴는 우선순위대로 들어가는 만큼(Priority+) · 더보기 = 모든 묶음을 담은 전체 메뉴
  ③ C  증권사 API 설정의 새 칸 + 쉬운 안내
화면 동작(폭에 따라 숨는 탭 · 서랍 열고 닫기)은 브라우저로 확인한다 — 여기서는 그 동작이 기대는 약속(순서 · 빠짐없음 ·
글)을 파일에서 본다.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
APP = (PUB / "app.html").read_text(encoding="utf-8")
CORE = (PUB / "js" / "core.js").read_text(encoding="utf-8")
MAIN = (PUB / "js" / "main.js").read_text(encoding="utf-8")


def _str_list(name: str) -> list[str]:
    m = re.search(rf"const {name} = \[([^\]]*)\];", CORE)
    assert m, f"core.js 에 {name} 가 없다"
    return re.findall(r'"([a-z]+)"', m.group(1))


def _fn(src: str, head: str) -> str:
    """`head` 로 시작하는 함수 본문(다음 줄 첫 칸의 `}` 까지)."""
    body = src[src.index(head):]
    return body[: body.index("\n}")]


def _gnb_menu_keys() -> list[str]:
    block = CORE[CORE.index("const GNB_MENUS = {"):]
    block = block[: block.index("\n};")]
    return re.findall(r"^  ([a-z]+): \{", block, flags=re.M)


def test_top_tabs_follow_priority_order():
    """TC-NV-01 · 위 메뉴 탭(app.html)은 core.js MENU_PRIORITY 와 같은 순서다 — Priority+ 는 앞에서부터 채운다."""
    bar = APP[APP.index('<div class="gnb-tabs">'):]
    bar = bar[: bar.index("</div>")]
    tabs = re.findall(r'data-gnb="([a-z]+)"', bar)
    assert tabs == _str_list("MENU_PRIORITY")
    assert tabs[:3] == ["agent", "company", "finance"], "결정 ② D — 로보 어드바이저 · 투자 인디케이터 · 금융 필수 지식이 앞 셋"


def test_every_menu_group_is_in_the_full_menu():
    """TC-NV-02 · 메뉴 묶음은 하나도 빠짐없이 전체 메뉴에 들어간다(위 메뉴 우선순위 + 서랍에만 있는 묶음) · 겹침 없음."""
    prio, only = _str_list("MENU_PRIORITY"), _str_list("MENU_DRAWER_ONLY")
    assert not set(prio) & set(only)
    assert sorted(prio + only) == sorted(_gnb_menu_keys()), "새 묶음을 GNB_MENUS 에 더했다면 MENU_PRIORITY 나 MENU_DRAWER_ONLY 에도"


def test_full_menu_keeps_headings_and_outside_links():
    """TC-NV-03 · 전체 메뉴는 소제목(heading)을 누를 수 없는 글로, 바깥 주소(href)를 링크로 그린다 — 강사님 판 빌더(묶음 둘 제외 ·
    모든 항목을 화면 단추로)는 소제목을 「undefined」 단추로, 개념 학습을 없는 화면으로 보냈다."""
    fn = CORE[CORE.index("function drawerItem(it)"):]
    fn = fn[: fn.index("\n}\n")]
    assert "it.heading" in fn and 'class="lnb-heading"' in fn
    assert "it.href" in fn and "<a " in fn and "data-menu-href" in fn
    assert '!["agent", "company"].includes' not in CORE, "강사님 판 빌더 · 더보기 표시가 되돌아왔다"
    # 화면을 옮기면 탭을 다시 맞춘다 — 지금 묶음 바꿔 끼우기 · 더보기 표시(fitGnbTabs 가 markMoreActive 까지 부른다 · DF-109)
    assert "fitGnbTabs()" in CORE[CORE.index("function navigate("):]
    assert "markMoreActive();" in _fn(CORE, "function fitGnbTabs()")


def test_first_screen_is_the_dashboard():
    """TC-NV-04 · 로그인 첫 화면은 투자 대시보드다(결정 ① C) — 진입 훅은 화면 키를 글자 그대로(화면 스캐너가 읽는 모양)."""
    assert '<div class="view" data-view="dashboard">' in APP
    assert ': "dashboard");' in MAIN, "주소에 화면이 없을 때 첫 화면"
    assert 'if (view === "dashboard") loadDashboard();' in MAIN
    assert 'href="/app.html#dashboard" class="gnb-logo"' in APP


def test_screen_text_has_no_server_setting_names():
    """TC-NV-05 · 대시보드 · 증권사 API 설정 화면 글에 서버 설정 이름 · 개발자 말 · 옛 서비스 이름이 없다(결정 ① C · ③ C)."""
    files = {"app.html": APP, "dashboard.js": (PUB / "js" / "dashboard.js").read_text(encoding="utf-8"),
             "settings.js": (PUB / "js" / "settings.js").read_text(encoding="utf-8")}
    banned = ("KIS_SECRETS_NAME", "DOMAIN_RAG_LAB_BASE_URL", "STOCK_COIN_TRADE_BASE_URL", "(레거시)",
              "자격증명은 서버(Secrets Manager)가 관리", "LUMINA INVEST", "Celery Beat")
    for name, text in files.items():
        for word in banned:
            assert word not in text, f"{name} 에 「{word}」"


def test_kis_hint_points_to_a_real_screen(monkeypatch):
    """TC-NV-06 · 키가 없을 때의 안내가 가리키는 화면 이름(증권사 API 설정)이 실제 메뉴에 있다 — 「종목 선정」 이라는 화면은 없다."""
    from app.config import settings
    from app.services import kis_quickstart as kq

    monkeypatch.setattr(settings, "STOCK_COIN_TRADE_BASE_URL", "")
    route = asyncio.run(kq.resolve_route(None))
    assert route.configured is False and "「증권사 API 설정」" in route.detail and "종목 선정" not in route.detail
    assert 'label: "증권사 API 설정"' in CORE


def test_dashboard_tabs_use_our_words_and_real_screens():
    """TC-NV-07 · 대시보드 계좌 탭(서버 글)에 옛 서비스 이름 · 서버 설정 이름이 없고, 「설정으로 이동」 링크는 앱에 있는 화면을
    가리킨다 — 강사님 판의 `#paper-account` 는 어느 판에도 없는 화면이었다(2026-10-03 브라우저 확인)."""
    src = (ROOT / "app" / "routes" / "dashboard.py").read_text(encoding="utf-8")
    literals = re.findall(r'"([^"\n]*)"', src)
    assert not [s for s in literals if "lumina" in s.lower()], "탭 글에 옛 서비스 이름"
    assert not [s for s in literals if re.search(r"\b[A-Z][A-Z0-9]*_(API_KEY|SECRET_KEY|BASE_URL|NAME)\b", s) and "미설정" in s]
    links = re.findall(r'link="#([a-z0-9-]+)"', src)
    assert links, "링크가 있는 탭"
    for key in links:
        assert f'data-view="{key}"' in APP, f"#{key} 화면이 앱에 없다"


# ── 위 메뉴 넘침 고침 (DF-109 · 2026-10-14 화면 결정 D84 = 융합안 D) ─────────────────────────────────
# 폭별 동작(숨은 수 = 더보기 숫자 · 넓어지면 탭이 줄지 않음 · 가로 넘침 0 · 1920 에서 열 묶음)은 브라우저 점검
# tests/e2e/gnb_widths.py 가 본다 — 여기서는 그 동작이 기대는 약속을 파일에서 본다.
MORE = (PUB / "js" / "gnbmore.js").read_text(encoding="utf-8")
QCSS = (PUB / "css" / "qurious.css").read_text(encoding="utf-8")


def test_more_tab_is_a_labelled_disclosure_button():
    """TC-NV-08 · 탭 줄 끝 더보기는 글자 「더보기」 를 가진 button 이고 aria-expanded · aria-controls 로 목록을 연다(APG
    Disclosure) — 아이콘 하나(「⋮」)가 아니고, 링크 · 단추 목록이라 role="menu" 를 쓰지 않는다. 목록은 GNB_MENUS 로 그린다."""
    assert 'more.type = "button"' in MORE and "더보기" in MORE
    assert 'setAttribute("aria-expanded"' in MORE and 'setAttribute("aria-controls"' in MORE
    assert 'role="menu"' not in MORE and "role = \"menu\"" not in MORE and "\"menu\")" not in MORE
    assert re.search(r'^import \{[^}]*GNB_MENUS[^}]*\} from "/js/core\.js";', MORE, flags=re.M), "목록은 core.js GNB_MENUS 하나로"
    assert 'bar.appendChild(more)' in MORE, "더보기는 탭 칸(.gnb-tabs) 끝에 — 오른쪽 끝이 아니다"
    assert "if (event.key === \"Escape\")" in MORE and "lumina:view-changed" in MORE, "Esc · 화면이 바뀌면 닫힘"


def test_fit_reserves_more_drops_icons_and_swaps_current_group():
    """TC-NV-09 · fitGnbTabs 는 ① 더보기 자리를 먼저 떼고 ② 다 안 들어가면 아이콘부터 빼고 ③ 지금 묶음이 숨으면 바꿔 끼우고
    ④ 숨은 묶음 키 · 수를 더보기에 적는다(목록은 그 값을 읽는다 — 계산은 한 곳)."""
    fn = _fn(CORE, "function fitGnbTabs()")
    assert 'getElementById("gnb-more-tab")' in fn and "more.offsetWidth" in fn
    assert 'classList.remove("gnb-noicons", "gnb-notagline")' in fn
    # 접는 차례 — 로고 부제 → 탭 아이콘 → 탭(폭 경계로 접으면 경계에서 넓어지는데 탭이 준다 · 1020 → 1040 실측)
    assert 0 < fn.index('classList.add("gnb-notagline")') < fn.index('classList.add("gnb-noicons")') < fn.index("shown.push(i)")
    assert '#gnb.gnb-notagline .gnb-logo-text span[data-brand="tagline"] { display: none; }' in QCSS
    assert "currentGnb" in fn and "shown.pop()" in fn, "지금 묶음 바꿔 끼우기"
    assert "more.dataset.hidden" in fn and "gnb-more-count" in fn
    assert "dataset.hidden =" not in MORE, "숨은 묶음 계산을 gnbmore.js 가 다시 하지 않는다(읽기만)"
    assert "#gnb.gnb-noicons .gnb-item > i { display: none; }" in QCSS


def test_header_defends_against_instructor_fixed_tab_strip():
    """TC-NV-10 · 강사님 새 판(5bb0e7e)의 `.gnb-tabs { flex: 0 0 auto }` · `.gnb-right { overflow: hidden }` 이 app.css 로 충돌 없이
    들어와도 우리 덧씌우기(qurious.css · app.css 뒤에 읽힘)가 탭 칸을 늘이고 오른쪽을 자르지 않게 덮는다 — 안 덮으면
    우선순위+ 가 멈춰 900 ~ 1366 에서 문서가 1,375px 로 넘치고 로그아웃 · 더보기가 사라진다(조사 실측)."""
    assert "#gnb .gnb-tabs { flex: 1 1 0%; min-width: 0; }" in QCSS
    assert "#gnb .gnb-right { flex: 0 0 auto; overflow: visible; }" in QCSS
    assert APP.index('href="/css/qurious.css') > APP.index('href="/css/app.css'), "덧씌우기는 app.css 뒤에 읽혀야 덮는다"


def test_avatar_menu_keeps_account_and_logout():
    """TC-NV-11 · 이름 · 로그아웃 단추는 머리에서 빠지고 아바타 메뉴로 간다 — 메뉴의 「내 계정」 항목은 GNB_MENUS.account 에서,
    로그아웃은 main.js 의 로그아웃 처리(숨은 #logout-btn)를 그대로 누른다(로그아웃 길은 하나)."""
    assert '#user-name, #logout-btn, #gnb-more-btn' in QCSS
    assert 'const ACCOUNT_GROUP = "account"' in MORE and "GNB_MENUS[ACCOUNT_GROUP]" in MORE
    assert 'getElementById("logout-btn")' in MORE and ".click()" in MORE
    assert 'document.getElementById("logout-btn").addEventListener("click"' in MAIN, "로그아웃 처리는 main.js 한 곳"
    assert 'addEventListener("click", () => navigate("mypage"))' not in MAIN, "아바타 누름은 메뉴를 연다(바로 이동하지 않음)"
    assert "initGnbMore();" in MAIN


def test_sync_badge_text_moves_to_title():
    """TC-NV-12 · 「n분 전 동기화」 글은 머리에서 숨기고(점만) 같은 글을 title · aria-label 로 옮긴다 — 글이 바뀔 때마다 따라간다."""
    assert "#sync-badge-text" in QCSS
    assert "MutationObserver" in MORE and 'getElementById("sync-badge-text")' in MORE
    assert "badge.title" in MORE and 'badge.setAttribute("aria-label"' in MORE
