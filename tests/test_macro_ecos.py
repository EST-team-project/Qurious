"""TC-MK — 거시경제 현황: 한국은행 ECOS 계열 읽기(app/services/macro_ecos.py · GET /api/macro/ecos · public/js/macroview.js) · 2026-10-29 · 할 일 ①-10 거시

옛 거시 화면은 야후 시세로 미국 10년물 · 유가를 그렸다(한국 거시가 아니었고 값마다 기준일이 없었다). 지금 약속:
1. 항목표가 수집기(`collector/ecos.py`)와 같다 — 앱 이미지에는 collector 가 없어 표를 둘 두는 대신 이 시험이 지킨다. (TC-MK-01)
2. 값 · 기준일 · 직전 관측값 · 변화를 서버가 한 곳에서 셈한다 — 금리는 %p · 지수 · 환율은 % · 물가는 전월 %와 전년 같은 달 %. (TC-MK-02)
3. 없는 계열은 줄을 빼지 않고 null + 까닭 · 표가 없거나 비면 available=false · 관리자에게만 할 일. (TC-MK-03)
4. 수집 DB 는 읽기 전용으로만 연다. (TC-MK-04)
5. 로그인한 사람만 · 일반 사용자 답에는 표 이름 · 명령이 없다. (TC-MK-05)
6. 화면 모듈은 응답 값 그대로 그린다 — 기준일 · 직전 날짜 · 출처 · 실시간 아님 · 초록 빨강 없음 · 이스케이프. (TC-MK-06)
7. ml.js 는 이 모듈을 부르고 app.html 에 칸이 있다 · 옛 야후 칸은 「해외 · 원자재 시세」 로 이름을 바꿨다. (TC-MK-07)
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
from app.services import macro_ecos as M
from collector import ecos as E

ROOT = Path(__file__).resolve().parents[1]
MV = ROOT / "public" / "js" / "macroview.js"


@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    p = tmp_path / "market.sqlite3"
    c = sqlite3.connect(p)
    c.executescript(E.ECOS_SERIES_DDL)
    c.close()
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(p))
    return p


def _put(p, stat, item, cycle, rows, name=""):
    c = sqlite3.connect(p)
    c.executemany("INSERT INTO ecos_series (stat_code, item_code, cycle, date, value, unit, item_name, fetched_at, "
                  "updated_at) VALUES (?, ?, ?, ?, ?, '', ?, 't', ?)",
                  [(stat, item, cycle, d, v, name, u) for d, v, u in rows])
    c.commit()
    c.close()


def _items(res):
    return {i["key"]: i for g in res["groups"] for i in g["items"]}


def test_group_table_matches_the_collector():
    """TC-MK-01 · 묶음 · 항목 코드 · 이름 · 주기 · 작성기관이 수집기와 같다 — 달라지면 화면이 조용히 빈다."""
    coll = {stat: (cycle, {k: (code, name) for k, code, name, _first in series}) for stat, cycle, series in E.GROUPS}
    mine = {stat: (cycle, {k: (code, name) for k, code, name, _u, _kind in specs}, origin)
            for _gk, _gl, stat, cycle, origin, specs in M.GROUPS}
    assert set(coll) == set(mine), "통계표 목록이 다르다"
    for stat, (cycle, items) in coll.items():
        assert mine[stat][0] == cycle and mine[stat][1] == items, stat
        assert mine[stat][2] == E.ORIGIN[stat], f"작성기관 {stat}"


def test_latest_prev_change_and_cpi_year_over_year(dbfile):
    """TC-MK-02 · 직전 관측값(주말 건너뜀) · 금리 %p · 지수 % · 환율 % · 물가 전월 % + 전년 같은 달 % · 값이 빈 줄은 쓰지 않는다."""
    _put(dbfile, "817Y002", "010200000", "D",
         [("2026-10-27", 3.758, "u27"), ("2026-10-26", 3.789, "u26"), ("2026-10-23", 3.80, "u23")])
    _put(dbfile, "802Y001", "0001000", "D",
         [("2026-10-27", 5638.34, "u"), ("2026-10-26", None, "u"), ("2026-10-23", 5469.47, "u")])   # 빈 줄은 건너뛴다
    _put(dbfile, "731Y001", "0000001", "D", [("2026-10-28", 1324.3, "uf"), ("2026-10-27", 1322.6, "u")])
    # 전년 같은 달(2025-09) 값이 열세 줄 안에 들어오게 둔다
    _put(dbfile, "901Y009", "0", "M", [("2026-09", 120.43, "uc"), ("2026-08", 120.05, "u"), ("2026-07", 119.9, "u"),
                                       ("2025-09", 117.05, "u")])
    res = M.read_ecos()
    it = _items(res)
    t3 = it["treasury_3y"]
    assert (t3["date"], t3["value"]) == ("2026-10-27", 3.758) and t3["prev"] == {"date": "2026-10-26", "value": 3.789}
    assert t3["change"] == {"unit": "%p", "value": -0.03}
    kospi = it["kospi"]
    assert kospi["prev"] == {"date": "2026-10-23", "value": 5469.47}                  # 값이 빈 10-26 은 건너뛴다
    assert kospi["change"] == {"unit": "%", "value": round((5638.34 / 5469.47 - 1) * 100, 2)}
    assert it["usd_krw"]["date"] == "2026-10-28" and it["usd_krw"]["change"]["unit"] == "%"
    cpi = it["cpi_total"]
    assert cpi["date"] == "2026-09" and cpi["cycle"] == "M"
    assert cpi["change"] == {"unit": "%", "value": round((120.43 / 120.05 - 1) * 100, 2)}
    assert cpi["yoy_pct"] == round((120.43 / 117.05 - 1) * 100, 2)
    assert res["available"] is True and res["updated_at"] == "uf"                   # 가장 늦게 받은 시각
    assert "ECOS" in res["source"] and res["groups"][0]["origin"] == "한국은행"
    assert it["usd_krw"]["origin"] == "서울외국환중개"                                  # 작성기관을 숨기지 않는다


def test_missing_series_empty_table_and_admin_hint(dbfile, tmp_path, monkeypatch):
    """TC-MK-03 · 없는 계열은 줄을 두고 null + 까닭 · 직전이 없으면 변화 null · 표가 없거나 비면 available=false · 할 일은 관리자만."""
    _put(dbfile, "817Y002", "010200000", "D", [("2026-10-27", 3.758, "u")])        # 한 줄뿐 → 직전 없음
    res = M.read_ecos()
    it = _items(res)
    assert it["treasury_3y"]["prev"] is None and it["treasury_3y"]["change"] is None
    assert it["kospi"]["value"] is None and it["kospi"]["reason"] and it["kospi"]["change"] is None
    assert len(it) == sum(len(g[5]) for g in M.GROUPS)                               # 줄은 하나도 빠지지 않는다

    empty = tmp_path / "e.sqlite3"
    sqlite3.connect(empty).executescript(E.ECOS_SERIES_DDL)
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(empty))
    r = M.read_ecos()
    assert r["available"] is False and r["groups"] == [] and "admin_hint" not in r
    assert "admin_hint" in M.read_ecos(admin=True)

    notable = tmp_path / "n.sqlite3"
    sqlite3.connect(notable).execute("CREATE TABLE x (a)")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(notable))
    assert M.read_ecos()["available"] is False and "ecos_series" in M.read_ecos(admin=True)["admin_hint"]

    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "none.sqlite3"))
    assert M.read_ecos()["available"] is False


def test_opens_collector_db_read_only(dbfile, monkeypatch):
    """TC-MK-04 · 수집 DB 는 mode=ro 로만 연다 — 앱이 수집 DB 에 쓰지 못한다."""
    seen = []
    real = sqlite3.connect

    def spy(target, *a, **k):
        seen.append(str(target))
        return real(target, *a, **k)

    monkeypatch.setattr(M.sqlite3, "connect", spy)
    M.read_ecos()
    assert seen and all("mode=ro" in s for s in seen), seen


def _client(roles):
    app = FastAPI()
    app.include_router(mr.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "email": "t@t", "roles": roles}
    return TestClient(app)


def test_route_login_and_admin_split(dbfile):
    """TC-MK-05 · 로그인해야 · 비었을 때 일반 사용자 답엔 할 일이 없고 관리자 답에만."""
    r = _client([]).get("/api/macro/ecos")
    assert r.status_code == 200 and r.json()["available"] is False and "admin_hint" not in r.json()
    assert "admin_hint" in _client(["admin"]).get("/api/macro/ecos").json()
    app = FastAPI()
    app.include_router(mr.router)
    assert TestClient(app).get("/api/macro/ecos").status_code == 401


ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')

DATA = {
    "available": True, "source": "한국은행 경제통계시스템(ECOS)", "notice": "한국은행이 집계 · 고시한 통계를 수집한 값입니다 — 거래소 실시간 시세가 아니며.",
    "updated_at": "2026-10-28T12:42:19+09:00",
    "groups": [
        {"key": "market_rates", "label": "시장금리", "origin": "한국은행", "cycle": "D", "items": [
            {"key": "treasury_3y", "label": "국고채(3년)", "unit": "연%", "cycle": "D", "kind": "pp", "date": "2026-10-27", "value": 3.758,
             "prev": {"date": "2026-10-26", "value": 3.789}, "change": {"unit": "%p", "value": -0.03}, "yoy_pct": None, "reason": ""},
            {"key": "cd_91d", "label": "CD(91일)", "unit": "연%", "cycle": "D", "kind": "pp", "date": "2026-10-27", "value": 3.27,
             "prev": {"date": "2026-10-26", "value": 3.26}, "change": {"unit": "%p", "value": 0.01}, "yoy_pct": None, "reason": ""}]},
        {"key": "index", "label": "주가지수", "origin": "한국은행", "cycle": "D", "items": [
            {"key": "kospi", "label": "KOSPI지수", "unit": "포인트", "cycle": "D", "kind": "pct", "date": "2026-10-27", "value": 5638.34,
             "prev": {"date": "2026-10-23", "value": 5469.47}, "change": {"unit": "%", "value": 3.09}, "yoy_pct": None, "reason": ""},
            {"key": "kosdaq", "label": "KOSDAQ지수", "unit": "포인트", "cycle": "D", "kind": "pct", "date": None, "value": None,
             "prev": None, "change": None, "yoy_pct": None, "reason": "아직 받은 값이 없습니다."}]},
        {"key": "price", "label": "물가", "origin": "국가데이터처", "cycle": "M", "items": [
            {"key": "cpi_total", "label": "소비자물가지수 총지수", "unit": "지수", "cycle": "M", "kind": "cpi", "date": "2026-09", "value": 120.43,
             "prev": {"date": "2026-08", "value": 120.05}, "change": {"unit": "%", "value": 0.32}, "yoy_pct": 2.88, "reason": ""}]},
    ],
}


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


def test_screen_draws_response_values_with_dates_and_source(tmp_path):
    """TC-MK-06 · 응답 값 그대로 · 기준일 · 직전 날짜 · 물가 전년 대비 · 출처 · 없는 값은 줄표 + 까닭 · 초록 빨강 없음 · 이스케이프."""
    out = _run(tmp_path, """
      out.html = mv.renderEcos({ok: true, data: DATA}, esc);
      out.fmt = [mv.numText(3.758), mv.numText(5638.34, 2), mv.numText(null), mv.signedText(-0.03, "%p"), mv.signedText(0.32, "%"),
                 mv.signedText(0, "%p"), mv.stampText("2026-10-28T12:42:19+09:00"), mv.stampText("nope")];
      const T = DATA.groups[0].items[0], C = DATA.groups[2].items[0];
      out.line = mv.changeText(T); out.cpi = mv.changeText(C); out.none = mv.changeText({prev: null});
      out.fail = mv.renderEcos({ok: false, error: "<b>x</b>"}, esc);
      out.na = mv.renderEcos({ok: true, data: {available: false, reason: "아직 못 받음", admin_hint: "<script>"}}, esc);
    """)
    html = out["html"]
    assert "3.758%" in html and "3.27%" in html and "5,638.34 포인트" in html and "120.43" in html
    assert "기준일 2026-10-27" in html and "기준일 2026-09" in html
    assert "직전 관측일(2026-10-26) 대비 <span" in html and "▼ −0.03%p</span>" in html and "▲ +3.09%</span>" in html
    assert "전월(2026-08) 대비 <span" in html and "▲ +0.32%</span>" in html and "전년 같은 달 대비 +2.88%" in html
    assert out["line"] == "직전 관측일(2026-10-26) 대비 ▼ −0.03%p" and out["cpi"] == "전월(2026-08) 대비 ▲ +0.32% · 전년 같은 달 대비 +2.88%"
    assert out["none"] == "—"
    assert "아직 받은 값이 없습니다." in html                                          # KOSDAQ — 줄표 + 서버 까닭
    assert "작성기관 한국은행" in html and "작성기관 국가데이터처" in html
    assert "출처: 한국은행 경제통계시스템(ECOS)" in html and "수집 2026-10-28 12:42 KST" in html and "실시간 시세가 아니며" in html
    for color in ("#22c55e", "#ef4444", "green", "red"):                             # 오르내림에 좋고 나쁨을 칠하지 않는다
        assert color not in html
    assert out["fmt"] == ["3.758", "5,638.34", "—", "−0.03%p", "+0.32%", "0%p", "2026-10-28 12:42 KST", ""]
    assert "&lt;b&gt;x&lt;/b&gt;" in out["fail"] and "<b>" not in out["fail"]
    assert "아직 못 받음" in out["na"] and "&lt;script&gt;" in out["na"] and "<script>" not in out["na"]


def test_wiring_and_legacy_block_renamed():
    """TC-MK-07 · ml.js 가 macroview.js 를 부르고 app.html 에 칸이 한 번 있다 · 옛 야후 칸은 이름을 바꿨고 「목업」 글이 없다."""
    ml = (ROOT / "public" / "js" / "ml.js").read_text(encoding="utf-8")
    app = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
    assert 'from "/js/macroview.js"' in ml and "loadEcos(api)" in ml and "renderEcos(res, escHtml)" in ml
    assert app.count('id="macro-ecos"') == 1
    view = app.split('data-view="macro-dashboard"', 1)[1].split('data-view="macro-industry"', 1)[0]
    assert "한국 거시경제 — 한국은행 통계" in view and "해외 · 원자재 시세 (지연 시세)" in view and "목업" not in view
    assert 'id="macro-grid"' in view and 'id="macro-loading"' in view                  # 옛 칸 id 는 그대로
