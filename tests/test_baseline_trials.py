"""TC-BSL — 기준 전략 시도(scripts/baseline_trials.py · 설계서 4.5 · P02-①-3) · 2026-10-29 · 10종목 110개 2026-10-30

1. 조합표 그대로 — 단기 {5, 10, 20} × 장기 {20, 40, 60, 120} · 단기 < 장기 = 11개 · 그 밖의 시도 없음. (TC-BSL-01)
2. 합격선 — D6 ⑦(교안): PF > 1.5 · MDD > −15% · 샤프 > 1.0 을 동시에. (TC-BSL-02)
3. 거래 단위 PF · 승률 — 거래마다 손익(원)으로 · 0주 거래는 따로 센다. (TC-BSL-03)
4. 실제 자료로 돌면 시도를 모두 남기고, 수량을 넣은 엔진 값과 다시 만든 누적 수익이 같다(수집 DB 가 없으면 건너뜀). (TC-BSL-04)
5. DSR(보조)의 시도 수는 조합표 11 × 종목 10 = 110 — 강민석 님 함수에 그 수를 넘긴다 · 합격 판정은 바꾸지 않는다(#363). (TC-BSL-05)
6. 종목 10개 = 2020-01-02 코스피 시가총액 상위(우선주 005935 뺌 · 수집 DB `mrkt_tot_amt`) — 수집 DB 가 없으면 건너뜀. (TC-BSL-06)
7. 합격이 없을 때만 「가장 가까운 조합」 — 넘은 기준 수 → 샤프 순 · 합격이 있으면 없음. (TC-BSL-07)
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


def test_trade_stats_by_pnl():
    """TC-BSL-03"""
    trades = [{"quantity": 10, "pnl": 300.0}, {"quantity": 5, "pnl": -100.0}, {"quantity": 0, "pnl": 0.0},
              {"quantity": 7, "pnl": -100.0}]
    st = bt._trade_stats(trades)
    assert st == {"trades": 3, "zero_qty_trades": 1, "win_rate_trade_pct": 33.33, "profit_factor": 1.5}


def test_real_run_records_every_trial():
    """TC-BSL-04"""
    try:
        bt._frame("005930.KS", date(2026, 8, 31))
    except SystemExit:
        pytest.skip("이 PC 에 수집 DB 가 없다")
    out = bt.run_all(date(2026, 8, 31), ["005930.KS"])            # 다시 만든 수익이 엔진과 다르면 run 이 멈춘다
    assert out["n_trials"] == 11 and out["dsr_n_trials"] == 110
    assert [(r["short"], r["long"]) for r in out["trials"]] == bt.GRID
    assert out["symbols"][0]["end"] <= "2026-08-31"               # 봉인 구간(D7) 앞까지
    assert out["card"]["position_sizing"]["risk_pct"] == 1.0
    for r in out["trials"]:
        assert r["pass"] == bt._passed(r)
        assert r["avg_weight_pct"] is None or 0 < r["avg_weight_pct"] <= 30


def test_dsr_uses_table_size(monkeypatch):
    """TC-BSL-05"""
    seen = {}
    real = bt.evaluation_risk.calculate_all_metrics

    def spy(returns, **k):
        seen.update(k)
        return real(returns, **k)

    monkeypatch.setattr(bt.evaluation_risk, "calculate_all_metrics", spy)
    net = pd.Series([0.01, -0.005, 0.002, 0.0, 0.004] * 60)
    v = bt._dsr(net)
    assert seen["n_trials"] == len(bt.GRID) * len(bt.SYMBOLS) == 110
    assert v is not None and 0 <= v <= 1


def test_symbols_are_first_day_kospi_top10():
    """TC-BSL-06"""
    import sqlite3
    db = ROOT / "data" / "collector" / "market.sqlite3"
    if not db.is_file():
        pytest.skip("이 PC 에 수집 DB 가 없다")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    top = [r[0] for r in c.execute("SELECT srtn_cd FROM price_daily WHERE bas_dt='20200102' AND mrkt_ctg='KOSPI' "
                                   "ORDER BY mrkt_tot_amt DESC LIMIT 11")]
    assert "005935" in top
    assert [s[:6] for s in bt.SYMBOLS] == [x for x in top if x != "005935"]


def test_nearest_only_without_pass():
    """TC-BSL-07"""
    base = {"symbol": "A", "short": 5, "long": 20, "pass": False}
    rows = [base | {"profit_factor": 1.6, "mdd_pct": -20.0, "sharpe_ratio": 0.4},
            base | {"long": 40, "profit_factor": 1.2, "mdd_pct": -10.0, "sharpe_ratio": 0.9},
            base | {"long": 60, "profit_factor": 1.7, "mdd_pct": -12.0, "sharpe_ratio": 0.5}]
    assert bt.nearest(rows) == {"symbol": "A", "short": 5, "long": 60, "criteria_met": 2}
    assert bt.nearest(rows + [base | {"profit_factor": 2.0, "mdd_pct": -5.0, "sharpe_ratio": 1.2, "pass": True}]) is None
