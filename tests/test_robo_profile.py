"""투자성향 진단 점수화 · 목표 달성 확률 시뮬레이션."""
import pytest

from app.services.robo_profile import QUESTIONS, goal_simulation, score_answers


def _answers(idx):
    return {q["id"]: idx for q in QUESTIONS}


def test_profile_levels_by_score():
    assert score_answers(_answers(0))["level"] == "안정형"          # 7점
    assert score_answers(_answers(2))["risk_profile"] == "moderate"   # 21점 → 위험중립형
    r = score_answers(_answers(4))                                    # 연령(역순) 1점 + 나머지 5점 = 31점
    assert r["level"] == "공격투자형" and r["risk_profile"] == "aggressive"
    best = {q["id"]: max(range(len(q["options"])), key=lambda i: q["options"][i]["score"]) for q in QUESTIONS}
    assert score_answers(best)["score"] == score_answers(best)["max_score"]


def test_profile_requires_all_answers():
    a = _answers(2); del a["loss"]
    with pytest.raises(ValueError):
        score_answers(a)
    with pytest.raises(ValueError):
        score_answers({**_answers(2), "age": 9})


def test_goal_simulation_deterministic_when_no_volatility():
    r = goal_simulation(1000, 5, target_return_pct=5, expected_return_pct=8, expected_volatility_pct=0, n_paths=500)
    assert r["probability_pct"] == 100.0
    assert r["percentiles_manwon"]["p50"] == pytest.approx(1000 * 1.08 ** 5, rel=1e-3)
    r2 = goal_simulation(1000, 5, target_return_pct=10, expected_return_pct=8, expected_volatility_pct=0, n_paths=500)
    assert r2["probability_pct"] == 0.0


def test_goal_simulation_with_contributions_and_volatility():
    r = goal_simulation(1000, 3, target_return_pct=6, expected_return_pct=7, expected_volatility_pct=15,
                        monthly_contribution_manwon=50, n_paths=2000)
    assert r["invested_manwon"] == 1000 + 50 * 36
    assert 0 < r["probability_pct"] < 100
    p = r["percentiles_manwon"]
    assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]
    assert len(r["curves"]["p50"]) == len(r["curve_years"])
    assert r["required_annual_return_pct"] > 0


# ── 목표 시뮬레이션 입력 경계 — 감리 HIGH FD-FIND-002 · DF-144 (2026-10-22) ──────────
# 강사님 배포본 운영 검증이 찾은 결함: 수익률 -101 을 넣으면 서버 오류 500(422 가 맞다).
# 우리 입력 모델이 강사님 판과 같아 그대로 재현됐다 → 계산 전에 막고, 계산이 넘친 조합도 422 로.
GOAL = "/api/ml/robo/goal-simulation"


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routes import ml

    app = FastAPI(); app.include_router(ml.router)
    app.dependency_overrides[ml.get_current_user] = lambda: {"id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"}
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("field", ["target_return_pct", "expected_return_pct"])
def test_goal_simulation_rejects_return_at_or_below_minus_100(client, field):
    """TC-RP-05 · 감리 재현 입력 -101 (과 -100) 은 500 이 아니라 422 · 화면에 보일 한국어 안내 글."""
    for bad in (-101, -100):
        r = client.post(GOAL, json={field: bad})
        assert r.status_code == 422, (field, bad, r.status_code)
        detail = r.json()["detail"]
        assert [d["loc"][-1] for d in detail] == [field]
        msg = detail[0]["msg"]
        assert "-100%" in msg and not msg.startswith(("Input should", "Value error")), msg


def test_goal_simulation_accepts_just_inside_the_bound(client):
    """TC-RP-06 · 경계 바로 안쪽(-99.9)은 그대로 계산된다(200) — 지금까지 되던 입력은 막지 않는다."""
    r = client.post(GOAL, json={"target_return_pct": -99.9, "expected_return_pct": -99.9, "n_paths": 500})
    assert r.status_code == 200, r.text
    assert 0 <= r.json()["probability_pct"] <= 100


@pytest.mark.parametrize("payload", [
    {"amount_manwon": -1}, {"amount_manwon": 10_000_001},
    {"monthly_contribution_manwon": -1}, {"monthly_contribution_manwon": 1_000_001},
    {"horizon_years": 0}, {"horizon_years": 41},
    {"target_return_pct": 1000.1}, {"expected_return_pct": 1000.1},
    {"expected_volatility_pct": -0.1}, {"expected_volatility_pct": 300.1},
])
def test_goal_simulation_other_fields_have_bounds(client, payload):
    """TC-RP-07 · 나머지 칸도 범위를 넘으면 422 — 지금까지는 0 · 1 · 40 으로 조용히 바꾸거나 계산이 넘쳤다."""
    r = client.post(GOAL, json=payload)
    assert r.status_code == 422, (payload, r.status_code)
    assert [d["loc"][-1] for d in r.json()["detail"]] == list(payload)


def test_goal_simulation_service_guards_its_own_math():
    """TC-RP-08 · 계산 함수도 스스로 막는다 — 수익률 -100% 이하 · 결과가 유한하지 않으면 ValueError(복소수 · NaN · inf 를 내보내지 않음)."""
    kw = dict(expected_volatility_pct=12, n_paths=500)
    with pytest.raises(ValueError, match="-100%"):
        goal_simulation(1000, 3, target_return_pct=-101, expected_return_pct=7, **kw)
    with pytest.raises(ValueError, match="-100%"):
        goal_simulation(1000, 3, target_return_pct=8, expected_return_pct=-101, **kw)
    with pytest.raises(ValueError, match="입력 범위"):
        goal_simulation(1e308, 40, target_return_pct=8, expected_return_pct=7, **kw)


def test_goal_simulation_route_turns_value_error_into_422(client, monkeypatch):
    """TC-RP-09 · 입력 경계가 놓친 조합의 안전판 — 계산 함수의 ValueError 는 422 와 그 글(500 아님)."""
    import app.services.robo_profile as robo_profile

    def overflow(*args, **kwargs):
        raise ValueError("계산 결과가 너무 커서 확률을 낼 수 없습니다 — 입력 범위를 확인해 주세요.")

    monkeypatch.setattr(robo_profile, "goal_simulation", overflow)
    r = client.post(GOAL, json={})
    assert r.status_code == 422
    assert "입력 범위" in r.json()["detail"]
