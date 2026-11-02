"""TC-SHT — 신호 적중 대조 (scripts/signal_hit_scan.py · #161 A9 · 2026-11-02)

1. 날은 공통 거래일에서 5거래일마다 하나 — 5거래일 뒤가 끝날 안에 있는 날만 뽑아 5일 뒤 수익끼리 겹치지 않는다. (TC-SHT-01)
2. 적중 = 매수 쪽은 오르면 · 매도 쪽은 내리면 · 관망은 세지 않는다(0 은 적중 아님). (TC-SHT-02)
3. 묶음 · 신뢰도 구간 집계가 손으로 센 값과 같고, 관망은 신뢰도 구간에 들어가지 않는다. (TC-SHT-03)
4. 끝날을 봉인 구간(2026-09-01 ~) 안으로 주면 읽지 않고 멈춘다. (TC-SHT-04)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("signal_hit_scan", ROOT / "scripts" / "signal_hit_scan.py")
shs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shs)


def test_sampled_days_are_horizon_apart_and_their_exit_stays_inside():
    days = [f"d{i:02d}" for i in range(23)]
    picks = shs.sample_days(days, horizon=5)
    assert picks == ["d00", "d05", "d10", "d15"]                  # d20 은 5거래일 뒤(d25)가 없다


def test_hit_counts_direction_only():
    assert shs.hit("매수", 0.01) is True and shs.hit("매수", 0.0) is False
    assert shs.hit("매도", -0.01) is True and shs.hit("매도", 0.0) is False
    assert shs.hit("관망", 0.05) is None


def test_summary_matches_hand_counts():
    rows = pd.DataFrame([
        {"signal": "매수", "strength": "강", "confidence": 0.9, "ret_5d": 0.02, "excess_5d": 0.01},
        {"signal": "매수", "strength": "보통", "confidence": 0.6, "ret_5d": -0.01, "excess_5d": -0.02},
        {"signal": "매수", "strength": "보통", "confidence": 0.3, "ret_5d": 0.03, "excess_5d": 0.0},
        {"signal": "관망", "strength": None, "confidence": 0.2, "ret_5d": 0.01, "excess_5d": 0.0},
        {"signal": "매도", "strength": "보통", "confidence": 0.6, "ret_5d": -0.04, "excess_5d": -0.03},
    ])
    s = shs.summarize(rows)
    assert s["baseline"]["n"] == 5 and s["baseline"]["up_ratio"] == pytest.approx(0.6)
    assert s["baseline"]["mean_ret_5d"] == pytest.approx(0.002)
    g = {(x["signal"], x["strength"]): x for x in s["groups"]}
    assert [(x["signal"], x["strength"]) for x in s["groups"]] == [("매수", "강"), ("매수", "보통"), ("관망", None), ("매도", "보통")]
    assert g[("매수", "보통")]["n"] == 2 and g[("매수", "보통")]["hit_ratio"] == pytest.approx(0.5)
    assert g[("매도", "보통")]["hit_ratio"] == 1.0 and g[("관망", None)]["hit_ratio"] is None
    bins = {(b["from"], b["to"]): b for b in s["confidence_bins"]}
    assert bins[(0.25, 0.5)]["n"] == 1 and bins[(0.5, 0.75)]["n"] == 2 and bins[(0.5, 0.75)]["hit_ratio"] == pytest.approx(0.5)
    assert bins[(0.0, 0.25)]["n"] == 0                           # 관망(0.2)은 적중을 세지 않아 구간에 없다
    assert sum(b["n"] for b in s["confidence_bins"]) == 4


def test_sealed_end_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["signal_hit_scan.py", "--end", "2026-09-01"])
    assert shs.main() == 2
    assert "봉인 구간" in capsys.readouterr().out
