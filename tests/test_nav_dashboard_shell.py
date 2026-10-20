"""위 메뉴 · 전체 메뉴 · 첫 화면 시험 (TC-NV) — 강사님 기초 코드 9478811 화면 쪽 반영 (2026-10-03).

화면 결정 셋(Figma 「Qurious · 투자 대시보드 · 메뉴 정리」 05 결정 기록)을 다음 강사님 반영 · 팀원 수정에서도 지킨다.
  ① C  첫 화면 = 투자 대시보드 + 우리 서비스 맞춤(KIS 키는 사용자마다 · 서버 설정 이름을 화면에 내지 않음)
  ② D  → 2026-10-18 D129 안 가 — 위 고정 탭 여섯 + 왼쪽 「전체 메뉴」 트리 · 좁은 화면은 ☰ 로 같은 트리
  ③ C  증권사 API 설정의 새 칸 + 쉬운 안내
화면 동작(폭에 따라 접히는 탭 줄 · ☰ 트리 열고 닫기)은 브라우저로 확인한다 — 여기서는 그 동작이 기대는 약속(순서 · 빠짐없음 ·
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


def test_top_tabs_are_the_fixed_six():
    """TC-NV-01 · 위 메뉴 탭(app.html)은 core.js MENU_TOP 과 같은 차례의 고정 여섯이다(2026-10-18 화면 결정 D129 안 가 ·
    사용자 S124 — 로보 어드바이저 · 투자 인디케이터 · 모의투자 · 퀀트자동매매 · 학습 · 데이터). 「학습」 탭은 금융 필수 지식으로 간다."""
    bar = APP[APP.index('<div class="gnb-tabs">'):]
    bar = bar[: bar.index("</div>")]
    tabs = re.findall(r'data-gnb="([a-z]+)"', bar)
    assert tabs == _str_list("MENU_TOP") == ["agent", "company", "paper", "quant", "finance", "crawl"]
    assert 'data-gnb="finance"><i class="fa-solid fa-book-open"></i> 학습</button>' in bar, "「학습」 탭 = 금융 필수 지식 묶음"


def test_every_menu_group_is_in_the_left_tree():
    """TC-NV-02 · 메뉴 묶음은 하나도 빠짐없이 한 번씩 왼쪽 「전체 메뉴」 트리(MENU_TREE)에 있고, 위 탭 여섯은 그 안의 지름길이다 ·
    개념 학습은 「학습」(금융 필수 지식) 바로 아래 묶음이다."""
    tree, top = _str_list("MENU_TREE"), _str_list("MENU_TOP")
    assert len(tree) == len(set(tree)), "트리에 같은 묶음이 두 번"
    assert sorted(tree) == sorted(_gnb_menu_keys()), "새 묶음을 GNB_MENUS 에 더했다면 MENU_TREE 에도"
    assert set(top) <= set(tree)
    assert "learn" not in tree, "개념 학습은 「학습」 한 묶음 안(2026-10-20 안 A — 금융 필수 지식 · 개발 개념 · 파이썬 중급 · 특강)"


def test_tree_keeps_headings_outside_links_and_buttons():
    """TC-NV-03 · 트리는 소제목(heading)을 누를 수 없는 글로, 바깥 주소(href)를 링크 + 숨은 글 「(새 화면)」 으로, 화면 항목을
    키보드로 닿는 button 으로 그린다 · 묶음은 details/summary · 화면을 옮기면 지금 묶음만 펼치고(사용자 S124) 지금 화면에
    aria-current 를 단다 · 탭 폭을 다시 잰다. 강사님 판 빌더(묶음 둘 제외)는 되돌아오지 않는다."""
    item = _fn(CORE, "function lnbItem(it)")
    assert "it.heading" in item and 'class="lnb-heading"' in item
    assert "it.href" in item and "<a " in item and "data-menu-href" in item and '<span class="sr-only">(새 화면)</span>' in item
    assert '<button type="button"' in item and 'data-view="${it.key}"' in item, "화면 항목은 키보드로 닿는 button"
    tree = _fn(CORE, "function renderLnbTree()")
    assert "MENU_TREE" in tree and '<details class="lnb-group"' in tree and '<summary class="lnb-group-head"' in tree
    assert '!["agent", "company"].includes' not in CORE, "강사님 판 빌더가 되돌아왔다"
    nav = _fn(CORE, "function navigate(")
    assert "syncLnbTree(currentGnb, navKey);" in nav and "fitGnbTabs();" in nav
    assert "const navKey = VIEW_PARENT[viewKey] || viewKey;" in nav, "메뉴 줄이 없는 화면(장 · 부 목차)은 따를 줄로 트리 · 머리 경로를 고른다(2026-10-20)"
    sync = _fn(CORE, "function syncLnbTree(")
    assert "if (moved) group.open = here;" in sync, "다른 묶음으로 옮기면 지금 묶음만 펼친다(사용자 S124)"
    assert 'setAttribute("aria-current", "page")' in sync
    assert '<nav id="lnb-nav" class="lnb-nav" aria-label="전체 메뉴"></nav>' in APP
    assert '<div id="lnb-section-title" class="lnb-section-title">전체 메뉴</div>' in APP


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
# 폭별 동작(2026-10-18 D129 — 탭은 전부 아니면 0 · 넓어지면 탭이 줄지 않음 · 가로 넘침 0)은 브라우저 점검
# tests/e2e/gnb_widths.py 가 본다 — 여기서는 그 동작이 기대는 약속을 파일에서 본다.
MORE = (PUB / "js" / "gnbmore.js").read_text(encoding="utf-8")
QCSS = (PUB / "css" / "qurious.css").read_text(encoding="utf-8")


def test_more_tab_and_right_drawer_are_gone():
    """TC-NV-08 · 「더보기 N ▾」 · 오른쪽 서랍 「전체 메뉴」 · 「⋮」 단추는 없다(2026-10-18 D129 — 숨은 묶음이 없고 모든 묶음은
    왼쪽 트리에 있다) — 옛 길이 되살아나면 메뉴가 두 곳 두 꼴이 된다. 아바타 메뉴의 「내 계정」 은 GNB_MENUS 하나로 그린다."""
    for word in ('id="gnb-more-btn"', 'id="gnb-offcanvas"', 'id="gnb-offcanvas-backdrop"'):
        assert word not in APP, word
    for word in ("gnb-more-tab", "MENU_PRIORITY", "MENU_DRAWER_ONLY", "markMoreActive", "gnb-overflow", "drawerItem"):
        assert word not in CORE and word not in MORE, word
    assert ".gnb-more-tab" not in QCSS and "gnb-more-btn" not in QCSS
    assert re.search(r'^import \{[^}]*GNB_MENUS[^}]*\} from "/js/core\.js";', MORE, flags=re.M)
    assert 'role="menu"' not in MORE, "링크 · 단추 목록이라 메뉴 역할을 쓰지 않는다(APG Disclosure)"


def test_fit_folds_tagline_icons_then_whole_row():
    """TC-NV-09 · fitGnbTabs 는 탭을 하나씩 숨기지 않는다 — 다 안 들어가면 ① 로고 부제 → ② 탭 아이콘 → ③ 탭 줄 통째(gnb-notabs)
    차례로 접는다(반만 보이는 탭 줄은 두지 않는다 · 메뉴는 왼쪽 트리 · ☰ 에 같다). 폭 경계(@media)가 아니라 실제 폭으로 잰다."""
    fn = _fn(CORE, "function fitGnbTabs()")
    assert 'classList.remove("gnb-noicons", "gnb-notagline", "gnb-notabs")' in fn
    i1, i2, i3 = (fn.index(f'classList.add("{c}")') for c in ("gnb-notagline", "gnb-noicons", "gnb-notabs"))
    assert 0 < i1 < i2 < i3, "접는 차례 — 부제 → 아이콘 → 탭 줄 통째"
    assert "gnb-overflow" not in fn and "shown.push" not in fn, "탭을 하나씩 숨기지 않는다"
    assert '#gnb.gnb-notagline .gnb-logo-text span[data-brand="tagline"] { display: none; }' in QCSS
    assert "#gnb.gnb-noicons .gnb-item > i { display: none; }" in QCSS
    assert "#gnb.gnb-notabs .gnb-tabs .gnb-item { display: none; }" in QCSS


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
    assert '#user-name, #logout-btn, #sync-badge-text' in QCSS
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


# ── 메뉴 개편 (2026-10-18 화면 결정 D129 안 가 · 사용자 S124 · Figma 「Qurious · 메뉴 개편」 05 · 06) ─────────────────────
# 폭별 동작(탭은 전부 아니면 0 · 가로 넘침 0 · ☰ 트리 열고 닫기)은 브라우저 점검 tests/e2e/gnb_widths.py 가 본다.
APPCSS = (PUB / "css" / "app.css").read_text(encoding="utf-8")
FINCSS = (PUB / "css" / "finlearn.css").read_text(encoding="utf-8")


def test_hamburger_opens_the_same_tree():
    """TC-NV-13 · 좁은 화면의 ☰ 는 같은 왼쪽 「전체 메뉴」 트리(#lnb)를 연다 — aria-expanded · aria-controls="lnb" · 어두운 막 누름 ·
    Esc · 화면이 바뀌면 · 트리 항목을 고르면 닫힌다(IA I12 남은 것 — 바깥 누름 닫기). 트리 너비는 min(300px, 86vw)."""
    mob = CORE[CORE.index("function setMobileLnb(open)"):]
    body = mob[: mob.index("\n}")]
    assert 'lnb.classList.toggle("mobile-open", open);' in body and 'setAttribute("aria-expanded", String(open))' in body
    assert 'btn.setAttribute("aria-controls", "lnb");' in mob
    assert 'event.key === "Escape"' in mob and 'lnbBackdrop.addEventListener("click"' in mob
    assert 'document.addEventListener("lumina:view-changed", () => setMobileLnb(false));' in mob
    assert "navigate(item.dataset.view); setMobileLnb(false);" in _fn(CORE, "function renderLnbTree()")
    assert "#lnb.mobile-open { width: min(300px, 86vw);" in QCSS and "#lnb-backdrop.open {" in QCSS
    assert "#lnb.mobile-open { display: flex; position: fixed;" in APPCSS, "☰ 트리는 768 아래에서 #lnb 를 띄우는 기존 규칙을 쓴다"


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4   # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_menu_text_colors_meet_contrast():
    """TC-NV-14 · 메뉴 글 대비 WCAG AA(보통 글 4.5) — 지금 탭 · 지금 항목은 --accent-h, 트리 소제목은 --text-heading, 「전체 메뉴」
    제목은 --brand-text(2026-10-18 Figma 06-5 · 사용자 S124 「셋 다 함께」 — 옛 값 4.37 · 2.56 · 3.19). 색 값을 파일에서 읽어 잰다.
    화면에서만 숨기는 글(.sr-only)도 정의돼 있어야 한다(옛 서랍의 「(새 화면)」 이 화면에 보였다)."""
    root = re.search(r":root \{ --text-heading: (#[0-9a-f]{6}); --brand-text: (#[0-9a-f]{6});", QCSS)
    assert root, "qurious.css :root 에 --text-heading · --brand-text"
    heading, brand = root.groups()
    accent_h = re.search(r"--accent-h:\s*(#[0-9a-fA-F]{6})", APPCSS).group(1)
    glow = re.search(r"--accent-glow:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", APPCSS)
    r, g, b = (int(glow.group(i)) for i in (1, 2, 3))
    a = float(glow.group(4))
    on_glow = "#" + "".join(f"{round(c * a + 255 * (1 - a)):02x}" for c in (r, g, b))   # 흰 바탕 위 옅은 파랑
    assert _contrast(accent_h, on_glow) >= 4.5, "지금 탭 · 지금 항목 글"
    assert _contrast(heading, "#ffffff") >= 4.5, "트리 소제목"
    assert _contrast(brand, "#ffffff") >= 4.5, "「전체 메뉴」 제목"
    assert "#gnb .gnb-item.active { color: var(--accent-h); }" in QCSS
    assert "#lnb .lnb-item.active { color: var(--accent-h); }" in QCSS
    assert "#lnb .lnb-section-title { color: var(--brand-text); }" in QCSS
    assert "color: var(--text-heading);" in FINCSS[FINCSS.index(".lnb-heading {"):]
    assert re.search(r"^\.sr-only \{ position: absolute; width: 1px; height: 1px;", QCSS, flags=re.M)


def test_tree_text_wraps_and_width_follows_screen():
    """TC-NV-15 · 트리 글은 자르지 않는다 — 빈칸에서 먼저 줄을 바꾸고 긴 덩어리는 아무 데서나(말줄임 없음) · 왼쪽 너비는 화면 폭에
    맞춰 clamp(240px, 15vw, 288px)(사용자 10-18 「화면에 맞게 메뉴 글씨 안 짤리도록 반응형으로」). 단추 항목은 글꼴 집만 물려받는다 —
    `font: inherit` 는 본문 18px · 줄 1.65 를 물려받아 항목이 묶음 머리보다 커졌다(S124 에 찾은 결함)."""
    assert "--lnb-w: clamp(240px, 15vw, 288px);" in QCSS
    assert "#lnb-nav .lnb-item, #lnb-nav .lnb-group-head { white-space: normal; line-height: 1.4; }" in QCSS
    assert "overflow-wrap: anywhere;" in QCSS and "text-overflow: clip;" in QCSS
    rule = re.search(r"^button\.lnb-item, a\.lnb-item \{([^}]*)\}", QCSS, flags=re.M)
    assert rule and "font-family: inherit" in rule.group(1) and "font: inherit" not in rule.group(1)

def test_view_change_scrolls_content_to_top():
    """TC-NV-16 · 다른 화면으로 옮기면 내용 칸(#main-content)을 맨 위로 — 굴러가는 칸이 창이 아니라 그 칸이라 브라우저가 자리를
    되돌려 주지 않는다. 앞 화면에서 내려간 자리를 물려받아 새 화면 중간에 떨어졌다(DF-134 · 2026-10-18 시연 영상을 찍다가 찾음).
    같은 화면을 다시 부르면 자리를 둔다."""
    nav = _fn(CORE, "function navigate(viewKey) {")
    assert nav.index("const moved = currentView !== viewKey;") < nav.index("currentView = viewKey;"), "옮기는지는 지금 화면을 바꾸기 전에 잰다"
    assert 'if (moved) document.getElementById("main-content")?.scrollTo(0, 0);' in nav
    assert '<main id="main-content">' in APP, "내용 칸 이름이 바뀌면 맨 위로 되돌리기가 헛돈다"
    css = (PUB / "css" / "app.css").read_text(encoding="utf-8")
    rule = re.search(r"#main-content \{([^}]*)\}", css)
    assert rule and "overflow-y: auto" in rule.group(1), "굴러가는 칸이 #main-content 가 아니면 이 시험을 다시 본다"
