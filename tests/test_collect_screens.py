"""수집 화면 셋 시험 (TC-CL) — 크롤링 세 화면 구현(UI 명세서 5절 · Figma 「데이터 수집 화면」 · 2026-10-08).

지키는 것
1. 「DB 초기화」 단추와 서버 길(`POST /api/admin/reset` · API-ADM-01)이 없다 — 그 길은 신용평가 참조 표 넷만이 아니라
   모든 사용자의 주문 · 포트폴리오 · 증권사 설정 · 채팅 · 크롤링 문서 · 감사 로그까지 지웠다(DF-78 · 2026-10-07 결정 ② A).
   개발용 초기화는 일회용 시험 DB(`scripts/personal/test.ps1`) · alembic 으로 한다.
2. 연결 — 메뉴 이름 셋 · 뿌리 칸 · 모양 파일 · 진입 훅(글자 그대로) · 화면 스캐너가 읽는 진입 API · 옛 단추와 그 리스너가 함께 없다
3. 화면 표 = 서버 열쇠 — 받을 범위 상태 · 러너 단계 결과 · 백업 점검 줄 상태를 화면이 다 안다(서버가 늘리면 이 시험이 먼저 깨진다)
4. 관리자 화면 — 일반 사용자에게 메뉴 셋 · 데이터 관제의 「자세히 →」 를 숨긴다(역할을 확인하기 전에도 숨긴 채)
5. 화면은 PC 쪽 일을 부르지 않는다(2026-10-08 결정 ①) — 화면이 보내는 쓰기는 주소 검사 · 주소로 받기 둘뿐, 나머지는 명령을 보인다
6. 데이터 관제는 단계 표 대신 한 줄(결정 ④) · 지난 회차에서 다시 돌린 줄을 회차와 나눠 그린다(DF-82)

글자를 찾는 시험은 주석에 속는다(2026-10-06 교훈) — 화면 글은 HTML 주석 · JS 줄 주석을 걷어 낸 뒤에 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "public" / "app.html"
JS_DIR = ROOT / "public" / "js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _html_text(src: str) -> str:
    """HTML 주석을 걷어 낸 글 — 「뺐다」 고 적은 설명 주석이 화면 글로 잡히지 않게."""
    return re.sub(r"<!--.*?-->", "", src, flags=re.S)


def _js_code(src: str) -> str:
    """JS 줄 주석(줄 머리의 `//`)을 걷어 낸 글."""
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_no_admin_reset_route():
    """TC-CL-01 · 서버 길이 없다 — 관리자 라우터에 `/reset` 이 없고, app/ 어디에도 그 길을 다시 만드는 줄이 없다(DF-78)."""
    from app.routes import admin

    paths = {(m, r.path) for r in admin.router.routes for m in getattr(r, "methods", set())}
    assert not any(p.endswith("/admin/reset") for _m, p in paths), sorted(paths)
    # 다른 파일에 같은 길을 새로 두는 경우까지 — 줄 머리부터 데코레이터 꼴로 찾는다(주석 속 글자에 속지 않게)
    deco = re.compile(r"^\s*@\w+\.(post|put|delete|patch|get)\(\s*[\"'](/api/admin)?/reset[\"']", re.M)
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py") if deco.search(_read(p))]
    assert hits == [], hits
    assert not re.search(r"^\s*async def reset_db\(", _read(ROOT / "app" / "routes" / "admin.py"), re.M)


def test_no_reset_button_or_call_on_screens():
    """TC-CL-02 · 화면에 「DB 초기화」 단추가 없고, 어느 화면 파일도 `/api/admin/reset` 을 부르지 않는다(DF-78)."""
    html = _html_text(_read(APP_HTML))
    assert 'id="admin-reset-btn"' not in html
    assert "DB 초기화" not in html
    callers = [p.name for p in JS_DIR.glob("*.js") if "/api/admin/reset" in _js_code(_read(p))]
    assert callers == [], callers
    # 사용법 안내(core.js 의 화면 설명)도 지운 단추를 가리키지 않는다
    assert "DB 초기화" not in _js_code(_read(JS_DIR / "core.js"))


VIEWS = ("crawl-auto", "crawl-manual", "crawl-ingest")


def test_wired_menu_roots_hooks_and_scanner():
    """TC-CL-03 · 연결 — 메뉴 이름 셋 · 뿌리 칸 · 모양 파일 · 진입 훅(글자 그대로) · 스캐너가 읽는 진입 API · 옛 단추 · 리스너가 함께 없다."""
    core, html = _read(JS_DIR / "core.js"), _read(APP_HTML)
    main, collect, agent = _read(JS_DIR / "main.js"), _read(JS_DIR / "collect.js"), _read(JS_DIR / "agent.js")
    crawl = core[core.index("  crawl: {"):core.index("  trading: {")]
    for key, label in zip(VIEWS, ("수집 일정 · 단계", "자료 직접 받기", "적재 · 백업")):
        assert re.search(rf'\{{ key: "{key}",\s*icon: "[^"]+",\s*label: "{label}" \}}', crawl), key
        assert re.search(rf'<div class="view" data-view="{key}"><div class="cl-root" data-cl="\w+"></div></div>', html), key
        assert f'if (view === "{key}")' in collect, f"진입 훅은 화면 키 글자 그대로 — {key}"
    assert 'href="/css/collect.css"' in html and (ROOT / "public" / "css" / "collect.css").is_file()
    assert re.search(r'^import \{ onCollectViewActivated \} from "/js/collect\.js";', main, re.M)
    assert re.search(r"^\s+onCollectViewActivated\(view\);", main, re.M)
    # 옛 단추가 app.html 에서 빠졌으면 agent.js 가 그 단추에 리스너를 걸지 않는다(null 오류로 agent.js 전체가 멈춘다)
    for old in ("auto-crawl-btn", "manual-crawl-btn", "naver-crawl-btn", "ingest-btn", "admin-reset-btn", "crawl-url"):
        assert f'id="{old}"' not in html, old
        assert f'getElementById("{old}")' not in _js_code(agent), old
    from scripts import view_scan
    entry = {r["key"]: set(r["entry_apis"]) for r in view_scan.scan()["rows"]}
    assert entry["crawl-auto"] == {"/api/data/runner"}
    assert entry["crawl-ingest"] == {"/api/data/backup"}
    assert {"/api/data/fetch-sources", "/api/data/fetch-plan", "/api/data/url-rules", "/api/data/url-check"} <= entry["crawl-manual"]


def _js_keys(src: str, name: str) -> set[str]:
    """`const NAME = { a: …, b: … }` 의 열쇠 · `const NAME = ["a", "b"]` 의 글자."""
    m = re.search(rf"const {name} = (\{{[^;]*?\}});|const {name} = \[([^\]]*)\];", src, re.S)
    assert m, name
    if m.group(1):
        return set(re.findall(r"(?:^|[{,\s])(\w+):", m.group(1)))
    return set(re.findall(r'"(\w+)"', m.group(2)))


def test_screen_tables_cover_server_keys():
    """TC-CL-04 · 화면 표 = 서버 열쇠 — 받을 범위 상태(fetch_plan.STATES) · 러너 단계 결과 · 백업 점검 줄 상태(backup_status.GROUP_STATE)."""
    from app.services import backup_status, fetch_plan

    src = _read(JS_DIR / "collect.js")
    assert _js_keys(src, "PLAN_ORDER") == set(fetch_plan.STATES)
    assert set(fetch_plan.TODO_STATES) <= set(fetch_plan.STATES)
    assert {"ok", "warning", "failed", "skipped"} <= _js_keys(src, "STEP_RESULT")
    assert _js_keys(src, "GROUP_TONE") == set(backup_status.GROUP_STATE)
    # 화면이 고르는 종류는 서버가 준 목록(fetch-sources)에서 — 종류 이름을 화면에 따로 적지 않는다(처음 값 하나만)
    assert re.findall(r'data-kind="(\w+)"', src) == [], "종류 단추는 서버 목록으로 그린다"


def test_admin_only_menus_hidden_by_default():
    """TC-CL-05 · 관리자 화면 — 일반 사용자에게 왼쪽 메뉴 · 전체 메뉴의 셋과 「자세히 →」 를 숨긴다 · 역할은 /api/me 의 roles 로."""
    css = _read(ROOT / "public" / "css" / "collect.css")
    for key in VIEWS:
        assert f'body:not(.q-admin) .lnb-item[data-view="{key}"]' in css, key
        assert f'body:not(.q-admin) [data-menu-view="{key}"]' in css, key
    assert "body:not(.q-admin) .q-admin-only" in css
    collect = _read(JS_DIR / "collect.js")
    assert re.search(r'classList\.toggle\("q-admin", admin\)', collect) and 'includes("admin")' in collect
    assert 'class="dh-more q-admin-only"' in _read(JS_DIR / "datahub.js")


def test_screens_do_not_run_pc_side_work():
    """TC-CL-06 · 화면이 보내는 쓰기는 주소 검사 · 주소로 받기 둘뿐 — 단계 다시 · 받기 · 원격 확인 · 리허설은 명령을 보인다(결정 ①)."""
    src = _js_code(_read(JS_DIR / "collect.js"))
    posts = re.findall(r'api\("([^"?]+)[^"]*",\s*\{\s*method:\s*"(POST|PUT|DELETE|PATCH)"', src)
    assert sorted(posts) == [("/api/data/url-check", "POST"), ("/api/ingest/crawl/url", "POST")], posts
    # 명령은 서버가 준 것을 그대로 보인다(러너 명령 · 받기 명령 · 백업 명령) — 화면이 명령 글을 지어내지 않는다(단계 이름만 끼운다)
    assert "d.rerun?.command" in src and "p.command" in src and "b.commands.remote" in src and "b.commands.restore" in src


def test_followup_skip_is_yellow_and_fill_command_from_catalog():
    """TC-CL-08 · 채울 것이 있는 건너뜀(서버가 넘긴 `followup` — 신호 단계 앱 DB 꺼짐 · 2026-10-08 안 B)은 노랑 「건너뜀」 과
    까닭 글을 보이고, 할 일 없는 건너뜀은 회색 그대로다. 「이 단계만 다시」 를 열면 단계 목록(러너 한 곳)의 빠진 날 채우기
    명령을 함께 보인다 — 화면이 명령 글을 지어내지 않는다(#142 답글 약속). 관제 한 줄도 그 회차를 확인할 것으로 칠한다."""
    src = _js_code(_read(JS_DIR / "collect.js"))
    table = src[src.index("function stepsTable"):src.index("function scheduleHtml")]
    assert re.search(r"s\.status === \"skipped\" && s\.followup", table), "건너뜀 가운데 뒤 할 일이 있는 줄만 따로 칠한다"
    bind = src[src.index("function bindSchedule"):src.index("async function renderCollectSchedule")]
    assert re.search(r"cat\?\.fill\s*\?\s*cmdBox\(cat\.fill,", bind), "채우기 명령은 단계 목록(catalog)의 fill 칸으로 상자를 그린다"
    assert re.search(r'"빠진 날 채우기"\)', bind), "상자 제목"
    hub = _js_code(_read(JS_DIR / "datahub.js"))
    assert re.search(r"s\.followup", hub[hub.index("const bad"):hub.index("const bad") + 200]), "관제 한 줄 표시도 채울 것을 본다"


def test_data_hub_one_line_and_reruns_apart():
    """TC-CL-07 · 데이터 관제 — 단계 표 대신 마지막 회차 한 줄(결정 ④) · 지난 회차에서 다시 돌린 줄은 「다시 돌림」 으로(DF-82)."""
    src = _js_code(_read(JS_DIR / "datahub.js"))
    assert "dh-steps" not in src and "dh-bar" not in src, "단계 표는 수집 일정 · 단계 화면으로 옮겼다"
    assert "dh-runline" in src and 'navigate("crawl-auto")' in src
    low = src[src.index("function lowCards"):src.index("function dataHubRoot")]
    assert re.search(r"if \(h\.only\)", low) and "다시 돌림" in low
