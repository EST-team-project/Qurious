"""종목 찾기 API — 「찾지 못함」 은 200 · 빈 목록 + 다음에 무엇을 넣을지 (TC-SSR · DF-125 · #257 · 2026-10-17).

무엇이 틀렸었나: `GET /api/stocks/search` 가 국내 상장 목록에 없는 한글 이름(오타 · 상장폐지 · 해외 회사 한글 이름)에
502 를 줬다 — 국내 목록에서 못 찾으면 해외 자동완성으로 넘기는데, 해외 자동완성은 한글 검색어에 400(Invalid Search Query)을
주고 그 오류가 그대로 502 가 됐다. 화면 여섯이 「검색 실패」 로 읽었고 리서치 화면은 502 를 빈 목록으로 우회하고 있었다.

여기서 지키는 것 —
1. 해외 자동완성의 400 은 「찾지 못함」 — 200 · 빈 목록 + 서버 글(한글이면 「영어 이름이나 티커로」).
2. 연결 끊김 · 시간 초과 · 5xx 는 「없음」 이 아니다 — 502 그대로(말없이 빈 목록으로 바꾸지 않는다).
3. 국내 목록에서 찾으면 그 결과 그대로 · 해외 자동완성이 빈 목록이면 글을 붙인다.
4. 리서치 화면의 502 우회가 없다(서버가 고쳐졌으니 502 는 진짜 실패로 알린다).
네트워크 없이 돈다.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.routes import stocks

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "public" / "js" / "research.js"     # 깨 보기가 이 칸을 사본으로 바꿔 끼운다


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _client(handler):
    """stocks 모듈이 쓰는 httpx.AsyncClient 를 갈음 — 해외 자동완성 응답을 handler 가 정한다."""
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return handler(httpx.Request("GET", url, params=params))
    return Fake


def _status(code: int, payload: dict | None = None):
    def h(req):
        return httpx.Response(code, json=payload or {}, request=req)
    return h


@pytest.fixture
def no_krx(monkeypatch):
    async def none(q):
        return []
    monkeypatch.setattr(stocks, "search_companies", none)


@pytest.mark.anyio
async def test_korean_name_not_listed_is_not_found_not_502(monkeypatch, no_krx):
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _client(_status(400, {"finance": {"error": {"code": "Bad Request"}}})))
    out = await stocks.stock_search(q="테슬라")
    assert out["results"] == []
    assert "국내 상장 목록" in out["note"] and "티커" in out["note"] and "테슬라" in out["note"]


@pytest.mark.anyio
async def test_empty_foreign_result_also_explains(monkeypatch, no_krx):
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _client(_status(200, {"quotes": []})))
    out = await stocks.stock_search(q="zzzz")
    assert out["results"] == [] and "찾지 못했습니다" in out["note"]


@pytest.mark.anyio
@pytest.mark.parametrize("handler", [_status(503), _status(500)])
async def test_server_errors_stay_502(monkeypatch, no_krx, handler):
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _client(handler))
    with pytest.raises(HTTPException) as e:
        await stocks.stock_search(q="AAPL")
    assert e.value.status_code == 502


@pytest.mark.anyio
async def test_connection_errors_stay_502(monkeypatch, no_krx):
    def boom(req):
        raise httpx.ConnectError("연결 끊김", request=req)
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _client(boom))
    with pytest.raises(HTTPException) as e:
        await stocks.stock_search(q="AAPL")
    assert e.value.status_code == 502


@pytest.mark.anyio
async def test_listed_korean_name_returns_the_krx_rows_untouched(monkeypatch):
    rows = [{"symbol": "055550.KS", "name": "신한지주", "exchange": "KOSPI", "type": "EQUITY"}]

    async def krx(q):
        return rows
    monkeypatch.setattr(stocks, "search_companies", krx)

    def never(req):
        raise AssertionError("국내 목록에서 찾으면 해외 자동완성을 부르지 않는다")
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _client(never))
    assert await stocks.stock_search(q="신한지주") == {"results": rows}


def test_research_screen_no_longer_hides_502():
    js = RESEARCH.read_text(encoding="utf-8").replace("\r\n", "\n")
    f = js[js.index("async function fetchResearchStocks("):]
    catch = f[f.index("} catch"):f.index("\n}\n")]
    assert "status === 502" not in catch and "? [] :" not in catch     # 실패를 빈 목록으로 바꾸지 않는다
    assert "return null;" in catch
