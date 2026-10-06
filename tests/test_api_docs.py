"""API 문서 화면 시험 (TC-AD) — 시스템관리 서랍 「API 문서」(public/api-docs/ · 2026-10-06).

화면은 브라우저로 확인했다(2026-10-06 · 1440 · 390 · 찾기 · 거름 · 자세히 · 시험 호출 · 쓰기 막기). 여기서는 사람이 놓치기 쉬운 것을 잰다.
1. 연결 — 서랍 칸(href) · 앱의 마운트 · 자원 판(?v=) · Swagger 자원이 FastAPI 기본 /docs 와 같은 것 · 기본은 읽기만 시험 호출.
2. 카탈로그 — scripts/api_scan.py --catalog 가 만드는 칸 · 실은 파일의 모양(바뀌는 칸이 없어 코드가 같으면 바이트가 같다).
3. 순수 함수 — 명세 + 카탈로그 잇기(한쪽에만 있는 것도 남김) · 거름 · Swagger 에 넘길 오퍼레이션 하나 · 주소 # 읽기.
   화면 파일(api-docs-core.js)을 그대로 Node 로 돌린다 — 파이썬으로 다시 쓰면 고친 곳을 시험하지 못한다(TC-LC-09 와 같은 길).
카탈로그가 지금 코드와 같은지는 시험으로 막지 않는다 — 팀원이 라우트를 더한 PR 이 실패하게 된다(TC-CP 와 같은 까닭).
뒤처졌는지는 `python scripts/api_scan.py --catalog public/api-docs/catalog.json --check` 와 점검(check.ps1 시스템)으로 본다.
4. 그 검사(`--check`)는 줄 끝을 접어 견준다 — core.autocrlf 작업 트리는 체크아웃 때 CRLF 로 바꿔 써서, 바이트 그대로면
   코드가 같아도 머지 · 브랜치 전환 뒤 늘 「뒤처졌다」 가 됐다(DF-77).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
DOCS = PUB / "api-docs"


def _read(rel: str) -> str:
    return (PUB / rel).read_text(encoding="utf-8")


def test_menu_mount_assets_and_read_only_default():
    """TC-AD-01 · 서랍 칸이 /api-docs/ 로 · 앱이 그 폴더를 붙임 · 자원 판이 같음 · Swagger 자원 = FastAPI /docs · 기본은 GET 만."""
    core = _read("js/core.js")
    block = core[core.index("sysadmin: {"):core.index("account: {")]
    assert re.search(r'key: "sysadmin-api",.*href: "/api-docs/"', block), "시스템관리 서랍에 API 문서 칸(href)이 없다"
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    # 줄 머리부터 맞춘다 — 글자만 찾으면 주석으로 막은 줄(`pass  # app.mount(...)`)도 통과한다(2026-10-06 깨 보기에서 놓침)
    assert re.search(r'^\s+app\.mount\("/api-docs", _RevalidateHtml\(directory=os\.path\.join\(_public, "api-docs"\), html=True',
                     main, re.M), "앱이 /api-docs 폴더를 붙이지 않는다"
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    js = (DOCS / "api-docs.js").read_text(encoding="utf-8")
    vers = set(re.findall(r'api-docs(?:-core)?\.(?:css|js)\?v=(\w+)', html + js))
    assert len(vers) == 1, f"자원 판 글자가 섞였다 — {vers}"
    assert 'id="api-docs-css"' in html and 'getElementById("api-docs-css")' in js   # Swagger CSS 를 우리 CSS 앞에 끼운다
    from fastapi.openapi import docs as fdocs
    import inspect
    swagger = set(re.findall(r"https://cdn\.jsdelivr\.net/npm/swagger-ui-dist@\d+/swagger-ui[\w.-]+", inspect.getsource(fdocs)))
    used = set(re.findall(r"https://cdn\.jsdelivr\.net/npm/swagger-ui-dist@\d+/swagger-ui[\w.-]+", js))
    assert used and used <= swagger, f"FastAPI /docs 와 다른 Swagger 자원 — {used - swagger}"
    # 시험 호출은 로그인 쿠키로 실제로 실행된다 → 처음엔 읽기만, 같은 출처 쿠키로
    assert "allowWrite: false" in js and "supportedSubmitMethods: submitMethods(S.allowWrite)" in js
    assert 'req.credentials = "same-origin"' in js


def test_catalog_fields_and_committed_file_shape():
    """TC-AD-02 · 카탈로그 = 스캐너 칸의 짧은 이름 · 바뀌는 칸(시각) 없음 · 실은 파일은 같은 모양 · (메서드, 경로) 겹침 없음."""
    import scripts.api_scan as scan
    _cb, routes, _reg = scan.scan(scan.ROOT)
    scan.attach_screens(routes, scan.ROOT)
    made = scan.catalog(routes)
    keys = [short for short, _ in scan.CATALOG_FIELDS]
    assert made["count"] == len(routes) and made["routes"] and list(made["routes"][0]) == keys
    assert scan.catalog_json(routes) == scan.catalog_json(routes)            # 같은 코드면 같은 바이트(시각 칸 없음)
    assert set(made) == {"schema", "source", "count", "routers", "routes"}   # 맨 위에 만든 시각 같은 바뀌는 칸이 없다
    saved = json.loads((DOCS / "catalog.json").read_text(encoding="utf-8"))
    assert saved["schema"] == 1 and saved["count"] == len(saved["routes"]) > 100
    pairs = [(r["method"], r["path"]) for r in saved["routes"]]
    assert len(pairs) == len(set(pairs)), "같은 메서드 · 경로가 두 번"
    for r in saved["routes"]:
        assert list(r) == keys and re.fullmatch(r"API-[A-Z]+-\d+", r["id"]), r



def test_catalog_check_folds_line_endings(tmp_path):
    """TC-AD-04 · 카탈로그 검사는 줄 끝을 접어 견준다 — CRLF 로 체크아웃된 파일도 코드가 같으면 통과 · 내용이 다르면 실패(DF-77)."""
    import scripts.api_scan as scan
    _cb, routes, _reg = scan.scan(scan.ROOT)
    scan.attach_screens(routes, scan.ROOT)
    made = scan.catalog_json(routes)
    crlf = tmp_path / "catalog.json"
    crlf.write_bytes(made.replace("\n", "\r\n").encode("utf-8"))
    assert scan.main(["--catalog", str(crlf), "--check"]) == 0
    stale = tmp_path / "stale.json"
    stale.write_bytes(made.replace('"count"', '"count_old"', 1).encode("utf-8"))
    assert scan.main(["--catalog", str(stale), "--check"]) == 1

NODE_CASES = r"""
import * as C from "__CORE__";
const out = {};
const spec = { openapi: "3.1.0", info: { title: "t", version: "1" }, components: { schemas: { AskBody: { type: "object" } } },
  paths: {
    "/api/kb/ask": { post: { summary: "Kb Ask", description: "근거 번호가 달린 답\n둘째 줄", operationId: "kb_ask", tags: ["kb"],
      requestBody: { content: { "application/json": { schema: { $ref: "#/components/schemas/AskBody" } } } } } },
    "/api/kb/search": { get: { summary: "Kb Search", description: "**근거** 청크 `찾기`", operationId: "kb_search" } },
    "/api/x/{id}": { parameters: [{ name: "id", in: "path" }], delete: { summary: "X", operationId: "x_del" } },
    "/api/new": { get: { summary: "New Route", operationId: "new_get" } },
  } };
const catalog = { count: 4, routes: [
  { id: "API-KB-02", router: "kb", method: "GET", path: "/api/kb/search", summary: "", auth: "세션", screens: ["agent-chat"] },
  { id: "API-KB-03", router: "kb", method: "POST", path: "/api/kb/ask", summary: "", auth: "세션·JWT", screens: [] },
  { id: "API-X-01", router: "x", method: "DELETE", path: "/api/x/{id}", summary: "엑스 지우기", auth: "세션 + 관리자", screens: [] },
  { id: "API-OA-09", router: "openapi", method: "GET", path: "/openapi/v1/docs-summary", summary: "", auth: "없음", screens: [] },
] };
const rows = C.mergeOps(spec, catalog);
out.keys = rows.map(r => r.key);
out.flags = rows.map(r => [r.key, r.inSpec, Boolean(r.cat)]);
out.titles = Object.fromEntries(rows.map(r => [r.key, r.title]));
const f = o => C.filterOps(rows, o).map(r => r.key);
out.f = {
  words: f({ q: "kb 찾기" }), fold: f({ q: "근거청크" }), id: f({ q: "api-x-01" }), none: f({ q: "kb 없음xyz" }),
  method: f({ methods: new Set(["DELETE"]) }), admin: f({ auth: "admin" }), open: f({ auth: "none" }),
  session: f({ auth: "session" }), screens: f({ screensOnly: true }), router: f({ router: "kb" }),
  screenWord: f({ q: "agent-chat" }),
};
out.groups = C.groupByRouter(rows).map(([k, v]) => [k, v.length]);
const one = C.oneOpSpec(spec, "/api/x/{id}", "DELETE");
out.one = { paths: Object.keys(one.paths), methods: Object.keys(one.paths["/api/x/{id}"]), comps: Object.keys(one.components.schemas) };
out.oneMissing = C.oneOpSpec(spec, "/api/kb/search", "POST");
out.submit = [C.submitMethods(false), C.submitMethods(true)];
out.hash = [C.hashToKey(C.keyToHash("GET /api/kb/search")), C.hashToKey("#javascript%3Aalert(1)"), C.hashToKey("#%E0%A4%A"), C.hashToKey("")];
out.deep = [C.swaggerDeepLink(spec.paths["/api/kb/ask"].post), C.swaggerDeepLink(spec.paths["/api/new"].get), C.swaggerDeepLink(null)];
out.auth = ["없음", "세션", "세션·JWT", "API 키", "세션 + 관리자", "세션·JWT + 역할(admin·user)", "", "모름"].map(C.authGroup);
out.stats = C.stats(rows);
process.stdout.write(JSON.stringify(out));
"""


def _run_core(tmp_path: Path, core: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "case.mjs"
    script.write_text(NODE_CASES.replace("__CORE__", core.resolve().as_uri()), encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_core_merge_filter_one_op_and_hash(tmp_path):
    """TC-AD-03 · 명세 + 카탈로그 잇기(카탈로그 차례 · 한쪽에만 있는 것도 남김) · 거름 · Swagger 한 오퍼레이션 · 주소 # · 쓰기 막기."""
    out = _run_core(tmp_path, DOCS / "api-docs-core.js")
    # 차례 — 카탈로그 차례, 명세에만 있는 것(/api/new)은 끝, 카탈로그에만 있는 것(docs-summary)도 남는다
    assert out["keys"] == ["GET /api/kb/search", "POST /api/kb/ask", "DELETE /api/x/{id}", "GET /openapi/v1/docs-summary", "GET /api/new"]
    assert ["GET /openapi/v1/docs-summary", False, True] in out["flags"] and ["GET /api/new", True, False] in out["flags"]
    # 제목 — 우리 summary → docstring 첫 줄(마크다운 표시 뺌) → FastAPI summary
    assert out["titles"]["POST /api/kb/ask"] == "근거 번호가 달린 답"
    assert out["titles"]["GET /api/kb/search"] == "근거 청크 찾기"
    assert out["titles"]["DELETE /api/x/{id}"] == "엑스 지우기" and out["titles"]["GET /api/new"] == "New Route"
    f = out["f"]
    assert f["words"] == ["GET /api/kb/search"]                      # 낱말 둘 다(AND)
    assert f["fold"] == ["GET /api/kb/search"]                       # 띄어쓰기를 접어 찾음
    assert f["id"] == ["DELETE /api/x/{id}"] and f["none"] == []
    assert f["method"] == ["DELETE /api/x/{id}"]
    assert f["admin"] == ["DELETE /api/x/{id}"] and f["open"] == ["GET /openapi/v1/docs-summary"]
    assert f["session"] == ["GET /api/kb/search", "POST /api/kb/ask"]
    assert f["screens"] == ["GET /api/kb/search"] and f["screenWord"] == ["GET /api/kb/search"]
    assert f["router"] == ["GET /api/kb/search", "POST /api/kb/ask"]
    assert out["groups"][0] == ["kb", 2]
    # Swagger 에 넘기는 명세 — 그 오퍼레이션 하나 + 경로 공통 인자 + 스키마 그대로
    assert out["one"] == {"paths": ["/api/x/{id}"], "methods": ["delete", "parameters"], "comps": ["AskBody"]}
    assert out["oneMissing"] is None
    assert out["submit"] == [["get"], ["get", "post", "put", "patch", "delete"]]
    assert out["hash"] == ["GET /api/kb/search", "", "", ""]          # 꼴이 아닌 #(스크립트 · 깨진 글)은 버린다
    assert out["deep"] == ["/docs#/kb/kb_ask", "/docs#/default/new_get", "/docs"]
    assert out["auth"] == ["none", "session", "session", "apikey", "admin", "admin", "", "other"]
    assert out["stats"] == {"total": 5, "inSpec": 4, "both": 3, "specOnly": 1, "catOnly": 1, "screens": 1}
