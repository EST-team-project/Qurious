"""TC-SCA — 전략 카드 → Pine v6 strategy() 내려받기 API(app/routes/strategy_cards.py) · 2026-10-29 · 화면 벤치마킹 S3

생성기(app/services/pine_strategy.py · 신장환 님 코드)는 부르기만 한다. 이 시험은 길만 잰다.
1. 목록: 카드 파일 stem 이 id · 판 1 · 판 2 모두 「만들 수 있음」 · 만들 수 없으면 까닭. (TC-SCA-01)
2. 코드: Pine v6 `strategy()` · 판 지문(fingerprint)이 생성기의 지문 함수와 같다 · 설정(properties)이 코드에서 다시 읽은 값과 같다 ·
   저장하지 않는다. (TC-SCA-02)
3. 판 2 는 ATR 손절 · 익절 · 체결 시점 칸이 코드에 옮겨진다(생성기가 판 2 로 읽은 증거 atr_period). (TC-SCA-03)
4. 입력 방어: 목록에 없는 id · 경로처럼 생긴 id → 404 · 숫자 범위 밖 → 422 · 유니버스 밖 종목 → 422(생성기 까닭 그대로). (TC-SCA-04)
5. 로그인 없이는 못 부른다 · 라우터가 main 에 등록돼 있다. (TC-SCA-05)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import strategy_cards
from app.services import pine_strategy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(strategy_cards.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000001", "roles": []}
    return TestClient(app)


def test_list_cards_from_files(client):
    """TC-SCA-01"""
    res = client.get("/api/strategy-cards")
    assert res.status_code == 200
    cards = {c["id"]: c for c in res.json()["cards"]}
    assert {"strategy-card-ma-cross-v1", "strategy-card-ma-cross-v2"} <= set(cards)
    for cid in ("strategy-card-ma-cross-v1", "strategy-card-ma-cross-v2"):
        assert cards[cid]["generatable"] is True and cards[cid]["reason"] == "" and cards[cid]["universe"] == ["005930"]
    assert cards["strategy-card-ma-cross-v1"]["version"] == 1 and cards["strategy-card-ma-cross-v2"]["version"] == 2
    files = {p.stem for p in strategy_cards.CARD_DIR.glob("strategy-card-*.json")}
    assert set(cards) == files                                                         # 파일 목록과 같다 — 새로 짓지 않는다


def test_pine_code_fingerprint_and_properties(client):
    """TC-SCA-02"""
    res = client.get("/api/strategy-cards/strategy-card-ma-cross-v1/pine", params={"ref_price": 70000, "mintick": 100})
    assert res.status_code == 200
    body = res.json()
    assert body["code"].startswith("//@version=6") and "strategy(" in body["code"] and body["declaration"] == "strategy"
    assert body["pine_version"] == 6 and body["symbol"] == "005930"
    spec = json.loads((strategy_cards.CARD_DIR / "strategy-card-ma-cross-v1.json").read_text(encoding="utf-8"))
    assert body["fingerprint"] == pine_strategy.fingerprint(spec)[:12] or body["fingerprint"] == pine_strategy.generate(spec).sha12
    p, ext = body["properties"], body["extracted"]
    assert p["initial_capital"] == ext["initial_capital"] == 10_000_000
    assert p["commission_type"] == ext["commission_type"] and p["slippage_ticks"] == ext["slippage_ticks"] == 1
    assert p["process_orders_on_close"] is False and p["timeframe"] == "1d"
    assert p["commission_one_way_pct"] == "0.105" and p["commission_round_trip_pct"] == "0.21"      # 수수료 0.015 + 매도세 0.18 ÷ 2 (생성기 근사)
    assert str(body["file"]).endswith(".json") and "코드는 저장하지 않습니다" in body["note"]
    # 기준가 · 호가 단위가 없으면 슬리피지 0 + 경고(생성기 규칙 그대로)
    bare = client.get("/api/strategy-cards/strategy-card-ma-cross-v1/pine").json()
    assert bare["properties"]["slippage_ticks"] == 0 and bare["warnings"]


def test_v2_card_carries_atr_and_stops(client):
    """TC-SCA-03"""
    body = client.get("/api/strategy-cards/strategy-card-ma-cross-v2/pine", params={"ref_price": 70000, "mintick": 100}).json()
    ext = body["extracted"]
    assert body["version"] == 2 and ext["atr_period"] > 0 and ext["atr_mult"] > 0 and ext["take_rr"] > 0
    assert ext["judge"] in ("close", "intrabar") and "atrPeriod" in body["code"]
    assert body["skipped_v2"] == []                                                    # 판 2 칸을 코드에 옮겼다


def test_input_defense(client):
    """TC-SCA-04"""
    base = "/api/strategy-cards"
    assert client.get(f"{base}/nope/pine").status_code == 404
    for bad in ("..%2F..%2Fapp%2Fmain", "strategy-card-ma-cross-v1.json", "strategy-card-../x", "%00"):
        assert client.get(f"{base}/{bad}/pine").status_code in (404, 422), bad
    ok = f"{base}/strategy-card-ma-cross-v1/pine"
    assert client.get(ok, params={"ref_price": -1}).status_code == 422
    assert client.get(ok, params={"mintick": 0}).status_code == 422
    assert client.get(ok, params={"slippage_bp": 5000}).status_code == 422
    assert client.get(ok, params={"capital": 10}).status_code == 422
    res = client.get(ok, params={"symbol": "000660"})
    assert res.status_code == 422 and "유니버스" in res.json()["detail"]               # 생성기의 까닭 그대로


def test_requires_login_and_is_registered():
    """TC-SCA-05"""
    app = FastAPI()
    app.include_router(strategy_cards.router)
    bare = TestClient(app, raise_server_exceptions=False)
    assert bare.get("/api/strategy-cards").status_code in (401, 403, 500)               # 세션 의존성이 막는다(override 없음)
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert re.search(r"from app\.routes import strategy_cards as strategy_cards_routes", main)
    assert "app.include_router(strategy_cards_routes.router)" in main
    src = (ROOT / "app" / "routes" / "strategy_cards.py").read_text(encoding="utf-8")
    assert "write_text" not in src and "open(" not in src                               # 생성한 코드를 저장하지 않는다
