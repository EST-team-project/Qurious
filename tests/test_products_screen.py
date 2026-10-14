"""TC-PD — 투자 성향별 상품 안내 화면(public/js/products.js) · 2026-10-12

무엇을 지키나
1. 화면이 읽는 칸이 서버 응답에 있다 — products.js 가 「변수.칸」 으로 읽는 곳을 모두 모아 응답과 맞댄다(TC-DG-04 꼴).
   서버가 칸 이름을 바꾸면 화면은 오류 없이 빈칸을 그리므로 시험이 먼저 깨지게. (TC-PD-01)
2. 규제 숫자를 화면에 따로 적지 않는다 — 사전교육 시간 · 기본예탁금 · 시행일은 응답(요건 상수표 한 곳)에서만 온다. (TC-PD-02)
3. 연결 — app.html 뿌리 칸 · 스타일 · main.js 부르는 줄 · 메뉴 이름 · 옛 단추 가드(옛 칸이 없어도 agent.js 가 멈추지 않게) ·
   화면 스캐너가 읽는 진입 훅 꼴. (TC-PD-03)
4. 자산 배분은 읽기만 — 비중표를 화면에 복제하지 않고, 무거운 배분 API 는 단추를 눌렀을 때만 부른다. 성향은 읽기만 하고
   브라우저 저장소에 쓰지 않는다(받은 비중은 그 탭의 sessionStorage 에만). (TC-PD-04)
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.services import fss_products as fp
from app.services import product_etfs as pe
from tests.test_fss_products import ANNUITY_PAGE1, DEPOSIT_PAGE1, FAKE_KEY, _transport
from tests.test_product_etfs import _make_db

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
JS = PUB / "js" / "products.js"
#: products.js 머리말의 변수 이름 규칙과 같다 — 객체마다 이름 하나
JS_READ = re.compile(r"(?<![\w.])(ov|ls|it|cls|grp|dv|rq|sv|p|rt|al)((?:\??\.[A-Za-z_]\w*)+)")

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


def test_screen_reads_only_fields_the_server_sends(db):
    """TC-PD-01"""
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
    }
    src = JS.read_text(encoding="utf-8")
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
    """TC-PD-04"""
    src = JS.read_text(encoding="utf-8")
    assert not re.search(r"(국내주식|해외주식|국내채권|대체자산|현금)[\"']?\s*:\s*\d", src), "비중표를 화면에 복제하지 않는다"
    assert '"/api/ml/robo/allocation"' not in src
    assert src.count('api(`/api/ml/robo/weights?') == 1
    calls = [ln for ln in src.splitlines() if "loadWeights()" in ln and "function loadWeights" not in ln]
    assert len(calls) == 1 and 'd.act === "weights"' in calls[0], "비중 조회는 단추를 눌렀을 때만"
    assert "localStorage.setItem" not in src and 'localStorage.getItem("robo_risk_profile")' in src
