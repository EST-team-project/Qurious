"""TC-FL — 금융감독원 「금융상품 한눈에」 오픈 API 실시간 연동(app/services/fss_products.py · 라우트) · 2026-10-12

약관(2026-10-12 원문 다시 확인 — 금융상품통합비교공시시스템 오픈 API 이용약관)
- 제9조 실시간으로 제공되는 정보를 서비스와 연동할 수 있을 뿐 · 복제 · 저장 · 전송 금지 · 화면에
  「금융상품통합비교공시시스템(금융감독원) 금융회사 상품정보」 를 사용한 결과임을 명시
- 제5조 인증키는 발급받은 사람만 · 제7조 개인 1일 10,000건

무엇을 지키나
- **저장하지 않는다** — 모듈이 캐시 · DB · 파일 쓰기를 쓰지 않는다(정적 규칙).
- 응답마다 출처 문구(약관 그대로)를 싣는다.
- 키가 없으면 바깥을 부르지 않고 「키 없음」 을 분명히 알린다(말없는 fallback 금지) — 일반 사용자 글에는 설정 이름 같은 개발 말이 없다.
- 키는 응답 · 로그 어디에도 나오지 않는다(바깥 오류 글에 주소가 섞여도).
- 기간(예: 12개월) 금리가 없는 상품도 숨기지 않고 뒤에 둔다.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import products as pr
from app.services import fss_products as fp

FAKE_KEY = "k" * 16 + "Z9" + "q" * 14  # 32자 · 실행할 때 이어 붙여 만든다(비밀값 검사에 걸리지 않게)

DEPOSIT_PAGE1 = {"result": {
    "prdt_div": "D", "total_count": "3", "max_page_no": "1", "now_page_no": "1", "err_cd": "000", "err_msg": "정상",
    "baseList": [
        {"dcls_month": "202610", "fin_co_no": "0010001", "fin_prdt_cd": "A1", "kor_co_nm": "가나은행", "fin_prdt_nm": "가나 정기예금",
         "join_way": "인터넷,스마트폰", "mtrt_int": "만기 후 1개월 50%", "spcl_cnd": "첫 거래 0.2%p", "join_deny": "1",
         "join_member": "실명의 개인", "etc_note": "", "max_limit": None, "dcls_strt_day": "20261001", "dcls_end_day": None,
         "fin_co_subm_day": "202610011000"},
        {"dcls_month": "202610", "fin_co_no": "0010002", "fin_prdt_cd": "B1", "kor_co_nm": "다라은행", "fin_prdt_nm": "다라 예금",
         "join_way": "영업점", "mtrt_int": "", "spcl_cnd": "없음", "join_deny": "3", "join_member": "제한", "etc_note": "",
         "max_limit": 50000000, "dcls_strt_day": "20261001", "dcls_end_day": None, "fin_co_subm_day": "202610011000"},
        {"dcls_month": "202610", "fin_co_no": "0010003", "fin_prdt_cd": "C1", "kor_co_nm": "마바은행", "fin_prdt_nm": "마바 6개월 예금",
         "join_way": "스마트폰", "mtrt_int": "", "spcl_cnd": "", "join_deny": "1", "join_member": "개인", "etc_note": "",
         "max_limit": None, "dcls_strt_day": "20261001", "dcls_end_day": None, "fin_co_subm_day": "202610011000"},
    ],
    "optionList": [
        {"dcls_month": "202610", "fin_co_no": "0010001", "fin_prdt_cd": "A1", "intr_rate_type": "S", "intr_rate_type_nm": "단리",
         "save_trm": "12", "intr_rate": 2.8, "intr_rate2": 3.1},
        {"dcls_month": "202610", "fin_co_no": "0010001", "fin_prdt_cd": "A1", "intr_rate_type": "S", "intr_rate_type_nm": "단리",
         "save_trm": "6", "intr_rate": 2.5, "intr_rate2": 2.7},
        {"dcls_month": "202610", "fin_co_no": "0010002", "fin_prdt_cd": "B1", "intr_rate_type": "M", "intr_rate_type_nm": "복리",
         "save_trm": "12", "intr_rate": 3.0, "intr_rate2": 3.0},
        {"dcls_month": "202610", "fin_co_no": "0010003", "fin_prdt_cd": "C1", "intr_rate_type": "S", "intr_rate_type_nm": "단리",
         "save_trm": "6", "intr_rate": 3.5, "intr_rate2": 3.6},
    ],
}}

ANNUITY_PAGE1 = {"result": {
    "prdt_div": "P", "total_count": "1", "max_page_no": "1", "now_page_no": "1", "err_cd": "000", "err_msg": "정상",
    "baseList": [
        {"dcls_month": "202610", "fin_co_no": "0010170", "fin_prdt_cd": "KR5102314204", "kor_co_nm": "가자산운용",
         "fin_prdt_nm": "가 연금증권투자신탁[채권]", "join_way": "인터넷", "pnsn_kind": "4", "pnsn_kind_nm": "연금저축펀드",
         "sale_strt_day": "20010201", "mntn_cnt": 73342945069, "prdt_type": "411", "prdt_type_nm": "채권형",
         "avg_prft_rate": 4.05, "dcls_rate": None, "guar_rate": None, "btrm_prft_rate_1": 2.96, "btrm_prft_rate_2": 1.97,
         "btrm_prft_rate_3": 3.35, "etc": None, "sale_co": "가은행,나증권", "dcls_strt_day": "20261001", "dcls_end_day": None,
         "fin_co_subm_day": "202610301534"}],
    "optionList": [],
}}


def _transport(pages: dict[int, dict] | None = None, *, status: int = 200, raise_exc: Exception | None = None, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if raise_exc is not None:
            raise raise_exc
        page = int(request.url.params.get("pageNo", "1"))
        body = (pages or {}).get(page, {"result": {"err_cd": "000", "err_msg": "정상", "total_count": "0", "max_page_no": "1",
                                                     "now_page_no": str(page), "baseList": [], "optionList": []}})
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def _search(**kw):
    kw.setdefault("api_key", FAKE_KEY)
    return asyncio.run(fp.search(**kw))


def test_no_key_does_not_call_out():
    seen = []
    r = asyncio.run(fp.search(kind="deposit", sector="bank", term=12, api_key="", transport=_transport(seen=seen)))
    assert r["status"] == "no_key" and r["items"] == [] and seen == []
    assert "FINANCE_SUPERVISORY" not in r["message"] and ".env" not in r["message"]


def test_deposit_normalized_sorted_and_nothing_hidden():
    seen = []
    r = _search(kind="deposit", sector="bank", term=12, sort="base", transport=_transport({1: DEPOSIT_PAGE1}, seen=seen))
    assert r["status"] == "ok"
    assert r["source_notice"] == fp.SOURCE_NOTICE
    assert "금융상품통합비교공시시스템(금융감독원) 금융회사 상품정보" in fp.SOURCE_NOTICE
    assert r["total_count"] == 3 and len(r["items"]) == 3            # 12개월이 없는 상품도 남는다
    assert [x["product"] for x in r["items"]] == ["다라 예금", "가나 정기예금", "마바 6개월 예금"]
    a1 = next(x for x in r["items"] if x["product_code"] == "A1")
    assert a1["rate"] == {"term_months": 12, "base": 2.8, "max": 3.1, "rate_type": "단리"}
    assert {o["term_months"] for o in a1["options"]} == {6, 12}
    assert a1["join_deny"] == "제한없음"
    assert next(x for x in r["items"] if x["product_code"] == "C1")["rate"] is None
    assert r["disclosed_month"] == "2026-10"
    # 요청 주소 · 인자
    req = seen[0]
    assert req.url.host == "finlife.fss.or.kr" and req.url.path.endswith("/finlifeapi/depositProductsSearch.json")
    assert req.url.params["topFinGrpNo"] == "020000" and req.url.params["pageNo"] == "1"


def test_sort_by_max_rate():
    r = _search(kind="deposit", sector="bank", term=12, sort="max", transport=_transport({1: DEPOSIT_PAGE1}))
    assert [x["product_code"] for x in r["items"]][:2] == ["A1", "B1"]   # 최고 우대 3.1 > 3.0


def test_pages_are_read_and_cap_is_explicit():
    p1 = json.loads(json.dumps(DEPOSIT_PAGE1)); p1["result"]["max_page_no"] = "9"
    seen = []
    r = _search(kind="deposit", sector="bank", term=12, transport=_transport({1: p1}, seen=seen), max_pages=2)
    assert len(seen) == 2 and r["pages_read"] == 2 and r["max_page_no"] == 9 and r["truncated"] is True


@pytest.mark.parametrize("code,status", [("010", "bad_key"), ("011", "bad_key"), ("012", "bad_key"), ("013", "bad_key"),
                                         ("020", "quota"), ("021", "ip_blocked"), ("100", "upstream_error"), ("900", "upstream_error")])
def test_error_codes(code, status):
    body = {"result": {"err_cd": code, "err_msg": "무엇", "total_count": "0"}}
    r = _search(kind="saving", sector="bank", term=12, transport=_transport({1: body}))
    assert r["status"] == status and r["items"] == []


def test_http_error_and_timeout_hide_key(caplog):
    caplog.set_level(logging.DEBUG)
    leak = httpx.ConnectTimeout(f"timeout for https://finlife.fss.or.kr/finlifeapi/x.json?auth={FAKE_KEY}")
    r1 = _search(kind="deposit", sector="bank", term=12, transport=_transport(raise_exc=leak))
    r2 = _search(kind="deposit", sector="bank", term=12, transport=_transport({1: DEPOSIT_PAGE1}, status=500))
    for r in (r1, r2):
        assert r["status"] == "upstream_error"
        assert FAKE_KEY not in json.dumps(r, ensure_ascii=False)
    assert FAKE_KEY not in caplog.text


def test_read_timeout_is_long_enough_for_savings():
    # 2026-10-12 실측: 적금(savingProductsSearch)은 우리 키로 은행 목록을 받는 데 10초를 넘겼다(예금 0.7초 · 틀린 키에는
    # 세 주소 모두 0.1초에 답함 — 금감원이 목록을 만드는 시간). 읽기 제한은 넉넉히, 연결이 안 되면 빨리 끊는다.
    seen = []
    _search(kind="saving", sector="bank", term=12, transport=_transport(seen=seen))
    t = seen[0].extensions["timeout"]
    assert t["read"] >= 25 and t["connect"] <= 10, t


def test_annuity_fields():
    r = _search(kind="annuity", sector="investment", term=12, transport=_transport({1: ANNUITY_PAGE1}))
    it = r["items"][0]
    assert it["pension_kind"] == "연금저축펀드" and it["product_type"] == "채권형"
    assert it["avg_return"] == 4.05 and it["past_returns"] == [2.96, 1.97, 3.35]
    assert it["sales_companies"] == ["가은행", "나증권"] and it["rate"] is None


def test_bad_kind_or_sector():
    with pytest.raises(ValueError):
        _search(kind="loan", sector="bank", term=12, transport=_transport())
    with pytest.raises(ValueError):
        _search(kind="deposit", sector="casino", term=12, transport=_transport())


def test_module_stores_nothing():
    """제9조 — 받은 값을 복제 · 저장하지 않는다: 캐시 · DB · 파일 쓰기를 부르지 않는다(글자 꼴 + 이름 꼴)."""
    src = Path(fp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
    for banned in ("sqlite3", "cache_get", "cache_set", "app.lib.cache", "app.database.postgres", "redis", "pickle", "shelve"):
        assert banned not in imported, banned
    calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for banned in ("open", "write_text", "write_bytes", "to_csv", "to_parquet", "dump", "setex", "hset"):
        assert banned not in calls, banned


# ── 라우트 ──────────────────────────────────────────────────────────────

def _client(roles):
    app = FastAPI()
    app.include_router(pr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": roles}
    return TestClient(app)


def test_route_no_key_messages(monkeypatch):
    monkeypatch.setattr(fp.settings, "FINANCE_SUPERVISORY_API_KEY", "", raising=False)
    r = _client([]).get("/api/products/savings?kind=deposit&sector=bank&term=12")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_key" and "admin_detail" not in body
    admin = _client(["admin"]).get("/api/products/savings?kind=deposit&sector=bank&term=12").json()
    assert "FINANCE_SUPERVISORY_API_KEY" in admin["admin_detail"]


def test_route_rejects_bad_params():
    c = _client([])
    assert c.get("/api/products/savings?kind=loan").status_code == 422
    assert c.get("/api/products/savings?kind=deposit&sector=casino").status_code == 422
    assert c.get("/api/products/savings?kind=deposit&term=7").status_code == 422
    assert c.get("/api/products/savings?kind=deposit&sort=best").status_code == 422
