"""TC-MI — 국내 산업별 하루 등락: KSIC 중분류 묶음(app/services/macro_industry.py · GET /api/macro/industry-kr · public/js/macroview.js) · 2026-10-29 · 할 일 ①-10 산업

옛 산업 화면은 미국 섹터 ETF 의 지연 시세를 그렸다(한국 산업이 아니었다). 지금 약속:
1. 업종코드(3 ~ 5자리)의 앞 두 자리로 KSIC 중분류에 묶는다 — 표에 없는 두 자리는 버리지 않고 「분류 못 찾음」 한 묶음. (TC-MI-01)
2. 등락 중앙값 · 오른 / 내린 / 보합 수 · 등락률이 없는 종목은 빼고 몇 곳이 들어갔는지 밝힌다 · 종목 셋 미만은 thin · 큰 순 정렬(모르는 묶음은 맨 뒤). (TC-MI-02)
3. KSIC 이름 표에 10차와 11차가 함께 있어도 **11차만** 쓴다 — 같은 코드에 이름이 둘이면 어느 쪽이 나올지 정해지지 않는다. (TC-MI-03)
4. 회사마다 가장 늦게 본 판만 쓴다 · 표가 없거나 비면 available=false · 관리자에게만 할 일 · 읽기 전용 · 로그인. (TC-MI-04 ~ 05)
5. 화면은 응답 값 그대로 — 곳 수 · 기준일 · 출처 · 「업종 전체 지수가 아니다」 · 종목 적음 표시 · 이스케이프. (TC-MI-06)
6. ml.js 가 이 모듈을 부르고 app.html 에 칸이 한 번 있다 · 옛 ETF 칸은 이름만 바꿨다. (TC-MI-07)
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import macro as mr
from app.services import macro_industry as M
from collector import db as CDB

ROOT = Path(__file__).resolve().parents[1]
MV = ROOT / "public" / "js" / "macroview.js"
KSIC = [("11", "대분류", "C", "제조업(10~34)", ""), ("11", "중분류", "26", "전자 부품·장비 제조업", "C"),
        ("11", "중분류", "21", "의약품 제조업", "C"), ("11", "대분류", "K", "금융 및 보험업(64~66)", ""),
        ("11", "중분류", "65", "보험업", "K"),
        ("11", "중분류", "10", "식료품 제조업", "C"),
        # 10차 — 이름이 다른 같은 코드. 쓰면 안 된다
        ("10", "중분류", "65", "보험 및 연금업", "K"), ("10", "대분류", "K", "옛 금융", "")]


@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(CDB.SCHEMA)
    c.executemany("INSERT INTO ksic_code (revision, level, code, name, parent_code, section, loaded_at) VALUES (?, ?, ?, ?, ?, ?, 't')",
                  [(rev, lv, code, name, parent, parent or code) for rev, lv, code, name, parent in KSIC])
    c.commit()
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def _company(p, corp, stock, name, induty, seen="2026-10-22T12:00:00+09:00", sha="a"):
    c = sqlite3.connect(p)
    c.execute("INSERT INTO dart_company (corp_code, fields_sha256, stock_code, stock_name, induty_code, first_seen_at, last_seen_at) "
              "VALUES (?, ?, ?, ?, ?, 't', ?)", (corp, sha, stock, name, induty, seen))
    c.commit()
    c.close()


def _price(p, stock, flt, cap, bas="20261027"):
    c = sqlite3.connect(p)
    c.execute("INSERT INTO price_daily (bas_dt, srtn_cd, flt_rt, mrkt_tot_amt) VALUES (?, ?, ?, ?)", (bas, stock, flt, cap))
    c.commit()
    c.close()


def _seed(p):
    # 전자부품(26): 5 종목 중 4 곳 등락 있음 · 의약품(21): 2 곳(thin) · 보험(65): 1 곳 · 모르는 코드(99): 1 곳
    rows = [("c1", "000001", "A전자", "26110", 3.0, 500), ("c2", "000002", "B전자", "26299", 1.0, 400),
            ("c3", "000003", "C전자", "261", -1.0, 300), ("c4", "000004", "D전자", "26429", 0.0, 200),
            ("c5", "000005", "E전자", "26121", None, 100),                          # 그날 시세 행이 없다
            ("c6", "000006", "F약품", "212", 2.0, 50), ("c7", "000007", "G약품", "21100", -2.0, 40),
            ("c8", "000008", "H보험", "65110", 0.5, 70), ("c9", "000009", "I기타", "99999", 1.5, 10)]
    for corp, stock, name, code, flt, cap in rows:
        _company(p, corp, stock, name, code)
        if flt is not None:
            _price(p, stock, flt, cap)
    _price(p, "000001", 9.9, 1, bas="20261026")                                       # 어제 줄 — 쓰지 않는다


def test_groups_by_first_two_digits_and_unknown_bucket(dbfile):
    """TC-MI-01 · 3 · 4 · 5자리 코드 모두 앞 두 자리로 묶인다 · 표에 없는 두 자리는 「분류 못 찾음」 한 묶음 · 곳 수 합 = 회사 수."""
    _seed(dbfile)
    res = M.read_industry()
    by = {g["code"]: g for g in res["groups"]}
    assert set(by) == {"26", "21", "65", ""}
    assert by["26"]["n"] == 5 and by["21"]["n"] == 2 and by[""]["name"] == "분류 못 찾음"
    assert by["26"]["section"] == {"code": "C", "name": "제조업(10~34)"}
    assert sum(g["n"] for g in res["groups"]) == res["universe"] == 9
    assert res["as_of"] == "2026-10-27"                                              # 가장 늦은 날 · 어제 줄은 안 쓴다


def test_median_counts_priced_thin_and_sort(dbfile):
    """TC-MI-02 · 중앙값 · 오른 / 내린 / 보합 · 등락률 없는 종목은 빼고 priced 로 밝힘 · 셋 미만 thin · 큰 순(모르는 묶음은 맨 뒤) · 대표 종목은 시가총액 순."""
    _seed(dbfile)
    res = M.read_industry()
    by = {g["code"]: g for g in res["groups"]}
    e = by["26"]                                                                     # 값 3.0 · 1.0 · −1.0 · 0.0 → 중앙값 0.5
    assert e["priced"] == 4 and e["change_median"] == 0.5 and (e["up"], e["down"], e["flat"]) == (2, 1, 1)
    assert e["thin"] is False and [t["name"] for t in e["top"]] == ["A전자", "B전자", "C전자"]
    assert by["21"]["thin"] is True and by["21"]["change_median"] == 0.0 and (by["21"]["up"], by["21"]["down"]) == (1, 1)
    assert by["65"]["change_median"] == 0.5 and by["65"]["thin"] is True
    medians = [g["change_median"] for g in res["groups"]]
    assert medians == sorted(medians, reverse=True)
    assert res["priced"] == 8                                                         # 시세 행이 없는 1곳은 빠짐
    # 등락률이 전부 없는 묶음은 중앙값 null 로 맨 뒤
    _company(dbfile, "c10", "000010", "J무시세", "10100")
    last = M.read_industry()["groups"][-1]
    assert last["change_median"] is None and last["priced"] == 0


def test_only_ksic_revision_11_names(dbfile):
    """TC-MI-03 · 10차 이름(「보험 및 연금업」 · 「옛 금융」)이 같은 코드에 있어도 11차 이름만 나온다."""
    _seed(dbfile)
    res = M.read_industry()
    by = {g["code"]: g for g in res["groups"]}
    assert by["65"]["name"] == "보험업" and by["65"]["section"]["name"] == "금융 및 보험업(64~66)"
    assert "제11차" in res["source"] and M.KSIC_REVISION == "11"


def test_latest_company_version_only_and_missing_tables(dbfile, tmp_path, monkeypatch):
    """TC-MI-04 · 회사마다 가장 늦게 본 판만(옛 판 업종은 안 센다) · 표가 없거나 비면 available=false · 관리자에게만 할 일 · 수집 DB 없음."""
    _seed(dbfile)
    _company(dbfile, "c1", "000001", "A전자", "21100", seen="2026-10-20T12:00:00+09:00", sha="old")   # 옛 판 — 업종이 달랐다
    res = M.read_industry()
    assert {g["code"]: g["n"] for g in res["groups"]}["26"] == 5 and res["universe"] == 9

    empty = tmp_path / "e.sqlite3"
    sqlite3.connect(empty).executescript(CDB.SCHEMA)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(empty))
    r = M.read_industry()
    assert r["available"] is False and r["groups"] == [] and "admin_hint" not in r and "admin_hint" in M.read_industry(admin=True)

    partial = tmp_path / "p.sqlite3"
    sqlite3.connect(partial).execute("CREATE TABLE price_daily (bas_dt TEXT)")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(partial))
    assert "dart_company" in M.read_industry(admin=True)["admin_hint"]
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "none.sqlite3"))
    assert M.read_industry()["available"] is False


def test_read_only_and_route(dbfile, monkeypatch):
    """TC-MI-05 · 수집 DB 는 mode=ro 로만 · 로그인해야 · 비었을 때 일반 사용자 답엔 할 일이 없다."""
    seen, real = [], sqlite3.connect
    monkeypatch.setattr(M.sqlite3, "connect", lambda t, *a, **k: (seen.append(str(t)), real(t, *a, **k))[1])
    M.read_industry()
    assert seen and all("mode=ro" in s for s in seen)
    monkeypatch.undo()

    def client(roles):
        app = FastAPI()
        app.include_router(mr.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": roles}
        return TestClient(app)

    monkeypatch.setenv("COLLECTOR_DB_PATH", str(dbfile))
    r = client([]).get("/api/macro/industry-kr")
    assert r.status_code == 200 and r.json()["available"] is False and "admin_hint" not in r.json()
    assert "admin_hint" in client(["admin"]).get("/api/macro/industry-kr").json()
    app = FastAPI()
    app.include_router(mr.router)
    assert TestClient(app).get("/api/macro/industry-kr").status_code == 401


ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')
DATA = {"available": True, "as_of": "2026-10-27", "universe": 351, "priced": 351, "source": "전자공시(DART) · KSIC 제11차 · 공공데이터포털 주식시세정보",
        "notice": "수집 대상 351곳만의 업종별 하루 등락입니다 — 업종 전체 지수가 아니고.",
        "groups": [
            {"code": "26", "name": "전자 부품 <제조업>", "section": {"code": "C", "name": "제조업(10~34)"}, "n": 31, "priced": 31,
             "change_median": 3.12, "up": 27, "down": 4, "flat": 0, "thin": False, "top": [{"code": "005930", "name": "삼성전자"}, {"code": "000660", "name": "SK하이닉스"}]},
            {"code": "52", "name": "창고업", "section": {"code": "H", "name": "운수 및 창고업"}, "n": 1, "priced": 1,
             "change_median": -2.2, "up": 0, "down": 1, "flat": 0, "thin": True, "top": [{"code": "086280", "name": "현대글로비스"}]},
            {"code": "99", "name": "시세 없음", "section": {"code": "", "name": ""}, "n": 2, "priced": 0,
             "change_median": None, "up": 0, "down": 0, "flat": 0, "thin": True, "top": []}]}


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as mv from "{MV.resolve().as_uri()}";\n{ESC}\nconst DATA = {json.dumps(DATA, ensure_ascii=False)};\n'
                      f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_screen_draws_response_values(tmp_path):
    """TC-MI-06 · 곳 수 · 기준일 · 중앙값 부호 · 오른 / 내린 · 대표 종목 · 종목 적음 · 출처 · 업종 전체 지수가 아니다 · 이스케이프 · 실패 · 자료 없음."""
    out = _run(tmp_path, """
      out.html = mv.renderIndustry({ok: true, data: DATA}, esc);
      out.fail = mv.renderIndustry({ok: false, error: "<i>x</i>"}, esc);
      out.na = mv.renderIndustry({ok: true, data: {available: false, reason: "아직 못 받음", admin_hint: "<script>"}}, esc);
    """)
    html = out["html"]
    assert "기준일 2026-10-27 · 수집 대상 351곳" in html and "한국표준산업분류(KSIC) 중분류" in html
    assert "▲ +3.12%" in html and "▼ −2.2%" in html and "오른 27 · 내린 4" in html and "오른 0 · 내린 1" in html
    assert "삼성전자 · SK하이닉스" in html and "제조업(10~34)" in html and "31곳" in html
    assert html.count("(종목 적음)") == 2                                             # 창고업 · 시세 없음 묶음
    assert "2곳 (등락 0곳)" in html and "—" in html                                    # 등락률이 없는 묶음은 줄표
    assert "업종 전체 지수가 아니고" in html and "출처: 전자공시(DART)" in html
    assert "전자 부품 &lt;제조업&gt;" in html and "<제조업>" not in html                 # 이스케이프
    assert "&lt;i&gt;x&lt;/i&gt;" in out["fail"] and "<i>" not in out["fail"]
    assert "아직 못 받음" in out["na"] and "&lt;script&gt;" in out["na"] and "<script>" not in out["na"]


def test_wiring_and_legacy_etf_block_renamed():
    """TC-MI-07 · ml.js 가 새 모듈을 부르고 app.html 에 칸이 한 번 있다 · 옛 ETF 칸 id 는 그대로 · 이름만 「미국 섹터 ETF (지연 시세)」."""
    ml = (ROOT / "public" / "js" / "ml.js").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert "loadIndustryKr(api)" in ml and "renderIndustry(res, escHtml)" in ml
    assert app.count('id="industry-kr"') == 1
    view = app.split('data-view="macro-industry"', 1)[1].split("<!-- 재무제표 분석 -->", 1)[0]
    assert "국내 산업별 하루 등락" in view and "미국 섹터 ETF (지연 시세)" in view and "목업" not in view
    assert 'id="industry-loading"' in view and 'id="industry-table-body"' in view and 'id="industry-table-wrap"' in view
