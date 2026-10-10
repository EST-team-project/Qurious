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
    # 수집 일정은 회차 기록과 수집 요청 목록(작업자 · 막는 때 · 2026-10-10 수집 단추)을 함께 읽는다
    assert entry["crawl-auto"] == {"/api/data/runner", "/api/data/runner/requests"}
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
    """TC-CL-06 · 화면은 PC 쪽 일을 직접 돌리지 않는다 — 화면이 보내는 쓰기는 주소 검사 · 주소로 받기와, 수집 요청 표에 줄을
    남기는 둘(만들기 · 취소 · 2026-10-10 수집 단추 결정)뿐이다. 요청 둘은 늘 화면 머리글(서버 `ACTION_HEADER`)을 붙이고, 돌리는
    일은 이 PC 의 작업자가 한다. 받기 · 원격 확인 · 리허설은 여전히 명령을 보인다(결정 ①)."""
    from app.services import collect_requests as cq

    src = _js_code(_read(JS_DIR / "collect.js"))
    posts = re.findall(r'api\("([^"?]+)[^"]*",\s*\{\s*method:\s*"(POST|PUT|DELETE|PATCH)"', src)
    assert sorted(posts) == [("/api/data/url-check", "POST"), ("/api/ingest/crawl/url", "POST")], posts
    req = _js_code(_read(JS_DIR / "collect-requests.js"))
    calls = re.findall(r'api\([`"](/api/[^`"?]+)[^`"]*[`"],\s*\{([^}]*)\}', req)
    writes = sorted((p, opts) for p, opts in calls if re.search(r'method:\s*"(POST|PUT|DELETE|PATCH)"', opts))
    assert [p for p, _ in writes] == ["/api/data/runner/requests", "/api/data/runner/requests/${id}/cancel"], writes
    assert all(re.search(r"headers:\s*ACTION\b", opts) for _, opts in writes), "상태를 바꾸는 두 부름은 늘 화면 머리글을 붙인다"
    m = re.search(r'const ACTION = \{\s*"([^"]+)":\s*"([^"]+)"\s*\}', req)
    assert m and (m.group(1), m.group(2)) == (cq.ACTION_HEADER, cq.ACTION_VALUE), "머리글 이름 · 값은 서버와 같다"
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
def _req_js() -> str:
    return _js_code(_read(JS_DIR / "collect-requests.js"))


def test_request_labels_come_from_server():
    """TC-CL-09 · 요청 · 작업자 상태 글은 서버가 준 글(`status_label`) 그대로 — 화면은 색(tone)만 고른다. 색 표는 서버의 상태
    열쇠를 모두 안다(서버가 상태를 늘리면 이 시험이 먼저 깨진다) · 화면에 상태 → 한국어 글 짝을 따로 두지 않는다."""
    from app.services import collect_requests as cq

    src = _req_js()
    assert _js_keys(src, "REQ_TONE") == set(cq.STATUS_LABEL)
    assert _js_keys(src, "WORKER_TONE") == set(cq.WORKER_STATES) | {"off", "missing"} == set(cq.WORKER_LABEL)
    assert "r.status_label" in src and "w.status_label" in src
    for label in cq.STATUS_LABEL.values():
        assert not re.search(rf'\w+:\s*"{re.escape(label)}"', src), f"상태 글 「{label}」 을 화면이 다시 짓지 않는다"
    assert "r.wait" in src and "r.result" in src, "기다리는 까닭 · 결과 한 줄도 서버 글 그대로"
    # 화면은 작업자 이름표 앞에 「PC 작업자 」 를 붙인다(띠 · 관제 한 줄 · 확인 창) — 이름표에 「작업자」 가 또 있으면 말이 겹친다
    assert "PC 작업자 ${escHtml(w.status_label" in src and "PC 작업자: ${escHtml(w.status_label" in src
    for state, label in cq.WORKER_LABEL.items():
        assert "작업자" not in label, f"「PC 작업자 {label}」 — {state} 이름표에서 「작업자」 를 뺀다"


def test_blocked_buttons_follow_server_blocked_now():
    """TC-CL-10 · 막는 때에는 단추를 끈다(2026-10-10 결정) — 판정은 서버의 `rules.blocked_now`(전체 · 단계마다 · 끝나는 시각)를
    그대로 쓰고, 화면이 시계로 창을 다시 세지 않는다. 러너가 도는 동안 · 같은 대상이 대기 · 도는 중일 때도 끈다."""
    src = _req_js()
    assert "blocked_now" in src and re.search(r"blocked_now\??\.full", src) and re.search(r"blocked_now\??\.steps", src)
    assert ".until" in src, "꺼진 단추 옆에 끝나는 시각"
    assert not re.search(r"\.(from|to)\s*[<>]=?|[<>]=?\s*\w+\.(from|to)\b", src), "창 시각을 화면이 견주지 않는다"
    assert "new Date().getHours" not in src and "getMinutes()" not in src
    # 두 단추 함수가 그 값으로 실제로 끈다 — 읽기만 하고 쓰지 않으면 이 시험이 잡는다(깨 보기 #13 · 14 · 2026-10-10)
    for fn in ("export function fullButtonHtml", "export function stepActionHtml"):
        body = src[src.index(fn):]
        body = body[:body.index("export function", len(fn))]
        assert re.search(r"else if \(b\?\.blocked\) why =", body), f"{fn} — 막는 때면 까닭을 두고 끈다"
        assert re.search(r"why \? `disabled title=", body), f"{fn} — 까닭이 있으면 disabled"
        assert re.search(r"const b = blockedFor\(", body), f"{fn} — 막는 때는 서버 값(blockedFor)에서"


def test_request_messages_for_server_codes():
    """TC-CL-11 · 누른 뒤 문구 — 새 요청은 「요청했습니다」, 같은 대상이 이미 대기 · 도는 중이면(서버 `created: false`)
    「이미 기다리는 요청이 있습니다」(새 줄 없음), 403 은 「관리자만 요청할 수 있습니다」, 409 · 422 는 서버 글 그대로."""
    src = _req_js()
    assert re.search(r"\.created\b", src)
    assert "요청했습니다" in src and "이미 기다리는 요청이 있습니다" in src
    assert re.search(r"status === 403[^\n]*\n?[^\n]*관리자만 요청할 수 있습니다", src) or (
        "status === 403" in src and "관리자만 요청할 수 있습니다" in src)
    assert re.search(r"err\.message|e\.message", src), "409 · 422 는 서버 글을 그대로 보인다"


def test_polling_5s_while_active_1min_otherwise_stops_off_view():
    """TC-CL-12 · 다시 묻는 간격 — 대기 · 도는 중인 줄이 있거나 대기 창이 열려 있는 동안은 5초, 그 밖에는 1분마다 목록을 다시
    묻는다(작업자 띠의 꺼짐 · 신호와 막는 때의 단추 끄기가 화면을 열어 둔 채로도 1분 안에 따라오게 — 2026-10-10 실측: 요청이 없을 때
    멈추게 했더니 띠가 25분 넘게 「꺼짐」 으로 남았다) · 수집 일정 화면을 떠나면 멈춘다 · 도는 줄이 끝나면 단계 표를 한 번 다시 읽는다."""
    src = _req_js()
    assert re.search(r"const POLL_MS = 5[_]?000;", src)
    assert re.search(r"const IDLE_POLL_MS = 60[_]?000;", src), "요청이 없을 때도 1분마다"
    sched = src[src.index("function schedulePoll"):]
    sched = sched[:sched.index("\n}") + 2]
    assert re.search(r"needPoll\(\) \? POLL_MS : IDLE_POLL_MS", sched), "활성이면 5초 · 아니면 1분 — 멈추지 않는다"
    assert re.search(r"pollTimer = onChange \?", sched), "수집 일정 화면(onChange)이 있을 때만 묻는다"
    assert re.search(r'const ACTIVE = \["queued", "running"\];', src)
    assert "clearTimeout(" in src and "stopRequestPolling" in src
    collect = _js_code(_read(JS_DIR / "collect.js"))
    hook = collect[collect.index("export function onCollectViewActivated"):]
    assert "stopRequestPolling()" in hook, "다른 화면으로 가면 멈춘다"
    assert "onFinished" in src or "finished" in src


def test_wait_modal_from_instructor_base_adapted():
    """TC-CL-13 · 대기 창 — 강사님 기초 코드(lumina-invest 10-08 판)의 대기 창 꼴(모래시계 · 경과 시간)을 가져와 고쳤다(2026-10-10
    결정 ③): 단계 이름 · 경과 · 상태 · 「창 닫기」(요청은 계속) · 대기일 때만 「요청 취소」. app.html 은 건드리지 않고 이 파일이
    창을 만든다 · 움직임 줄이기 설정을 지킨다 · 가져온 곳을 머리말에 적는다."""
    src = _read(JS_DIR / "collect-requests.js")
    code = _js_code(src)
    assert "lumina-invest" in src and "app-loading-modal" in src, "가져온 곳(강사님 대기 창)을 적는다"
    assert "openWaitModal" in code and "cq-wait-modal" in code and "창 닫기" in code and "요청 취소" in code
    assert "cq-wait-modal" not in _read(APP_HTML), "app.html 에 창을 넣지 않는다"
    css = _read(ROOT / "public" / "css" / "collect.css")
    assert ".cq-hourglass" in css and "prefers-reduced-motion" in css[css.index(".cq-hourglass"):]


def test_data_hub_request_line_admin_only():
    """TC-CL-14 · 데이터 관제 — 관리자에게만 수집 요청 한 줄(작업자 상태 · 대기 · 도는 중 수 · 최근 요청 하나 → 수집 일정)
    (2026-10-10 결정 ①: 안 B 의 최신 정보는 관제에). 일반 사용자에게는 칸을 숨기고 요청 API 도 부르지 않는다."""
    hub = _js_code(_read(JS_DIR / "datahub.js"))
    assert 'class="card dh-reqline q-admin-only"' in hub
    assert "renderHubRequestLine" in hub
    src = _req_js()
    fn = src[src.index("export async function renderHubRequestLine"):]
    assert "isCollectAdmin()" in fn[:600], "관리자일 때만 요청 목록 API 를 부른다"
