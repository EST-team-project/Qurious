"""데이터 관제 · 일정 화면 시험 (TC-DH) — 화면 설계 결정(Figma 「데이터 관제 · 금융 일정」 결정 ① ② ③)이 코드에 이어졌나.

화면은 브라우저로 확인했다(2026-10-02 · 1280 · 390 캡처). 여기서는 사람이 놓치기 쉬운 두 가지를 잰다.
1. 연결 — 위 메뉴 「데이터」(옛 크롤링) 맨 위에 데이터 관제, 「투자분석 기초」 에 일정, 화면 칸 · 모양 파일 · 진입 훅 · 사용법.
2. 규약 — 화면이 읽는 응답 칸이 서버 응답에 실제로 있는가. 서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그린다
   (화면 JS 를 고치지 않은 채 응답만 바뀌는 일을 시험이 잡는다). 일정 종류는 결정 ③ 대로 서버의 넷과 같아야 한다.
네트워크 · 실제 수집 DB 없이 돈다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import collector_db, data_status as ds, market_calendar as cal_svc
from collector import market_calendar as mc

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
KST = timezone(timedelta(hours=9))


def _read(rel: str) -> str:
    return (PUB / rel).read_text(encoding="utf-8")


def _js_object_keys(src: str, name: str) -> set[str]:
    """`const NAME = { a: …, "b-c": … }` 의 맨 위 키들(값 안쪽 객체의 키는 세지 않는다)."""
    body = src[src.index(f"const {name} = {{") + len(f"const {name} = {{"):]
    depth, keys, i = 1, set(), 0
    while depth and i < len(body):
        ch = body[i]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif depth == 1:
            m = re.match(r'\s*"?([\w-]+)"?\s*:', body[i:])
            if m and (i == 0 or body[i - 1] in "{,\n "):
                keys.add(m.group(1))
                i += m.end() - 1
        i += 1
    return keys


def test_menu_views_assets_and_hooks_are_wired():
    """TC-DH-01 · 위 메뉴 「데이터」 맨 위 = 데이터 관제 · 「투자분석 기초」 의 일정 · 화면 칸 둘 · 모양 파일 · 진입 훅 · 사용법 · 위 메뉴 표시."""
    core, app, main = _read("js/core.js"), _read("app.html"), _read("js/main.js")
    crawl = core[core.index("  crawl: {"):core.index("  trading: {")]
    assert "데이터" in crawl.split("items")[0] and re.search(r'items: \[\s*\{ key: "data-status"', crawl), "데이터 관제가 「데이터」 맨 위"
    invest = core[core.index("  invest: {"):core.index("  finance: {")]
    assert 'key: "market-calendar"' in invest
    for key in ("data-status", "market-calendar"):
        assert f'data-view="{key}"' in app
        assert f'"{key}":' in core[core.index("const VIEW_GUIDES"):], f"사용법 안내에 {key}"
    assert 'href="/css/datahub.css"' in app and 'data-gnb="crawl"><i class="fa-solid fa-database"></i> 데이터' in app
    assert "initDataBadge()" in main and "onDataHubViewActivated(view)" in main and "onCalendarViewActivated(view)" in main
    assert (PUB / "js" / "datahub.js").is_file() and (PUB / "js" / "calendar.js").is_file()
    # 화면 스캐너가 진입 훅을 읽어야 API 명세서의 「부르는 화면」 칸이 맞다 — 훅을 상수(`view === VIEW`)로 적거나
    # 다른 파일과 같은 함수 이름을 쓰면 스캐너가 놓치거나 섞어 읽는다(2026-10-02 「(다른 곳)」 으로 남았던 일)
    from scripts import view_scan
    entry = {r["key"]: set(r["entry_apis"]) for r in view_scan.scan()["rows"]}
    assert entry["data-status"] == {"/api/data/status"}
    assert entry["market-calendar"] == {"/api/calendar/events", "/api/calendar/trading-days"}


def test_calendar_kinds_match_server_and_decision_3():
    """TC-DH-02 · 일정 종류 — 화면의 넷 = 서버의 넷(결정 ③: 아직 모으지 않는 경제지표 · 실적 · 금통위 · FOMC 의 자리는 두지 않는다)."""
    src = _read("js/calendar.js")
    assert _js_object_keys(src, "KINDS") == set(cal_svc.EVENT_KINDS)
    for word in ("경제지표", "FOMC", "금통위", "실적"):
        assert word not in src.split("const KINDS")[1].split("};")[0]


def test_data_status_fields_read_by_screen_exist(tmp_path, monkeypatch):
    """TC-DH-03 · 데이터 관제 화면 · 서랍 · 위 메뉴 표시가 읽는 칸이 상태 응답에 있다 · 판정 · 러너 상태 · 단계 상태의 색 표가 서버 값을 다 덮는다."""
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))
    ds._cache.clear()
    st = ds.get_status(datetime(2026, 10, 2, 14, 0, tzinfo=KST), use_cache=False)
    for k in ("verdict", "verdict_label", "as_of", "summary", "checked_at", "runner", "tables", "calendar", "hf", "rows_state"):
        assert k in st, k
    for k in ("state", "label", "detail", "next_expected", "history", "last", "running"):
        assert k in st["runner"], k
    for k in ("key", "label", "source", "last_date", "verdict", "verdict_label", "rows", "detail"):
        assert k in st["tables"][0], k
    src = _read("js/datahub.js")
    assert set(ds.VERDICT_LABEL) <= _js_object_keys(src, "VERDICT_CLASS")
    assert {"ok", "warning", "error"} == _js_object_keys(src, "OVERALL")
    assert {"ok", "warning", "failed", "running", "late", "missing"} <= _js_object_keys(src, "RUNNER_CLASS")
    assert {"ok", "warning", "failed", "skipped"} <= _js_object_keys(src, "STEP_MARK")
    # 화면이 읽는 칸 이름이 JS 에 그대로 있다(서버 칸 이름을 바꾸면 이 시험과 화면을 함께 고친다)
    for field in ("st.as_of", "st.verdict", "st.summary", "st.rows_note", "r.next_expected", "r.running_since", "t.last_date", "t.rows", "h.uploaded_at"):
        assert field in src, field


def test_calendar_fields_read_by_screen_exist(tmp_path, monkeypatch):
    """TC-DH-04 · 일정 화면 · 카드 · 설명 창이 읽는 칸이 일정 · 거래일 응답에 있다(수집기 스키마로 만든 작은 DB)."""
    from tests.test_market_calendar import DIVIDENDS, TODAY, fake_fetch, make_db

    path = tmp_path / "market.sqlite3"
    conn = make_db(path, dividends=DIVIDENDS)
    mc.build(conn, today=TODAY, fetcher=fake_fetch, quiet=True)
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(path))
    ev = cal_svc.events(date(2026, 9, 27), date(2026, 10, 31))
    td = cal_svc.trading_days(date(2026, 9, 27), date(2026, 10, 31))
    assert ev["events"] and td["days"]
    for k in ("id", "kind", "date", "weekday", "title", "detail", "symbol", "market", "confidence_label"):
        assert k in ev["events"][0], k
    for k in ("date", "is_trading_day"):
        assert k in td["days"][0], k
    assert "end" in ev["calendar"]
    src = _read("js/calendar.js")
    for field in ("e.confidence_label", "e.weekday", "e.detail", "e.symbol", "day.is_trading_day", "state.calendar?.end"):
        assert field in src, field
    # 보유 종목 카드는 모의계좌 보유 응답의 symbol 앞 6자리를 쓴다
    assert "/api/paper/stocks/positions" in src and "p.symbol" in src
