"""TC-PIX — 공개 지수 종가(랜딩 티커 · S166)

랜딩(로그인 전 첫 화면)에 코스피 · 코스닥의 가장 최근 거래일 종가 한 줄을 보인다. 값은 수집 DB 의 지수 일봉
(공공데이터포털 금융위원회 지수시세정보 — 공공누리 제4유형: 출처 표시 · 비상업 · 변경 금지)이라 **가공 없이 종가 그대로**
읽고, 기준일과 출처를 같이 싣는다. 외부 시세 사이트는 부르지 않는다.

1. 두 지수의 가장 최근 거래일 종가를 그대로 · 같은 이름의 다른 시리즈를 섞지 않는다. (TC-PIX-01)
2. 기준일이 다르면 늦은 날 것만 · 종가 0 은 건너뜀 · 한쪽이 없으면 있는 쪽만. (TC-PIX-02)
3. DB 없음 · 표 없음 · 빈 표 → 빈 목록(화면은 칸을 숨긴다). (TC-PIX-03)
4. 라우트 — 로그인 없이 200 · 응답 모양 · 출처 문구 · 캐시 머리. (TC-PIX-04)
5. 분당 제한(넘으면 429) · 서버 캐시 · 횟수 저장소가 안 돼도 막지 않음. (TC-PIX-05)
6. 화면 — 서버가 준 값만 · 못 받으면 숨김 · 쿠키를 보내지 않음 · 「실시간」 · 계산값 없음. (TC-PIX-06)
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import public_data
from app.services import collector_db
from collector.db import SCHEMA  # 수집기의 실제 스키마 — 픽스처 DB 가 실제와 같은 모양이게

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "public" / "js" / "landing.js").read_text(encoding="utf-8")
CSS = (ROOT / "public" / "css" / "landing.css").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

EMPTY = {"as_of": None, "items": []}


def _make_db(path: Path, rows: list[tuple]) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO index_daily (bas_dt, idx_csf, idx_nm, clpr) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


def test_reads_latest_close_of_kospi_and_kosdaq_as_is(tmp_path):
    """TC-PIX-01 · 두 지수의 가장 최근 거래일 종가를 그대로 · 같은 이름의 다른 시리즈는 섞지 않는다 · 계산값이 없다."""
    db = _make_db(tmp_path / "m.sqlite3", [
        ("20261027", "KOSPI시리즈", "코스피", 2640.01), ("20261028", "KOSPI시리즈", "코스피", 2650.12),
        ("20261027", "KOSDAQ시리즈", "코스닥", 850.5), ("20261028", "KOSDAQ시리즈", "코스닥", 853.04),
        ("20261028", "KRX시리즈", "코스피", 1.0),      # 이름만 같은 다른 시리즈 — 섞이면 안 된다
        ("20261028", "KOSPI시리즈", "코스피 200", 357.77),  # 이름이 비슷한 다른 지수
    ])
    got = collector_db.read_latest_index_closes(db)
    assert got == {"as_of": "2026-10-28", "items": [{"name": "코스피", "close": 2650.12}, {"name": "코스닥", "close": 853.04}]}
    assert set(got["items"][0]) == {"name", "close"}, "종가 말고 등락 · 전일 대비 같은 계산값을 싣지 않는다(변경 금지)"


def test_mixed_dates_zero_close_and_missing_series(tmp_path):
    """TC-PIX-02 · 기준일이 다르면 늦은 날 것만 · 종가 0 은 건너뜀 · 한쪽이 없으면 있는 쪽만."""
    mixed = _make_db(tmp_path / "a.sqlite3", [
        ("20261029", "KOSPI시리즈", "코스피", 2660.5),
        ("20261028", "KOSDAQ시리즈", "코스닥", 853.04),
    ])
    assert collector_db.read_latest_index_closes(mixed) == {"as_of": "2026-10-29", "items": [{"name": "코스피", "close": 2660.5}]}, \
        "다른 날의 종가를 한 줄에 섞지 않는다"
    zero = _make_db(tmp_path / "b.sqlite3", [
        ("20261029", "KOSPI시리즈", "코스피", 2660.5), ("20261029", "KOSDAQ시리즈", "코스닥", 0),
        ("20261028", "KOSDAQ시리즈", "코스닥", 853.04),
    ])
    got = collector_db.read_latest_index_closes(zero)
    assert got["items"] == [{"name": "코스피", "close": 2660.5}] and got["as_of"] == "2026-10-29", "종가 0 인 날은 건너뛰고 더 늦은 쪽만 남는다"
    only = _make_db(tmp_path / "c.sqlite3", [("20261028", "KOSDAQ시리즈", "코스닥", 853.04)])
    assert collector_db.read_latest_index_closes(only) == {"as_of": "2026-10-28", "items": [{"name": "코스닥", "close": 853.04}]}


def test_missing_db_table_or_rows_give_empty_list(tmp_path, monkeypatch):
    """TC-PIX-03 · DB 없음 · 표 없음 · 빈 표는 빈 목록 — 화면은 칸을 숨긴다(빈 숫자를 두지 않는다)."""
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(tmp_path / "없음.sqlite3"))
    assert asyncio.run(collector_db.get_latest_index_closes()) == EMPTY
    no_table = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(no_table)
    conn.execute("CREATE TABLE other (a)")
    conn.commit()
    conn.close()
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(no_table))
    assert asyncio.run(collector_db.get_latest_index_closes()) == EMPTY
    empty = _make_db(tmp_path / "e.sqlite3", [])
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(empty))
    assert asyncio.run(collector_db.get_latest_index_closes()) == EMPTY


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(public_data, "_cache", {"at": 0.0, "value": None})
    db = _make_db(tmp_path / "m.sqlite3", [
        ("20261028", "KOSPI시리즈", "코스피", 2650.12), ("20261028", "KOSDAQ시리즈", "코스닥", 853.04),
    ])
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(db))
    app = FastAPI()
    app.include_router(public_data.router)
    return TestClient(app)


def test_route_is_public_and_returns_source_and_as_of(client):
    """TC-PIX-04 · 로그인 없이 200 · 응답 모양(as_of · source · items) · 출처 문구에 공공누리 제4유형 · 캐시 머리."""
    r = client.get("/api/public/index-closes")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"as_of", "source", "items"}
    assert body["as_of"] == "2026-10-28"
    assert body["source"] == collector_db.INDEX_SOURCE and "공공누리 제4유형" in body["source"] and "금융위원회" in body["source"]
    assert body["items"] == [{"name": "코스피", "close": 2650.12}, {"name": "코스닥", "close": 853.04}]
    assert r.headers["cache-control"].startswith("public")
    assert all(not route.dependencies for route in public_data.router.routes), "로그인 없이 읽는 길이다(의존성으로 인증을 걸지 않는다)"


def test_rate_limit_cache_and_counter_outage(client, monkeypatch):
    """TC-PIX-05 · 분당 제한을 넘으면 429 · 10분 서버 캐시(수집 DB 를 매번 읽지 않는다) · 횟수 저장소가 안 돼도 막지 않는다."""
    class Counter:
        def __init__(self):
            self.n = 0

        async def incr(self, key, ttl=None):
            self.n += 1
            return self.n

    monkeypatch.setattr(public_data, "rate_limit_cache", Counter())
    monkeypatch.setattr(public_data, "RATE_MAX", 3)
    reads = {"n": 0}
    real = collector_db.get_latest_index_closes

    async def counted():
        reads["n"] += 1
        return await real()

    monkeypatch.setattr(collector_db, "get_latest_index_closes", counted)
    assert [client.get("/api/public/index-closes").status_code for _ in range(4)] == [200, 200, 200, 429]
    assert reads["n"] == 1, "캐시 안에서는 수집 DB 를 다시 읽지 않는다"

    class Down:
        async def incr(self, key, ttl=None):
            raise RuntimeError("redis down")

    monkeypatch.setattr(public_data, "rate_limit_cache", Down())
    assert client.get("/api/public/index-closes").status_code == 200, "횟수 저장소가 안 돼도 값싼 읽기는 막지 않는다"


def test_landing_line_shows_server_values_only_and_hides_when_empty():
    """TC-PIX-06 · 랜딩 한 줄 — 서버가 준 값만 · 못 받으면 숨김 · 쿠키를 보내지 않음 · 「실시간」 · 계산값 없음 · 라우터 등록."""
    assert re.search(r'<p class="hero-ticker" id="index-ticker" hidden></p>', INDEX), "처음엔 숨겨 둔다"
    block = JS.split("async function setupTicker()", 1)[1].split("setupIntro();", 1)[0]
    assert 'fetch("/api/public/index-closes", { credentials: "omit" })' in block, "로그인 쿠키를 보내지 않는다"
    assert block.index("d.items.length === 0") < block.index("el.hidden = false"), "목록이 비면 숨긴 채 둔다"
    assert "!r.ok" in block and "catch" in block, "못 받으면(오류 · 네트워크) 숨긴 채 둔다"
    assert "${d.as_of} 종가 · 출처: ${d.source}" in block, "기준일 · 출처를 값과 같이 적는다(공공누리 제4유형)"
    for word in ("실시간", "자동매매", "등락", "change", "prev"):
        assert word not in block and word not in INDEX.split('id="index-ticker"', 1)[1].split("</p>", 1)[0], f"가공 · 과장 낱말 — {word}"
    assert not re.search(r"it\.close\s*[-+*/]", block), "종가를 계산하지 않는다(변경 금지)"
    assert ".hero-ticker[hidden] { display: none; }" in CSS
    assert "app.include_router(public_data_routes.router)" in MAIN
