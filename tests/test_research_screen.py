"""투자 정보 리서치 화면 시험 (TC-RS) — 수집 자료 검색 화면(public/js/research.js · Figma 결정 안 B + C 해석 1 · DF-61).

화면은 브라우저로 확인했다(2026-10-06 · 1280 · 390 · 모든 단추 · 종목 시간표). 여기서는 사람이 놓치기 쉬운 것을 잰다.
1. 연결 — 리서치 칸은 새 화면 뿌리만 · 「AI RAG로 검색」 안내가 사라졌다(DF-61) · 진입 훅 · 강사님 agent.js 의 옛 단추
   묶기는 단추가 없어도 깨지지 않는다(그 아래 크롤링 단추 묶기가 함께 멈추지 않게).
2. 규약 — 화면의 출처 · 주제 · 공시 유형 표가 서버(data_search) · 수집기 이름표(tagging)와 같다 · 화면 → API 상한.
3. 칸 — 화면이 읽는 응답 칸이 실제 검색 응답에 있다(작은 수집 DB 로 지은 색인).
4. 결정 — 처음 차례(낱말이 있으면 관련도순) · 종목을 고르면 시간표(그 종목 전부로 시작) · data-view 속성을 쓰지 않는다.
5. 오류 글 — 서버 detail 이 객체여도 화면 글은 message 다(DF-72 · `common.js` 의 `api` 를 Node 로 돌림).
네트워크 · 실제 수집 DB 없이 돈다.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import data_search as DS
from collector import tagging
from tests.test_data_search_api import _login, env  # noqa: F401 — 작은 수집 DB · 색인 고정물을 빌려 쓴다

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"


def _read(rel: str) -> str:
    return (PUB / rel).read_text(encoding="utf-8")


def _js_list(src: str, name: str) -> list[str]:
    body = re.search(rf"const {name} = \[(.*?)\];", src, re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def test_view_is_wired_and_df61_text_is_gone():
    """TC-RS-01 · 리서치 칸은 새 화면 뿌리만 · 「AI RAG로 검색」 이 없다(DF-61) · 진입 훅 · 강사님 옛 단추 묶기는 단추가 없어도 넘어간다."""
    app, main, agent, src = _read("app.html"), _read("js/main.js"), _read("js/agent.js"), _read("js/research.js")
    block = app[app.index('data-view="agent-news"'):app.index("<!-- ══ 2. 데이터")]
    assert '<div class="rs-root"></div>' in block and 'id="news-search"' not in block
    assert "AI RAG로 검색" not in app and "AI RAG로 검색" not in _read("js/core.js")
    assert 'import { onResearchViewActivated } from "/js/research.js"' in main and "onResearchViewActivated(view)" in main
    assert 'if (view === "agent-news") renderResearch();' in src
    # 옛 단추가 app.html 에서 빠졌으니 강사님 agent.js 의 묶기는 ?. 로 넘어가야 한다(아니면 모듈이 그 줄에서 멈춘다)
    assert 'document.getElementById("news-search")?.addEventListener' in agent
    from scripts import view_scan
    row = next(r for r in view_scan.scan()["rows"] if r["key"] == "agent-news")
    assert row["entry_apis"] == ["/api/data/search"] and row["hook"] == ["renderResearch"]


def test_tables_match_server_and_collector():
    """TC-RS-02 · 출처 셋 = 서버 SOURCES(이름 · 차례) · 주제 = 수집기 이름표 스물하나 · 공시 유형 A~J · 화면 → API 상한."""
    src = _read("js/research.js")
    sources = re.findall(r'^\s+(\w+): \["([^"]+)", "\w+"\],', src[src.index("const SOURCES = {"):src.index("};", src.index("const SOURCES = {"))], re.M)
    assert [k for k, _ in sources] == list(DS.SOURCES) and dict(sources) == DS.SOURCE_LABELS
    topics = _js_list(src, "TOPICS")
    assert sorted(topics) == sorted(t[0] for t in tagging.TOPICS) and len(topics) == len(set(topics)) == 21
    dtypes = re.findall(r"\b([A-J]): \"", src[src.index("const DTYPES = {"):src.index("};", src.index("const DTYPES = {"))])
    assert dtypes == list(DS.DTYPES)
    page = int(re.search(r"const PAGE = (\d+);", src).group(1))
    tl_page = int(re.search(r"const TL_PAGE = (\d+);", src).group(1))
    assert 1 <= page <= DS.MAX_LIMIT and 1 <= tl_page <= DS.MAX_LIMIT
    assert "&limit=${TL_PAGE}" in src and "limit=500" in src                  # 시간표 일정 500 ≤ 일정 API 상한 5000


def test_screen_fields_exist_in_search_response(env):  # noqa: F811
    """TC-RS-03 · 화면이 읽는 칸이 검색 응답에 있다(공시 · 핵심 숫자 · 종류 칸 개수) · 뉴스 출처 표시 칸은 색인이 쓴다."""
    r = DS.search(q="", limit=5, facets=True)
    assert r["items"] and {"total", "total_capped", "facets"} <= set(r)
    assert set(r["facets"]["source"]) == set(DS.SOURCES)
    it = r["items"][0]
    for k in ("doc_id", "kind", "title", "summary", "url", "published", "source", "corp_name", "stock_code", "tags", "extra"):
        assert k in it, k
    assert "pblntf_ty" in it["extra"]
    # 제출인(flr_nm)은 DART 목록에 있을 때만 실린다(시험 고정물엔 없다) — 화면은 없으면 건너뛰고, 색인은 있으면 싣는다
    assert "flr_nm" in (ROOT / "collector" / "search_index.py").read_text(encoding="utf-8")
    div = next(x for x in DS.search(q="배당", limit=5)["items"] if x.get("key_numbers"))
    assert {"dps", "record_date"} <= set(div["key_numbers"])
    rep = next(x for x in DS.search(q="사업보고서", limit=5)["items"] if (x.get("key_numbers") or {}).get("revenue"))
    assert {"revenue", "operating_income", "net_income", "fs_div", "same_filing"} <= set(rep["key_numbers"])
    src = _read("js/research.js")
    for field in ("it.corp_name", "it.stock_code", "it.tags?.symbol", "it.tags?.topic", "ex.pblntf_ty", "ex.flr_nm",
                  "ex.publisher", "ex.attribution", "it.key_numbers", "r.total_capped", "r.facets", "k.dps", "k.record_date",
                  "k.fs_div", "k.same_filing"):
        assert field in src, field
    index_src = (ROOT / "collector" / "search_index.py").read_text(encoding="utf-8")
    assert '"publisher"' in index_src and 'extra["attribution"]' in index_src


def test_decisions_first_order_symbol_timeline_and_attr_names():
    """TC-RS-04 · 결정 — 처음 차례는 낱말이 있으면 관련도순 · 종목을 고르면 시간표(낱말을 비우고 그 종목 전부) · 언론사 기사는
    원문 링크만(본문 없음) · 링크는 http(s) 만 · data-view 속성을 쓰지 않는다(앱이 화면 이름으로 쓴다)."""
    src = _read("js/research.js")
    assert 'function sortNow() { return S.sort || (S.q ? "relevance" : "date"); }' in src
    pick = src[src.index("function pickSymbol"):src.index("// ── 결과")]
    assert 'S.view = "timeline"; S.q = "";' in pick
    assert "function safeUrl(u) { return /^https?:\\/\\//i.test(u || \"\") ? u : \"\"; }" in src
    assert 'rel="noopener noreferrer"' in src
    # 화면 칸을 찾는 `.view[data-view="…"]` 는 괜찮다 — 이 파일이 만드는 단추에 data-view 속성을 달면 안 된다
    # (글자 `data-view=` 로 쓰든, 속성 이름을 인자 `"data-view"` 로 넘기든 — 2026-10-06 깨 보기에서 둘째 꼴을 놓쳤다)
    assert not re.search(r'(?<!\[)\bdata-view=', src), "data-view 는 앱 전체의 화면 이름 속성 — data-rs-view 를 쓴다"
    assert not re.search(r'["\'`]data-view["\'`]', src), "속성 이름 data-view 를 인자로 넘기지 않는다"
    # 화면이 늦게 온 응답을 버린다(조건을 바꾸면 앞 조건의 결과가 덮지 않게)
    assert src.count("if (my !== seq) return;") == 4


def test_api_error_text_from_object_detail(tmp_path):
    """TC-RS-05 · 서버 오류의 detail 이 객체({message, hint})여도 화면 글은 message 다 — 「[object Object]」 가 아니다(DF-72).

    화면 함수(`common.js` 의 `api`)를 그대로 떼어 Node 로 돌린다(TC-LC-09 와 같은 길) — fetch 만 가짜로 바꾼다.
    """
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    src = _read("js/common.js")
    start = src.index("export async function api(")
    fn = src[start:src.index("\n}\n", start) + 3].replace("export async function", "async function", 1)
    cases = [   # (HTTP 상태, 응답 본문) — 검색 색인 503 · 입력 검증 422 · 글 detail · message 없는 객체
        [503, {"detail": {"message": "검색 색인을 읽지 못했습니다", "hint": "색인을 다시 만든다"}}],
        [422, {"detail": [{"msg": "field required"}, {"msg": "too long"}]}],
        [404, {"detail": "없는 종목"}],
        [500, {"detail": {"code": 7}}],
    ]
    script = tmp_path / "api.mjs"
    script.write_text(
        "function redirectToLogin() {}\n" + fn
        + "\nconst cases = " + json.dumps(cases, ensure_ascii=False) + ";\nconst out = [];\n"
        + "for (const [status, body] of cases) {\n"
        + "  globalThis.fetch = async () => ({ status, ok: false, json: async () => body });\n"
        + "  try { await api('/api/x'); out.push(null); }\n"
        + "  catch (e) { out.push([e.message, e.status, e.detail ?? null]); }\n"
        + "}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got[0] == ["검색 색인을 읽지 못했습니다", 503, cases[0][1]["detail"]]   # 화면은 hint 도 e.detail 로 읽을 수 있다
    assert got[1] == ["field required · too long", 422, None]
    assert got[2] == ["없는 종목", 404, None]
    assert got[3][0] == '{"code":7}' and got[3][2] == {"code": 7}
    assert all("[object Object]" not in g[0] for g in got)


def test_clearing_query_shows_latest_right_away():
    """TC-RS-06 · 검색어를 비우면 바로 최신 소식으로(2026-10-08 결정 · DF-86) — 검색 칸의 ✕(search) · 다 지움(input)에서 낱말 조건을
    빼고 차례를 자동으로 되돌려 다시 받는다 · 낱말 없이 검색해도 직접 고른 관련도순을 남기지 않는다 · 다른 거름은 건드리지 않는다."""
    src = _read("js/research.js")
    code = re.sub(r"^\s*//.*$", "", src, flags=re.M)          # 주석 속 글자에 속지 않게
    assert re.search(r'^\s+qInput\.addEventListener\("search",\s*onResearchQueryCleared\)', code, re.M)
    assert re.search(r'^\s+qInput\.addEventListener\("input",\s*onResearchQueryCleared\)', code, re.M)
    assert re.search(r"if \(!qInput\.value\.trim\(\)\) clearResearchQuery\(\)", code)
    body = code[code.index("function clearResearchQuery()"):code.index("function renderResearch()")]
    assert 'S.q = "";' in body and re.search(r'if \(S\.sort === "relevance"\) S\.sort = "";', body) and "reload();" in body
    for other in ("S.source", "S.symbol", "S.topic", "S.period"):
        assert other not in body, f"검색어를 비울 때 {other} 거름은 그대로 둔다"
    submit = code[code.index('addEventListener("submit"'):code.index("const qInput")]
    assert re.search(r'if \(!S\.q && S\.sort === "relevance"\) S\.sort = "";', submit), "낱말 없는 관련도순을 남기지 않는다"
