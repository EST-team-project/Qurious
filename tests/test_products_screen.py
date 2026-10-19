"""TC-PD — 투자 성향별 상품 안내 화면(public/js/products.js) · 2026-10-12

무엇을 지키나
1. 화면이 읽는 칸이 서버 응답에 있다 — products.js 가 「변수.칸」 으로 읽는 곳을 모두 모아 응답과 맞댄다(TC-DG-04 꼴).
   서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그리므로 시험이 먼저 깨지게. (TC-PD-01)
2. 규제 숫자를 화면에 따로 적지 않는다 — 사전교육 시간 · 기본예탁금 · 시행일은 응답(요건 상수표 한 곳)에서만 온다. (TC-PD-02)
3. 연결 — app.html 뿌리 칸 · 스타일 · main.js 부르는 줄 · 메뉴 이름 · 옛 단추 가드(옛 칸이 없어도 agent.js 가 멈추지 않게) ·
   화면 스캐너가 읽는 진입 훅 꼴. (TC-PD-03)
4. 자산 배분은 읽기만 — 비중표를 화면에 복제하지 않고, 무거운 배분 계산(POST)은 부르지 않는다. 비중 판단은
   js/productweights.js 한 곳이고 화면에 들어올 때 저절로 부른다. 성향 · 비중을 브라우저 저장소에 쓰지 않는다. (TC-PD-04)
5. #179 계약 그대로 고른다 — 서버 라우트가 실제로 낸 응답(저장본 · 기본 비중)을 node 로 판단 함수에 먹인다:
   저장본 먼저 · 404 일 때만 기본 비중 · 그 밖 오류(0 · 401 · 500 · 상태 없는 오류)는 메우지 않고 까닭 ·
   handoff 가 null 이어도 비중 · 성향이 다르면 저장본 + 다시 계산 안내. (TC-PD-05 · 2026-10-16)
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import fss_products as fp
from app.services import product_etfs as pe
from tests.test_fss_products import ANNUITY_PAGE1, DEPOSIT_PAGE1, FAKE_KEY, _transport
from tests.test_product_etfs import _make_db

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
JS = PUB / "js" / "products.js"
JSW = PUB / "js" / "productweights.js"          # 비중 고르기(#179 계약) — 응답 al · sa 는 여기서 읽는다
#: products.js 머리말의 변수 이름 규칙과 같다 — 객체마다 이름 하나
JS_READ = re.compile(r"(?<![\w.])(ov|ls|it|cls|grp|dv|rq|sv|p|rt|al|sa)((?:\??\.[A-Za-z_]\w*)+)")


def _screen_src() -> str:
    return JS.read_text(encoding="utf-8") + "\n" + JSW.read_text(encoding="utf-8")

#: 적금 한 쪽 — 이자 줄에 적립 방식(rsrv_type_nm)이 붙는다(예금에는 없다)
SAVING_PAGE1 = {"result": {
    "prdt_div": "S", "total_count": "1", "max_page_no": "1", "now_page_no": "1", "err_cd": "000", "err_msg": "정상",
    "baseList": [
        {"dcls_month": "202610", "fin_co_no": "0010001", "fin_prdt_cd": "S1", "kor_co_nm": "가나은행", "fin_prdt_nm": "가나 적금",
         "join_way": "스마트폰", "mtrt_int": "", "spcl_cnd": "자동이체 0.1%p", "join_deny": "1", "join_member": "개인",
         "etc_note": "", "max_limit": None, "dcls_strt_day": "20261001", "dcls_end_day": None, "fin_co_subm_day": "202610011000"}],
    "optionList": [
        {"dcls_month": "202610", "fin_co_no": "0010001", "fin_prdt_cd": "S1", "intr_rate_type": "S", "intr_rate_type_nm": "단리",
         "rsrv_type": "S", "rsrv_type_nm": "정액적립식", "save_trm": "12", "intr_rate": 3.2, "intr_rate2": 3.6}],
}}


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    _make_db(p)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    pe.clear_cache()
    yield p
    pe.clear_cache()


def _fss(kind: str, page: dict | None) -> dict:
    key = FAKE_KEY if page is not None else ""
    return asyncio.run(fp.search(kind=kind, sector="bank", term=12, api_key=key, transport=_transport({1: page} if page else None)))


def _allocation_keys() -> set[str]:
    """상품 화면이 사용하는 가벼운 비중 API의 실제 응답 계약."""
    from app.routes.ml import robo_weights
    return set(asyncio.run(robo_weights("moderate", 3, {"id": "test"})))


def _weights_response(risk: str = "moderate", horizon: int = 3) -> dict:
    """기본 비중 라우트(API-ML-11)가 실제로 내는 응답 — 응답 모델을 거친 꼴."""
    from app.routes import ml
    return ml.AllocationWeightsResponse.model_validate(
        asyncio.run(ml.robo_weights(risk, horizon, {"id": "test"}))).model_dump(mode="json")


def _latest_response(monkeypatch, *, risk: str = "moderate", symbols=("005930.KS", "000660.KS")) -> dict:
    """저장본 라우트(API-ML-12)가 실제로 내는 응답 — 저장소 읽기만 갈아 끼우고 넘김(handoff) 계산 · 응답 모델은 그대로.

    symbols 에 국내 종목이 아닌 것(AAPL)이 섞이면 넘김 계산이 거절해 handoff 가 null 이 된다(계약 4 — 그래도 비중은 읽는다)."""
    from app.routes import ml
    from app.services.asset_allocation import asset_allocation
    result = {"risk_profile": risk, "horizon_years": 3, "allocations": asset_allocation(risk, 3),
              "optimization": {"weights": {s: round(1 / len(symbols), 4) for s in symbols}},
              "stock_picks": [{"code": s, "name": s} for s in symbols], "amount_manwon": 5000}

    async def fake_load(db, user_id):
        return {"id": "r-1", "saved_at": "2026-10-15T14:32:05.123456+09:00", "result": dict(result)}

    monkeypatch.setattr(ml, "load_result", fake_load)
    raw = asyncio.run(ml.latest_allocation({"id": "u-1"}, None))
    return ml.LatestAllocationResponse.model_validate(raw).model_dump(mode="json")


def _merged(objs: list[dict]) -> dict:
    out: dict = {}
    for obj in objs:
        for k, v in obj.items():
            if out.get(k) is None:
                out[k] = v
    return out


def _missing(obj, chain: tuple[str, ...]) -> str | None:
    for key in chain:
        if not isinstance(obj, dict):
            return None          # 목록 · 글자에 붙은 것(.map · .length · .join)은 JS 의 것이라 멈춘다
        if key not in obj:
            return key
        obj = obj[key]
    return None


def test_screen_reads_only_fields_the_server_sends(db, monkeypatch):
    """TC-PD-01 · products.js + productweights.js 를 함께 모은다(al · sa 는 비중 고르기 파일에서 읽는다)"""
    ov = pe.overview(per_group=50)
    ls = pe.list_etfs(limit=200)
    dep, sav, ann = _fss("deposit", DEPOSIT_PAGE1), _fss("saving", SAVING_PAGE1), _fss("annuity", ANNUITY_PAGE1)
    assert dep["status"] == sav["status"] == ann["status"] == "ok"
    no_key = _fss("deposit", None)
    err = {**no_key, "admin_detail": fp.ADMIN_DETAIL.get(no_key["status"], "")}   # 라우트가 관리자에게 붙이는 칸
    products = dep["items"] + sav["items"] + ann["items"]
    objs = {
        "ov": [ov], "ls": [ls], "it": [it for g in ov["derivatives"]["groups"] for it in g["items"]] + ls["items"],
        "cls": ov["classes"], "grp": [g for c in ov["classes"] for g in c["groups"]] + ov["derivatives"]["groups"],
        "dv": [ov["derivatives"]], "rq": list(ov["requirements"]["items"].values()),
        "sv": [dep, sav, ann, err], "p": products, "rt": [p["rate"] for p in products if p["rate"]],
        "al": [dict.fromkeys(_allocation_keys())],
        "sa": [_latest_response(monkeypatch)],
    }
    src = _screen_src()
    reads = {(m.group(1), tuple(re.findall(r"[A-Za-z_]\w*", m.group(2)))) for m in JS_READ.finditer(src)}
    assert len(reads) > 60, "화면이 읽는 칸을 거의 못 모았다 — 변수 이름 규칙(products.js 머리말)을 볼 것"
    assert {v for v, _ in reads} == set(objs), "변수 이름 규칙의 이름이 모두 쓰여야 한다(안 쓰는 이름은 머리말에서 뺀다)"
    missing = []
    for var, chain in sorted(reads):
        assert objs[var], f"시험 자료에 {var} 줄이 없다 — 맞대 볼 수 없다"
        miss = _missing(_merged(objs[var]), chain)
        if miss:
            missing.append(f"{var}.{'.'.join(chain)} — 응답에 「{miss}」 칸이 없다")
    assert missing == []


def test_no_requirement_numbers_in_screen():
    """TC-PD-02 · 규제 숫자는 상수표 한 곳 — 화면 글에 따로 적으면 규제가 바뀔 때 한쪽만 고쳐진다."""
    src = JS.read_text(encoding="utf-8")
    for bad in ("1,000만", "3,000만", "10000000", "30000000", "10_000_000", "30_000_000", "2020-09-07", "2026-07-31",
                "사전교육 1시간", "사전교육 2시간"):
        assert bad not in src, bad


def test_wiring():
    """TC-PD-03"""
    html = (PUB / "app.html").read_text(encoding="utf-8")
    assert '<div class="view" data-view="agent-products"><div class="pd-root"></div></div>' in html
    assert '<link rel="stylesheet" href="/css/products.css" />' in html
    assert 'id="bank-search"' not in html and 'id="product-results"' not in html          # 옛 칸은 뺐다
    main = (PUB / "js" / "main.js").read_text(encoding="utf-8")
    assert 'import { onProductsViewActivated } from "/js/products.js";' in main
    assert "  onProductsViewActivated(view);" in main
    core = (PUB / "js" / "core.js").read_text(encoding="utf-8")
    assert 'key: "agent-products",  icon: "fa-solid fa-coins",                 label: "투자 성향별 상품 안내"' in core
    agent = (PUB / "js" / "agent.js").read_text(encoding="utf-8")
    for bid in ("bank-search", "fund-search"):                 # 옛 칸이 없으면 묶지 않는다 — 없으면 agent.js 모듈이 여기서 멈춘다
        assert f'document.getElementById("{bid}")?.addEventListener' in agent
    src = JS.read_text(encoding="utf-8")
    assert 'if (view !== "agent-products") return;' in src      # 화면 스캐너(scripts/view_scan.py)가 읽는 진입 훅 꼴


def test_allocation_is_read_only():
    """TC-PD-04 · 비중표 복제 없음 · 무거운 계산(POST) 없음 · 판단은 productweights.js 한 곳 · 브라우저에 쓰지 않음"""
    screen, pick = JS.read_text(encoding="utf-8"), JSW.read_text(encoding="utf-8")
    src = screen + "\n" + pick
    assert not re.search(r"(국내주식|해외주식|국내채권|대체자산|현금)[\"']?\s*:\s*\d", src), "비중표를 화면에 복제하지 않는다"
    assert '"/api/ml/robo/allocation"' not in src and "method:" not in pick, "배분 계산(POST)은 자산 배분 화면 몫"
    # 두 GET 은 판단 파일에만 한 번씩 — 화면 파일이 따로 부르면 404 판단이 두 벌이 된다(SSoT)
    assert pick.count('api("/api/ml/robo/allocation/latest")') == 1 and pick.count("api(`/api/ml/robo/weights?") == 1
    assert "/api/ml/robo/" not in screen.split("*/", 1)[1], "화면 파일은 비중 API 를 직접 부르지 않는다"
    assert "import" not in pick.split("*/", 1)[1] and "document" not in pick.split("*/", 1)[1], "판단 파일은 DOM · import 없이(node 시험)"
    assert "resolveWeights(api, readProfile())" in screen
    # 화면에 들어올 때 저절로 + 못 읽었을 때 「다시 불러오기」 단추 — 그 밖에서 부르지 않는다
    calls = [ln.strip() for ln in screen.splitlines() if "loadWeights()" in ln and "function loadWeights" not in ln]
    assert sorted(calls) == sorted(['if (d.act === "weights") { loadWeights(); return; }', "loadWeights();"]), calls
    assert "e?.status !== 404" in pick, "404 일 때만 기본 비중으로 — 그 밖 오류는 메우지 않는다"
    for store in ("localStorage.setItem", "sessionStorage.setItem", "sessionStorage.getItem", "pd_weights_v1"):
        assert store not in src, store            # 받은 비중을 브라우저에 남기지 않는다(같은 탭 다른 사용자)
    assert 'import { readRiskProfile as readProfile } from "/js/riskprofile.js"' in screen
    assert 'localStorage.getItem("robo_risk_profile")' not in screen


#: node 로 돌릴 경우 — 가짜 api 는 부른 길을 적고, 시나리오에 없는 길(무거운 POST 등)을 부르면 599 로 던진다
NODE_WEIGHTS = r"""
import { resolveWeights, DEFAULT_HORIZON_YEARS } from "__PW__";
const SA = __SA__, SA_NOHANDOFF = __SA2__, AL = __AL__;
const L = "/api/ml/robo/allocation/latest";
function fake(script) {
  const calls = [];
  const api = async (path, opts) => {
    calls.push([path, (opts && opts.method) || "GET"]);
    const key = path.startsWith("/api/ml/robo/weights?") ? "weights" : path;
    const r = script[key];
    if (!r) throw Object.assign(new Error("예상 밖 호출 " + path), { status: 599 });
    if (r.plain) throw new TypeError("상태 없는 오류");
    if (r.ok) return JSON.parse(JSON.stringify(r.ok));
    throw Object.assign(new Error(r.message || "오류"), { status: r.status });
  };
  return { api, calls };
}
const cases = {
  saved_same:      [{ [L]: { ok: SA } }, { risk_profile: SA.result.risk_profile, level: "위험중립형" }],
  saved_nohandoff: [{ [L]: { ok: SA_NOHANDOFF } }, null],
  saved_differs:   [{ [L]: { ok: SA } }, { risk_profile: "aggressive", level: "공격투자형" }],
  none_404:        [{ [L]: { status: 404, message: "저장된 배분 결과가 없습니다." } }, null],
  default_404:     [{ [L]: { status: 404, message: "저장된 배분 결과가 없습니다." }, weights: { ok: AL } }, { risk_profile: "aggressive" }],
  net_0:           [{ [L]: { status: 0, message: "서버에 연결할 수 없습니다." }, weights: { ok: AL } }, { risk_profile: "moderate" }],
  auth_401:        [{ [L]: { status: 401, message: "로그인이 필요합니다." }, weights: { ok: AL } }, { risk_profile: "moderate" }],
  server_500:      [{ [L]: { status: 500, message: "서버 오류 (HTTP 500)" }, weights: { ok: AL } }, { risk_profile: "moderate" }],
  plain_error:     [{ [L]: { plain: true }, weights: { ok: AL } }, { risk_profile: "moderate" }],
  default_fails:   [{ [L]: { status: 404 }, weights: { status: 503, message: "잠시 뒤 다시" } }, { risk_profile: "moderate" }],
};
const out = { horizon: DEFAULT_HORIZON_YEARS };
for (const [name, [script, profile]] of Object.entries(cases)) {
  const f = fake(script);
  out[name] = { res: await resolveWeights(f.api, profile), calls: f.calls };
}
process.stdout.write(JSON.stringify(out));
"""


def _run_weights(tmp_path: Path, sa: dict, sa2: dict, al: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "weights.mjs"
    script.write_text(NODE_WEIGHTS.replace("__PW__", JSW.resolve().as_uri())
                      .replace("__SA2__", json.dumps(sa2, ensure_ascii=False))
                      .replace("__SA__", json.dumps(sa, ensure_ascii=False))
                      .replace("__AL__", json.dumps(al, ensure_ascii=False)), encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_weights_follow_issue_179_contract(tmp_path, monkeypatch):
    """TC-PD-05 · 서버가 실제로 낸 응답으로 — 저장본 먼저 · 404 만 기본 비중 · 그 밖 오류는 메우지 않음 · handoff null 도 비중"""
    sa = _latest_response(monkeypatch, risk="moderate")
    sa2 = _latest_response(monkeypatch, risk="moderate", symbols=("005930.KS", "AAPL"))
    assert sa["handoff"] is not None and sa2["handoff"] is None, "시험 자료 — 넘김이 되는 저장본 · 안 되는 저장본"
    al = _weights_response("aggressive", 3)
    out = _run_weights(tmp_path, sa, sa2, al)
    L = "/api/ml/robo/allocation/latest"
    only_latest = [[L, "GET"]]
    weights_path = "/api/ml/robo/weights?risk_profile=aggressive&horizon_years=3"

    # 1 · 4 · 5 — 저장본이 있으면 그것만(기본 비중을 부르지 않는다) · 넘김이 null 이어도 비중 · 성향 다름은 표시만
    for name, differs in (("saved_same", False), ("saved_nohandoff", False), ("saved_differs", True)):
        res, calls = out[name]["res"], out[name]["calls"]
        assert calls == only_latest, (name, calls)
        assert res["state"] == "ok" and res["source"] == "saved" and res["differs"] is differs, (name, res)
        assert res["allocations"] == sa["result"]["allocations"] and res["saved_at"] == sa["saved_at"]
        assert res["risk_profile"] == "moderate" and res["horizon_years"] == 3

    # 2 — 404 일 때만 기본 비중(진단 성향 · 3년) · 진단 성향도 없으면 부르지 않고 「none」
    assert out["none_404"] == {"res": {"state": "none"}, "calls": only_latest}
    res = out["default_404"]["res"]
    assert out["default_404"]["calls"] == [[L, "GET"], [weights_path, "GET"]]
    assert res == {"state": "ok", "source": "default", "saved_at": None, "risk_profile": "aggressive", "horizon_years": 3,
                   "allocations": al["allocations"], "differs": False}
    assert out["horizon"] == 3

    # 3 — 그 밖 오류는 「저장본 없음」 이 아니다: 기본 비중을 부르지 않고 까닭(상태 번호 · 글)을 그대로
    for name, status, message in (("net_0", 0, "서버에 연결할 수 없습니다."), ("auth_401", 401, "로그인이 필요합니다."),
                                  ("server_500", 500, "서버 오류 (HTTP 500)"), ("plain_error", None, "상태 없는 오류")):
        assert out[name]["calls"] == only_latest, (name, out[name]["calls"])
        assert out[name]["res"] == {"state": "error", "step": "saved", "status": status, "message": message}, name
    # 기본 비중이 실패해도 메우지 않는다
    assert out["default_fails"]["res"] == {"state": "error", "step": "default", "status": 503, "message": "잠시 뒤 다시"}

    # 무거운 배분 계산(POST)은 어느 경우에도 부르지 않는다
    assert all(method == "GET" for case in out.values() if isinstance(case, dict) for _, method in case["calls"])


#: products.js 를 그대로 node 에 올린다 — import 넷 가운데 셋(common · core · productchart)은 가짜로, 비중 고르기는 진짜 파일로.
#: 문서 객체는 뿌리 칸 하나 · 성향 고르기 글(#robo-risk option)만 흉내 낸다. 브라우저 저장소에 쓰면 writes 에 남는다.
NODE_SCREEN = r"""
const SC = __SC__;
const LBL = { conservative: "보수적 (안정추구형)", moderate: "중립 (위험중립형)", aggressive: "공격적 (수익추구형)" };
const writes = [];
__ESC__
__FMT__
function setup(scn) {
  const handlers = {};
  const root = { innerHTML: "", contains: () => true, addEventListener: (t, f) => { handlers[t] = f; }, querySelector: () => null };
  const calls = [];
  globalThis.document = { querySelector: (sel) => {
    if (sel.includes("pd-root")) return root;
    const m = sel.match(/^#robo-risk option\[value="(.*)"\]$/);
    return m && LBL[m[1]] ? { textContent: " " + LBL[m[1]] + " " } : null;
  } };
  globalThis.CSS = { escape: (s) => String(s) };
  globalThis.localStorage = { getItem: (k) => (k === "robo_risk_profile:v1:test-account" && scn.profile ? JSON.stringify({...scn.profile, score: scn.profile.risk_profile === "aggressive" ? 35 : 7}) : null),
                              setItem: (k) => writes.push(["localStorage", k]) };
  globalThis.sessionStorage = { getItem: (k) => { writes.push(["sessionStorage.get", k]); return null; },
                                setItem: (k) => writes.push(["sessionStorage", k]) };
  globalThis.__stub = { escHtml, fmt, navigate: () => {}, openProductChart: () => {},
    api: async (path) => {
      calls.push(path);
      const key = path.startsWith("/api/products/etfs/overview") ? "overview"
        : path === "/api/ml/robo/allocation/latest" ? "latest" : path.startsWith("/api/ml/robo/weights?") ? "weights" : path;
      const r = key === "overview" ? { ok: SC.overview } : scn[key];
      if (!r) throw Object.assign(new Error("예상 밖 호출 " + path), { status: 599 });
      if (r.wait) return new Promise((res) => setTimeout(() => res(JSON.parse(JSON.stringify(r.wait))), 120));
      if (r.ok) return JSON.parse(JSON.stringify(r.ok));
      throw Object.assign(new Error(r.message || "오류"), { status: r.status });
    } };
  return { root, handlers, calls };
}
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));
const tabs = (html) => [...html.matchAll(/aria-selected="(true|false)" class="pd-tab[^"]*" data-tab="([^"]+)"/g)].map((m) => [m[2], m[1] === "true"]);
let n = 0;
async function open(scn) {
  const env = setup(scn);
  const { setRiskProfileUser } = await import("__RP__");
  setRiskProfileUser("test-account"); // 앱 부팅의 /api/me 확인 뒤 계정 문맥
  const mod = await import("__MOD__?case=" + (++n));
  mod.onProductsViewActivated("agent-products");
  await tick();
  return { env, mod };
}
const click = async (env, dataset) => { env.handlers.click({ target: { closest: () => ({ dataset }) } }); await tick(); };
const snap = (env) => ({ html: env.root.innerHTML, tabs: tabs(env.root.innerHTML), calls: [...env.calls] });
const out = {};
const SAVED = { ok: SC.saved };
let r;
r = await open({ latest: SAVED, profile: { risk_profile: "conservative", level: "안정형" } });
out.saved = snap(r.env);
r = await open({ latest: SAVED, profile: { risk_profile: "aggressive", level: "공격투자형" } });
out.differs = snap(r.env);
r = await open({ latest: { status: 404, message: "저장된 배분 결과가 없습니다." }, weights: { ok: SC.weights }, profile: { risk_profile: "aggressive", level: "공격투자형" } });
out.fallback = snap(r.env);
r = await open({ latest: { status: 404, message: "저장된 배분 결과가 없습니다." } });
out.none = snap(r.env);
const errScn = { latest: { status: 500, message: "서버 오류 (HTTP 500)" }, weights: { ok: SC.weights }, profile: { risk_profile: "conservative", level: "안정형" } };
r = await open(errScn);
out.error = snap(r.env);
errScn.latest = SAVED;                                   // 「다시 불러오기」 — 이번엔 저장본이 온다
await click(r.env, { act: "weights" });
out.retry = snap(r.env);
r = await open({ latest: SAVED, profile: { risk_profile: "conservative", level: "안정형" } });
await click(r.env, { tab: "해외주식" });                  // 사용자가 탭을 고르고
r.mod.onProductsViewActivated("agent-products");         // 다른 화면에 갔다가 다시 들어온다
await tick();
out.picked = snap(r.env);
r = await open({ latest: { wait: SC.saved }, profile: { risk_profile: "conservative", level: "안정형" } });
out.loading = snap(r.env);
await tick(200);
out.loaded = snap(r.env);
out.writes = writes;
process.stdout.write(JSON.stringify(out));
"""


def _fn_src(src: str, head: str) -> str:
    start = src.index(head)
    return src[start:src.index("\n}\n", start) + 3].replace("export function", "function", 1)


def _run_screen(tmp_path: Path, sc: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    common = (PUB / "js" / "common.js").read_text(encoding="utf-8")
    screen = JS.read_text(encoding="utf-8")
    imports = {
        'import { api, escHtml, fmt } from "/js/common.js";': "const { api, escHtml, fmt } = globalThis.__stub;",
        'import { navigate } from "/js/core.js";': "const { navigate } = globalThis.__stub;",
        'import { openProductChart } from "/js/productchart.js";': "const { openProductChart } = globalThis.__stub;",
        'import { resolveWeights } from "/js/productweights.js";': f'import {{ resolveWeights }} from "{JSW.resolve().as_uri()}";',
        'import { readRiskProfile as readProfile } from "/js/riskprofile.js";': f'import {{ readRiskProfile as readProfile }} from "{(PUB / "js" / "riskprofile.js").resolve().as_uri()}";',
    }
    for old, new in imports.items():
        assert screen.count(old) == 1, f"화면 파일의 import 꼴이 바뀌었다 — 시험 틀도 함께: {old}"
        screen = screen.replace(old, new)
    mod = tmp_path / "products_under_test.mjs"
    mod.write_text(screen, encoding="utf-8")
    script = tmp_path / "screen.mjs"
    script.write_text(NODE_SCREEN.replace("__SC__", json.dumps(sc, ensure_ascii=False)).replace("__MOD__", mod.resolve().as_uri())
                      .replace("__RP__", (PUB / "js" / "riskprofile.js").resolve().as_uri())
                      .replace("__ESC__", _fn_src(common, "export function escHtml(")).replace("__FMT__", _fn_src(common, "export function fmt(")),
                      encoding="utf-8")
    run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_header_states_and_tab_keep(db, tmp_path, monkeypatch):
    """TC-PD-06 · 화면 그리기 — 머리 자산 배분 줄의 상태 다섯(저장본 · 성향 다름 · 기본 비중 · 둘 다 없음 · 못 읽음 + 다시 불러오기 ·
    불러오는 중)과 탭 차례 · 고른 탭 지키기 · 브라우저 저장소에 쓰지 않음. 서버가 실제로 낸 한눈에 · 저장본 · 기본 비중 응답으로."""
    sc = {"overview": pe.overview(per_group=5),          # 5 = products.js PER_GROUP
          "saved": _latest_response(monkeypatch, risk="conservative"),
          "weights": _weights_response("aggressive", 3)}
    out = _run_screen(tmp_path, sc)
    L, W = "/api/ml/robo/allocation/latest", "/api/ml/robo/weights?risk_profile=aggressive&horizon_years=3"
    first = lambda snap: [k for k, on in snap["tabs"] if on]                         # noqa: E731 — 고른 탭

    # 저장본 — 비중 큰 순(보수: 국내채권 50 이 먼저) · 저장 시각 KST · 다시 계산 안내 없음 · 기본 비중은 부르지 않음
    s = out["saved"]
    assert "자산 배분 — 국내채권 50% · " in s["html"] and "(저장한 배분 · 10월 15일 14:32 · 투자 기간 3년)" in s["html"]
    assert "자산 배분 보기 →" in s["html"] and "pd-mix-note" not in s["html"]
    assert first(s) == ["국내채권"] and [k for k, _ in s["tabs"]][:2] == ["국내채권", "국내주식"]
    assert L in s["calls"] and not any(c.startswith("/api/ml/robo/weights") for c in s["calls"])
    assert "탭 차례 = 내 자산 배분 비중 큰 순" in s["html"]
    # 성향 다름 — 저장본을 그대로 쓰고 안내 한 줄(두 성향 이름 · 자산 배분 화면으로)
    d = out["differs"]["html"]
    assert "자산 배분 — 국내채권 50% · " in d and "저장한 배분은 「보수적 (안정추구형)」 성향으로 계산했고," in d
    assert "지금 진단한 성향은 「공격투자형」 입니다" in d
    assert "다시 계산하러 가기 →" in d
    # 404 + 진단 성향 → 기본 비중(공격: 국내주식 45 먼저)
    f = out["fallback"]
    assert "(저장한 배분이 없어 진단 성향의 기본 비중 · 투자 기간 3년)" in f["html"] and "자산 배분 계산하기 →" in f["html"]
    assert f["calls"].count(W) == 1 and first(f) == ["국내주식"]
    # 404 + 진단 전 → 진단하기 안내 · 탭은 기본 차례
    nn = out["none"]
    assert "투자 성향을 진단하면 탭이 내 자산 배분 비중 큰 순으로 바뀝니다." in nn["html"] and "탭 차례 = 기본 차례" in nn["html"]
    assert not any(c.startswith("/api/ml/robo/weights") for c in nn["calls"])
    # 못 읽음(500) — 메우지 않고 까닭 · 「다시 불러오기」 · 탭은 기본 차례(국내주식) · 기본 비중을 부르지 않음
    e = out["error"]
    assert "자산 배분 비중을 읽지 못했습니다 — 서버 오류 (HTTP 500) · 탭은 기본 차례입니다." in e["html"]
    assert 'data-act="weights"' in e["html"] and "다시 불러오기" in e["html"] and "자산 배분 —" not in e["html"]
    assert not any(c.startswith("/api/ml/robo/weights") for c in e["calls"]) and first(e) == ["국내주식"]
    # 다시 불러오기 → 저장본이 오면 비중 줄 · 고른 탭이 없었으니 비중 큰 탭으로
    rt = out["retry"]
    assert "자산 배분 — 국내채권 50% · " in rt["html"] and first(rt) == ["국내채권"] and rt["calls"].count(L) == 2
    # 고른 탭은 다시 들어와 비중이 다시 와도 그대로
    assert first(out["picked"]) == ["해외주식"] and out["picked"]["calls"].count(L) == 2
    # 불러오는 중 → 온 뒤
    assert "자산 배분 비중을 불러오는 중…" in out["loading"]["html"] and "자산 배분 —" not in out["loading"]["html"]
    assert "자산 배분 — 국내채권 50% · " in out["loaded"]["html"] and first(out["loaded"]) == ["국내채권"]
    # 브라우저 저장소에 쓰지도 읽지도 않는다(성향 localStorage 읽기만)
    assert out["writes"] == []
def test_learn_links_both_ways():
    """TC-PD-07 · 화면 → 개념 학습 → 화면 두 방향(2026-10-16) — 화면의 학습 링크는 교재에 있는 장만 가리키고,
    그 장은 「앱에서 해 보기」 로 이 화면(#agent-products)에 돌아온다. 장 이름을 바꾸면 화면 링크가 죽지 않게."""
    from app.services import learn_pages as lp
    pages, errors = lp.load_builtin(PUB / "learn" / "content")
    assert errors == []
    src = JS.read_text(encoding="utf-8")
    slugs = re.findall(r'learnLink\("([a-z0-9-]+)"', src)
    assert set(slugs) == {"funds-etf", "investor-profile-suitability"}, slugs
    assert 'href="/app.html#learn/${slug}" target="_blank" rel="noopener"' in src, "새 탭(앱 안 장 화면 · 2026-10-19) · opener 끊기"
    for slug in set(slugs):
        assert slug in pages, slug
        assert "(/app.html#agent-products)" in pages[slug].body and "## 앱에서 해 보기" in pages[slug].body, slug
    # 레버리지 · 인버스 주의 상자 안에도 「펀드와 ETF」 — 왜 오래 들고 있으면 배수와 달라지나
    warn = src[src.index('<div class="pd-warn" role="note">'):]
    assert 'learnLink("funds-etf", "펀드와 ETF")' in warn[:warn.index("</div>")]

