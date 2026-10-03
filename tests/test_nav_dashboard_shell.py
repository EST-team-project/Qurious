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
    assert "markMoreActive()" in CORE[CORE.index("function navigate("):]


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
