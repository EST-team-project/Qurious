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
    # 제안 목록에서 고르면 낱말을 비우고 그 종목 전부로(옛 뜻 그대로) — 「검색」 이 낱말 · 종목을 함께 보낼 때만 낱말을 남긴다(2026-10-17)
    assert 'S.view = "timeline";' in pick and re.search(r'if \(!keepQuery\) \{\s*S\.q = "";', pick)
    assert 'pickSymbol(li.dataset.code, li.dataset.name)' in src, "제안 목록에서 고르면 keepQuery 없이"
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


# ── 2026-10-17 · 첫 목록(설계 A) · 종목 칸(세 안 공통) — Figma 「투자 정보 리서치」 03-2 ──────────────────────────────────────
ROWS = PUB / "js" / "researchrows.js"


def _rows_run(tmp_path: Path, body: str):
    """researchrows.js(DOM 없는 판단 모듈)를 Node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
    import json
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "rows.mjs"
    script.write_text(f'import * as rr from "{ROWS.resolve().as_uri()}";\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_same_titles_grouped_and_site_titles_last(tmp_path):
    """TC-RS-07 · 같은 제목은 한 줄로(뉴스만 · 처음 나온 자리에 · 빈칸만 다른 것도) · 공시는 회사마다 같은 보고서 이름이라 묶지 않는다 ·
    제목이 사이트 이름뿐인 기사(서버 site_name_title)는 목록 줄에서 빼 끝에 게시처마다 한 묶음(L11)."""
    out = _rows_run(tmp_path, r"""
const n = (id, title, extra = {}) => ({ doc_id: id, kind: "news", source: "gdelt", title, extra: { publisher: "a.kr", ...extra }, site_name_title: false });
const d = (id, title, corp) => ({ doc_id: id, kind: "disclosure", source: "dart", title, corp_name: corp, extra: {} });
const site = (id) => ({ doc_id: id, kind: "news", source: "gdelt", title: "KBS 뉴스", extra: { publisher: "kbs.co.kr" }, site_name_title: true });
const g = rr.groupResearchRows([
  site("s1"), n("a1", "트럼프 \"현대차, 美 공장에 투자\""), n("b1", "몸값 높아진 원화"), d("x1", "주식등의대량보유상황보고서(일반)", "삼성전자"),
  n("a2", "트럼프  \"현대차, 美 공장에 투자\" ", { publisher: "b.kr" }), d("x2", "주식등의대량보유상황보고서(일반)", "SK하이닉스"),
  site("s2"), { ...n("p1", "몸값 높아진 원화"), source: "policy_news" },
]);
out.rows = g.rows.map(r => [r.it.doc_id, r.same.map(x => x.doc_id)]);
out.sites = g.siteGroups.map(s => [s.title, s.publisher, s.items.map(x => x.doc_id)]);
out.empty = rr.groupResearchRows([]);
""")
    assert out["rows"] == [["a1", ["a2"]], ["b1", ["p1"]], ["x1", []], ["x2", []]]
    assert out["sites"] == [["KBS 뉴스", "kbs.co.kr", ["s1", "s2"]]]
    assert out["empty"] == {"rows": [], "siteGroups": []}


def test_stock_box_resolves_without_waiting(tmp_path):
    """TC-RS-08 · 종목 칸 판단 — 이름(빈칸 · 대소문자 무시) · 코드가 정확히 같은 것 하나면 그 종목 · 여럿이면 목록 · 없으면 「찾지 못함」
    (점검 <표 2> 라 · 마 — 치자마자 Enter · 「검색」 이 종목 칸 글을 버림)."""
    out = _rows_run(tmp_path, r"""
const s = (code, name) => ({ code, name, market: "KOSPI" });
const shinhan = [s("055550", "신한지주"), s("293940", "신한알파리츠"), s("404990", "신한서부티엔디리츠")];
out.exact = rr.resolveStockQuery(shinhan, "신한지주");
out.prefix = rr.resolveStockQuery(shinhan, "신한");
out.code = rr.resolveStockQuery(shinhan, " 055550 ");
out.space = rr.resolveStockQuery([s("005930", "삼성전자"), s("005935", "삼성전자우")], "삼성 전자");
out.upper = rr.resolveStockQuery([s("035420", "NAVER")], "naver");
out.one_not_exact = rr.resolveStockQuery([s("035420", "NAVER")], "네이버");
out.none = rr.resolveStockQuery([], "없는회사");
out.empty = rr.resolveStockQuery(shinhan, "  ");
""")
    assert out["exact"] == {"kind": "pick", "code": "055550", "name": "신한지주"}
    assert out["prefix"] == {"kind": "list"} and out["one_not_exact"] == {"kind": "list"}
    assert out["code"]["code"] == "055550" and out["space"]["code"] == "005930" and out["upper"]["code"] == "035420"
    assert out["none"] == {"kind": "none"} and out["empty"] == {"kind": "empty"}


def test_switch_text_counts_hidden_from_server(tmp_path):
    """TC-RS-09 · 스위치 글 — 숨긴 수는 서버 facets.untagged 의 합(화면이 다시 세지 않는다) · 끄면 「숨김」 · 켜면 「함께」 · 0 이면 감춤."""
    out = _rows_run(tmp_path, r"""
const u = { dart: 0, policy_news: 440, gdelt: 35820 };
out.on = rr.researchSwitchText(true, u);
out.off = rr.researchSwitchText(false, u);
out.zero = rr.researchSwitchText(true, { dart: 0, policy_news: 0, gdelt: 0 });
out.missing = rr.researchSwitchText(true, null);
""")
    assert out["on"] == {"n": 36260, "text": "이름표 없는 기사까지 보기 (36,260건 숨김)"}
    assert out["off"]["text"] == "이름표 없는 기사까지 보기 (36,260건 함께)"
    assert out["zero"]["n"] == 0 and out["missing"]["n"] == 0


def test_first_list_and_stock_box_are_wired():
    """TC-RS-10 · 화면 연결 — 처음은 「투자 관련만」(tagged) · 스위치는 role=switch · aria-checked · 숨긴 수는 응답 facets.untagged ·
    목록은 판단 모듈로 묶음 · 종목 칸은 찾기 줄(낱말 칸 옆 · 사용자 결정 2026-10-17) · Enter 는 제안 목록을 기다리지 않고 「검색」 과 같은
    길 · 「검색」 은 새로 친 종목을 먼저 찾는다 · 거름 칸의 종목 칸은 고른 종목 칩만."""
    src = _read("js/research.js")
    code = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    assert re.search(r'^import \{[^}]*groupResearchRows[^}]*\} from "/js/researchrows\.js";', code, re.M)
    assert re.search(r"tagged: true", code[code.index("const S = {"):code.index("};", code.index("const S = {"))])
    assert re.search(r'if \(S\.tagged\) p\.set\("tagged", "true"\);', code)
    # 스위치 이름이 「이름표 없는 기사까지 보기」 라 켜짐 = 숨긴 기사도 봄(tagged 꺼짐) — aria-checked 는 그 반대 값
    assert "r.facets.untagged" in code and 'role="switch"' in code and 'aria-checked="${!S.tagged}"' in code
    assert "groupResearchRows(S.items)" in code
    bar = code[code.index('<form class="rs-bar"'):code.index("</form>", code.index('<form class="rs-bar"'))]
    assert "rs-q" in bar and "rs-sym-q" in bar and 'class="rs-suggest"' in bar and 'type="submit"' in bar
    filters = code[code.index("function filtersHtml()"):code.index("function paintFilters()")]
    assert "rs-sym-q" not in filters and "rs-sym-chip" in filters, "거름 칸에는 고른 종목 칩만"
    key = code[code.index("function onResearchSymbolKey"):code.index("\n}\n", code.index("function onResearchSymbolKey"))]
    assert 'e.key === "Enter"' in key and "e.preventDefault()" in key and "requestSubmit()" in key
    find = code[code.index("async function findResearchStock"):code.index("\n}\n", code.index("async function findResearchStock"))]
    assert "clearTimeout(suggestTimer)" in find and "resolveStockQuery(" in find
    submit = code[code.index('addEventListener("submit"'):code.index("const qInput")]
    assert re.search(r"await findResearchStock\(symInput, \{ keepQuery: true \}\)", submit)
    # 종목 찾기 API 의 502 는 「국내 목록에 없고 해외 자동완성도 실패」(app/routes/stocks.py) — 국내만 고르는 이 화면에선 「없음」.
    # 그 밖의 오류는 「없음」 으로 덮지 않고 찾기 실패로 알린다(말없는 대체 금지 · 2026-10-17 손 시험에서 찾음)
    fetch = code[code.index("async function fetchResearchStocks"):code.index("\n}\n", code.index("async function fetchResearchStocks"))]
    assert "err?.status === 502 ? [] : null" in fetch
    show = code[code.index("function showResearchSuggest"):code.index("\n}\n", code.index("function showResearchSuggest"))]
    assert "rows === null" in show and "종목 찾기가 잠시 안 됩니다" in show and "국내 상장 종목에서 찾지 못했습니다" in show
    # 「검색」 단추로 연 목록은 초점이 이미 칸 밖이다 — 칸 밖을 누르면 닫는다(초점 잃음만으로는 못 닫음 · 손 시험에서 찾음)
    wire = code[code.index("function wireResearchBar"):code.index("\n}\n", code.index("function wireResearchBar"))]
    assert re.search(r'document\.addEventListener\("click", e => \{ if \(!box\.contains\(e\.target\)\) hideResearchSuggest\(input\); \}\)', wire)
