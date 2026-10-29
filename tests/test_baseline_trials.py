"""TC-BSL — 기준 전략 시도(scripts/baseline_trials.py · 설계서 4.5 · P02-①-3) · 2026-10-29

1. 조합표 그대로 — 단기 {5, 10, 20} × 장기 {20, 40, 60, 120} · 단기 < 장기 = 11개 · 그 밖의 시도 없음. (TC-BSL-01)
2. 합격선 — D6 ⑦(교안): PF > 1.5 · MDD > −15% · 샤프 > 1.0 을 동시에. (TC-BSL-02)
3. 거래 단위 묶음 — 진입일부터 청산일까지 복리로 한 거래 · 끝까지 들고 있던 거래도 센다. (TC-BSL-03)
4. 실제 자료로 돌면 시도 11개를 모두 남기고, 다시 만든 누적 수익이 엔진 값과 같다(수집 DB 가 없으면 건너뜀). (TC-BSL-04)
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("baseline_trials", ROOT / "scripts" / "baseline_trials.py")
bt = importlib.util.module_from_spec(spec)
sys.modules["baseline_trials"] = bt
spec.loader.exec_module(bt)


def test_grid_is_the_table():
    """TC-BSL-01"""
    assert bt.GRID == [(5, 20), (5, 40), (5, 60), (5, 120), (10, 20), (10, 40), (10, 60), (10, 120), (20, 40), (20, 60), (20, 120)]
    design = (ROOT / "docs/phase-3/02-design/system/인디케이터-전략-설계.md").read_text(encoding="utf-8")
    assert "단기 {5, 10, 20} × 장기 {20, 40, 60, 120} · 단기 < 장기 | 11 |" in design


def test_pass_line():
    """TC-BSL-02"""
    assert bt.PASS == {"profit_factor": 1.5, "mdd_pct": -15.0, "sharpe_ratio": 1.0}


def test_trades_grouping():
    """TC-BSL-03"""
    idx = pd.date_range("2026-01-01", periods=8)
    held = pd.Series([0, 1, 1, 0, 0, 1, 1, 1], index=idx, dtype=float)
    net = pd.Series([0, 0.10, -0.05, 0.02, 0, 0.01, 0.01, -0.02], index=idx)
    tr = bt._trades(net, held)
    assert tr == pytest.approx([1.10 * 0.95 * 1.02 - 1, 1.01 * 1.01 * 0.98 - 1])


def test_real_run_records_every_trial():
    """TC-BSL-04"""
    try:
        bt._frame("005930.KS", date(2026, 8, 31))
    except SystemExit:
        pytest.skip("이 PC 에 수집 DB 가 없다")
    out = bt.run("005930.KS", date(2026, 8, 31))                 # 다시 만든 수익이 엔진과 다르면 run 이 멈춘다
    assert out["n_trials"] == 11 and [(r["short"], r["long"]) for r in out["trials"]] == bt.GRID
    assert out["end"] <= "2026-08-31"                             # 봉인 구간(D7) 앞까지
    for r in out["trials"]:
        assert r["pass"] == (r["profit_factor"] is not None and r["profit_factor"] > 1.5 and r["mdd_pct"] > -15 and r["sharpe_ratio"] > 1)
