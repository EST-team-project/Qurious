"""TC-PLP — 수집 회차 프로파일 (scripts/pipeline_profile.py · 설계 `수집-파이프라인-분리-병렬화-설계.md` · 강사님 피드백 10-30)

읽기 전용 도구이므로 합성 회차로 계산을, 소스로 「안 쓴다 · 단계 이름이 러너와 같다」 를 본다.
1. 의존 모델 앞뒤(모르는 단계 · 순환)와 일부러 깬 모델을 잡는다. (TC-PLP-01)
2. 계산 — 순차 = 합 · 일꾼이 늘수록 줄지만 하한(가장 긴 사슬)보다 작아지지 않고 · 같은 자원에 쓰는 단계는 안 겹친다. (TC-PLP-02)
3. 의존 모델의 단계 이름이 러너 `STEPS` 와 같다(드리프트 방지) · 읽기 전용(쓰기 호출 없음). (TC-PLP-03)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_profile as pp  # noqa: E402


def test_dependency_model_is_consistent_and_catches_a_broken_one():
    """TC-PLP-01 · 모델 앞뒤 — 실제 모델은 통과하고, 모르는 단계 · 순환을 넣으면 잡는다."""
    assert pp.check_model() == []
    assert any("단계 목록에 없다" in m for m in pp.check_model({"a": ["zzz"], "b": []}))
    assert "순환" in " ".join(pp.check_model({"a": ["b"], "b": ["a"]}))
    assert set(pp.RESOURCE) == set(pp.DEPS)


def test_scenarios_respect_dependencies_resources_and_the_lower_bound():
    """TC-PLP-02 · 합성 회차 — 순차 = 합 · 일꾼이 늘면 줄지만 하한 아래로 안 내려가고 · 같은 자원(수집 DB 쓰기)은 겹치지 않는다."""
    sec = {"price": 10.0, "dividend": 10.0, "calendar": 5.0, "adjusted": 100.0, "search": 80.0}
    order = ["price", "dividend", "search", "calendar", "adjusted"]
    total = sum(sec.values())
    assert pp.simulate(sec, order, 1, use_resource=False) == pytest.approx(total)
    cp = pp.critical_path(sec)
    assert cp["path"] == ["dividend", "calendar", "adjusted"] or cp["path"][-1] == "adjusted"
    assert cp["seconds"] == pytest.approx(10 + 5 + 100)                    # dividend → calendar → adjusted
    free = pp.simulate(sec, order, 3, use_resource=False)
    assert cp["seconds"] - 1e-9 <= free < total, "일꾼이 늘면 줄지만 하한 아래로는 못 간다"
    # 수집 DB 쓰기 단계끼리는 겹치지 않는다 — price · dividend · calendar · adjusted 는 한 줄(125초) · search 만 겹친다
    safe = pp.simulate(sec, order, 3)
    assert safe == pytest.approx(10 + 10 + 5 + 100)
    assert safe >= free
    # search 는 자기 파일이라 수집 DB 쓰기 줄과 겹친다 — 순차보다 search 만큼 줄어든다
    assert total - safe == pytest.approx(80.0)


def test_report_on_a_synthetic_round_and_flags_unmodeled_steps(tmp_path):
    """TC-PLP-02b · 보고서 — 묶음 · 큰 단계 · 시나리오가 나오고 모델에 없는 새 단계는 시나리오에서 빼고 알린다."""
    steps = [{"name": "price", "seconds": 5.0, "status": "ok"}, {"name": "search", "seconds": 50.0, "status": "ok"},
             {"name": "adjusted", "seconds": 40.0, "status": "ok"}, {"name": "brand_new_step", "seconds": 9.0, "status": "ok"}]
    rep = pp.report(steps, {"price": "받기", "search": "계산", "adjusted": "계산"})
    assert rep["total_seconds"] == 104.0 and rep["unmodeled_steps"] == ["brand_new_step"]
    assert rep["groups"] == {"받기": 5.0, "계산": 90.0, "?": 9.0}
    assert rep["top"][0]["name"] == "search"
    assert rep["scenarios"]["지금(순차 · 일꾼 1)"] == 95.0, "모델 밖 단계는 시나리오에서 뺀다"
    f = tmp_path / "last.json"
    f.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    assert pp.load_steps(f)[1]["seconds"] == 50.0
    assert "큰 단계" in pp.render(rep) and "brand_new_step" in pp.render(rep)
    assert pp.main(["--file", str(tmp_path / "없는파일.json")]) == 1


def test_model_step_names_match_the_runner_and_tool_is_read_only():
    """TC-PLP-03 · 의존 모델의 단계 이름이 러너 STEPS 와 같다(러너에 단계가 늘면 이 시험이 알려 준다) · 도구는 쓰지 않는다."""
    import re
    runner = (ROOT / "scripts" / "daily_update.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'^\s*Step\("([a-z_]+)"', runner, flags=re.M))
    assert declared, "러너에서 단계 이름을 못 읽었다"
    missing = declared - set(pp.DEPS)
    assert not missing, f"러너에 새로 생긴 단계가 의존 모델에 없다 — DEPS · RESOURCE 에 더한다: {sorted(missing)}"
    extra = set(pp.DEPS) - declared - {"manifest", "export", "verify", "upload", "ohlcv_upload", "journal_upload", "sector_laws"}
    assert not extra, f"의존 모델에만 있는 단계(러너에서 사라졌나): {sorted(extra)}"
    src = (ROOT / "scripts" / "pipeline_profile.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "open(", ".unlink(", "subprocess", "sqlite3"):
        assert forbidden not in src.split('"""', 2)[2], f"읽기 전용 도구가 {forbidden} 를 쓴다"


def test_history_stats_use_many_rounds_and_skip_single_step_reruns(tmp_path):
    """TC-PLP-04 · 회차 이력 — 한 단계만 다시 돌린 줄은 빼고, 단계마다 최소 · 중앙값 · 최대 · 폭(날마다 다른 정도)을 낸다."""
    def rnd(search, adjusted, n=20):
        steps = [{"name": f"s{i}", "seconds": 1.0} for i in range(n)]
        steps += [{"name": "search", "seconds": search}, {"name": "adjusted", "seconds": adjusted}]
        return {"started_at": "x", "steps": steps}
    lines = [rnd(468.4, 331), {"only": "search", "steps": [{"name": "search", "seconds": 4.6}]}, rnd(457.3, 330), rnd(13.0, 190)]
    f = tmp_path / "history.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    h = pp.history_stats(f)
    assert h["rounds"] == 3, "한 단계만 다시 돌린 줄 · 깨진 줄은 회차가 아니다"
    s = h["steps"]["search"]
    assert (s["n"], s["min"], s["median"], s["max"]) == (3, 13.0, 457.3, 468.4) and s["spread"] == 455.4
    assert h["steps"]["adjusted"]["spread"] == 141.0
    text = pp.render_history(h)
    assert text.index("search") < text.index("adjusted"), "폭이 큰 단계가 먼저"
    assert "평균을 믿기 이르다" in text, "회차가 5번 아래면 경고한다"
    assert pp.history_stats(tmp_path / "없음.jsonl") == {"rounds": 0, "steps": {}}
