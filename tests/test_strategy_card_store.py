"""TC-SCU — 전략 카드 저장(U6 · 기본 인디케이터 전략 화면 · #392) — app/services/strategy_card_store.py · app/routes/indicator_strategy.py
· app/routes/strategy_cards.py 의 목록이 사용자 카드도 읽는 길 · 2026-10-29

#392 이동원 님 조건 셋을 잰다.
1. 저장 → 목록 → Pine 내려받기가 이어진다 — 저장한 카드가 「카드 → Pine」 목록에 나오고 코드가 나온다. (TC-SCU-01)
2. 사용자마다 따로 — 다른 사용자의 카드는 목록 · Pine · 지우기 어디에도 안 보인다. 예시 카드는 모두에게. (TC-SCU-02)
3. id · 경로 보호 — 이름 칸은 영문 소문자 · 숫자 · - 만 · 경로 문자 거부 · 예시 카드 id 로 덮어쓰기 금지 · 사용자 id 도 경로로 안 씀. (TC-SCU-03)
4. 카드 꼴 — 판 2 예시와 칸 이름 · 자리가 같고 화면이 고친 칸만 바뀐다 · 범위 밖 값은 까닭과 함께 422. (TC-SCU-04)
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import indicator_strategy, strategy_cards
from app.services import strategy_card_store

U1, U2 = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000b2"
FORM = {"slug": "ma-cross-10-60", "name": "이동평균 교차 10 · 60", "symbol": "005930.KS", "short_window": 10, "long_window": 60,
        "atr_period": 14, "atr_mult": 2.5, "take_rr": 2, "risk_pct": 1, "max_position_pct": 30, "max_symbols": 5,
        "entry_mode": "open", "exit_mode": "open", "judge": "close"}


@pytest.fixture()
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATEGY_CARD_DIR", str(tmp_path / "cards"))

    def make(uid):
        app = FastAPI()
        app.include_router(strategy_cards.router)
        app.include_router(indicator_strategy.router)
        app.dependency_overrides[get_current_user] = lambda: {"id": uid, "roles": []}
        return TestClient(app)
    return make(U1), make(U2)


def test_save_list_pine(clients, tmp_path):
    """TC-SCU-01"""
    c1, _ = clients
    res = c1.post("/api/indicator-strategy/cards", json=FORM)
    assert res.status_code == 200, res.text
    card_id = res.json()["id"]
    assert card_id == "strategy-card-ma-cross-10-60"
    assert (tmp_path / "cards" / U1 / f"{card_id}.json").is_file()
    listed = {c["id"]: c for c in c1.get("/api/strategy-cards").json()["cards"]}
    assert {"strategy-card-ma-cross-v1", "strategy-card-ma-cross-v2", card_id} <= set(listed)
    assert listed[card_id]["generatable"] is True and listed[card_id]["universe"] == ["005930"]
    pine = c1.get(f"/api/strategy-cards/{card_id}/pine", params={"ref_price": 70000, "mintick": 100})
    assert pine.status_code == 200, pine.text
    body = pine.json()
    assert body["code"].startswith("//@version=6") and "strategy(" in body["code"] and body["skipped_v2"] == []
    mine = c1.get("/api/indicator-strategy/cards").json()
    assert [c["id"] for c in mine["cards"]] == [card_id] and mine["template"]["strategy_id"] == "ma_cross_20_60"


def test_users_do_not_see_each_other(clients):
    """TC-SCU-02"""
    c1, c2 = clients
    card_id = c1.post("/api/indicator-strategy/cards", json=FORM).json()["id"]
    ids2 = {c["id"] for c in c2.get("/api/strategy-cards").json()["cards"]}
    assert card_id not in ids2 and {"strategy-card-ma-cross-v1", "strategy-card-ma-cross-v2"} <= ids2
    assert c2.get(f"/api/strategy-cards/{card_id}/pine").status_code == 404
    assert c2.get("/api/indicator-strategy/cards").json()["cards"] == []
    assert c2.delete(f"/api/indicator-strategy/cards/{card_id}").status_code == 404
    assert c1.delete(f"/api/indicator-strategy/cards/{card_id}").status_code == 200
    assert card_id not in {c["id"] for c in c1.get("/api/strategy-cards").json()["cards"]}


@pytest.mark.parametrize("slug", ["../x", "a/b", "A-upper", "", "x" * 41, "-lead", "ma cross"])
def test_slug_and_path_defense(clients, tmp_path, slug):
    """TC-SCU-03"""
    c1, _ = clients
    res = c1.post("/api/indicator-strategy/cards", json={**FORM, "slug": slug})
    assert res.status_code == 422 and "카드 이름" in res.json()["detail"]
    assert not any((tmp_path / "cards").rglob("*.json")) if (tmp_path / "cards").exists() else True


def test_example_ids_and_user_id_are_protected(clients, tmp_path):
    """TC-SCU-03"""
    c1, _ = clients
    res = c1.post("/api/indicator-strategy/cards", json={**FORM, "slug": "ma-cross-v2"})
    assert res.status_code == 422 and "예시 카드" in res.json()["detail"]
    example = json.loads((strategy_cards.CARD_DIR / "strategy-card-ma-cross-v2.json").read_text(encoding="utf-8"))
    assert example["strategy_id"] == "ma_cross_20_60"                                 # 예시 파일은 그대로
    with pytest.raises(strategy_card_store.CardError):
        strategy_card_store.user_dir("../../etc")
    assert strategy_cards._files("../../etc").keys() == strategy_cards._files().keys()   # 이상한 사용자 id 는 예시만


def test_template_matches_example_file(monkeypatch, tmp_path):
    """TC-SCU-04 — 이미지에 docs/ 가 없을 때 쓰는 코드 안 값이 판 2 예시 파일과 같다"""
    assert strategy_card_store.TEMPLATE_V2 == json.loads(strategy_card_store.TEMPLATE.read_text(encoding="utf-8"))
    monkeypatch.setattr(strategy_card_store, "TEMPLATE", tmp_path / "없음.json")
    assert strategy_card_store.template() == strategy_card_store.TEMPLATE_V2
    assert strategy_card_store.template() is not strategy_card_store.TEMPLATE_V2       # 고쳐도 원본이 안 바뀌게 복사


def test_card_shape_and_ranges(clients):
    """TC-SCU-04"""
    c1, _ = clients
    card = c1.post("/api/indicator-strategy/cards", json=FORM).json()["card"]
    tpl = strategy_card_store.template()
    assert list(card) == list(tpl) and list(card["stops"]) == list(tpl["stops"])              # 칸 이름 · 자리 그대로
    assert list(card["position_sizing"]) == list(tpl["position_sizing"])
    assert card["entry"] == {"indicator": "ma_cross", "params": {"short_window": 10, "long_window": 60}, "condition": "short_above_long"}
    assert card["exit"]["condition"] == "short_below_long" and card["universe"] == ["005930"]
    assert card["stops"]["atr_mult"] == 2.5 and card["stops"]["stop_kind"] == "atr" and card["stops"]["lock"] == "entry"
    assert card["warmup_bars"] == 60 and card["reentry"] == "new_signal" and card["price_basis"] == "adj_base"
    for bad, word in [({"take_rr": 4}, "take_rr"), ({"short_window": 60}, "단기"), ({"entry_mode": "next_open"}, "entry_mode"),
                      ({"judge": "x"}, "judge"), ({"risk_pct": "a"}, "risk_pct"), ({"symbol": "../1"}, "종목")]:
        res = c1.post("/api/indicator-strategy/cards", json={**FORM, **bad})
        assert res.status_code == 422 and word in res.json()["detail"], (bad, res.text)
