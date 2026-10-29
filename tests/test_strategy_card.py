"""TC-CRD — 전략 카드 판 2 (인디케이터 전략 설계서 4.3 · #314 2026-10-27).

카드는 백테스트 · Pine 생성기 · 자동매매가 같은 명세를 읽는 자리라(`P02-①-2`), 칸 이름 · 값이 읽는 쪽 코드의
이름 · 범위와 같은지, 판 2 가 판 1 과 같은 매수 · 매도 판단을 내는지, 판단이 뒤 봉에 기대지 않는지를 본다.
주문 · LEAN 은 부르지 않는다. 판 1 파일은 그림자 일지 지문이라(#333) 읽기만 한다.
"""
import json
from datetime import date
from pathlib import Path
from typing import get_args

import pandas as pd
import pytest

from app.services.auto_trade import apply_strategy_spec_to_signal, evaluate_spec_rules
from app.services.collector_db import read_daily_candles
from app.services.execution_policy import ExecutionPolicy
from app.services.investment_research import backtest_strategy
from app.services.quant_pipeline import backtest, backtest_custom_indicator, preprocess
from tests.conftest import make_candles

CARDS = Path(__file__).resolve().parents[1] / "docs/phase-3/02-design/system/예시"
V1 = json.loads((CARDS / "strategy-card-ma-cross-v1.json").read_text(encoding="utf-8"))
V2 = json.loads((CARDS / "strategy-card-ma-cross-v2.json").read_text(encoding="utf-8"))
REAL_DB = Path(__file__).resolve().parents[1] / "data" / "collector" / "market.sqlite3"


def _action(card: dict, closes: list[float]) -> str:
    return apply_strategy_spec_to_signal({"action": "관망", "score": 0}, card, indicators={"closes": closes})["action"]


def test_v2_keeps_v1_fields():
    assert (V2["strategy_id"], V2["version"]) == (V1["strategy_id"], 2)
    for key in V1.keys() - {"version", "name", "position_sizing"}:
        assert V2[key] == V1[key], key
    assert V1["position_sizing"].items() <= V2["position_sizing"].items()


def test_v2_names_and_values_match_readers():
    sizing = V2["position_sizing"]
    assert sizing["size_kind"] in get_args(ExecutionPolicy.model_fields["size_kind"].annotation)
    ExecutionPolicy(size_kind=sizing["size_kind"], risk_pct=sizing["risk_pct"])   # 자동매매 수량 설정의 이름 · 범위 그대로
    stops = V2["stops"]
    assert stops["stop_kind"] in ("pct", "atr") and stops["atr_period"] == 14 and stops["atr_mult"] > 0
    assert stops["take_kind"] == "rr" and 1.5 <= stops["take_rr"] <= 3
    assert stops["judge"] in ("close", "next_open", "intrabar") and stops["lock"] == "entry"
    assert V2["reentry"] == "new_signal" and V2["price_basis"] in ("raw", "adj_base")   # 앱 OHLCV 의 가격 기준 이름(data_ohlcv)


def test_v2_fill_timing_is_what_backtest_reads_and_reports():
    df = preprocess(make_candles(120))
    out = backtest(df, pd.Series(0, index=df.index), entry_mode=V2["entry_mode"], exit_mode=V2["exit_mode"])
    assert (out["entry_mode"], out["exit_mode"]) == (V2["entry_mode"], V2["exit_mode"])


def test_v2_judge_is_what_every_backtest_response_reports():
    # 세 백테스트 모두 손절 · 익절을 apply_stops(그날 종가)로 판정한다 — 응답이 카드 판 2 의 `stops.judge` 와 같은 값을 싣는다
    df = preprocess(make_candles(120))
    plain = backtest(df, pd.Series(0, index=df.index), stop_loss_pct=5.0)
    custom = backtest_custom_indicator(make_candles(300), base="rsi_ma", stop_loss_pct=5.0)
    strategy = backtest_strategy(make_candles(400), strategy="ma", stop_loss_pct=5.0)
    assert "error" not in strategy
    assert plain["judge"] == custom["costs"]["judge"] == strategy["judge"] == V2["stops"]["judge"]


def test_warmup_bars_is_where_the_card_starts_judging():
    windows = [V2["entry"]["params"]["long_window"], V2["entry"]["params"]["short_window"], V2["stops"]["atr_period"]]
    assert V2["warmup_bars"] == max(windows)
    closes = [100.0] * V2["warmup_bars"]
    assert evaluate_spec_rules(V2, {"closes": closes[:-1]}) is None
    assert evaluate_spec_rules(V2, {"closes": closes}) is not None


def test_v2_judges_like_v1():
    closes = preprocess(make_candles(300))["close"].astype(float).tolist()
    for k in range(V2["warmup_bars"] - 5, len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V1, closes[:k]), k


def test_v2_judgment_uses_only_the_last_warmup_bars():
    closes = preprocess(make_candles(300))["close"].astype(float).tolist()
    w = V2["warmup_bars"]
    for k in range(w, len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V2, closes[k - w:k]), k


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_v2_judges_like_v1_on_005930():
    data = read_daily_candles("005930.KS", period="2y", today=date(2026, 8, 31), path=REAL_DB)
    closes = [float(c["close"]) for c in data["candles"]]
    assert len(closes) > V2["warmup_bars"]
    for k in range(V2["warmup_bars"], len(closes) + 1):
        assert _action(V2, closes[:k]) == _action(V1, closes[:k]), k


@pytest.mark.skipif(not REAL_DB.is_file(), reason="수집 DB 가 없다(CI · 새 clone)")
def test_수정주가는_원래_가격에_그날_계수를_곱한_값이라_ATR_을_원래_단위로_옮길_수_있다():
    # #366 — 판 2 의 ATR 은 수정주가로 재고 주문 · 일지는 원래 가격으로 체결한다. 식의 방향(수정 = 원래 × cum_factor)을
    # 계수가 바뀐 실제 종목에서 못 박는다: 판단 날 ATR(수정) ÷ cum_factor 가 그날 원래 가격 단위의 거리다.
    import sqlite3
    from app.services.price_basis import adjusted_to_raw

    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    try:
        code, day = con.execute(
            "SELECT srtn_cd, MAX(bas_dt) FROM price_adjusted WHERE cum_factor < 0.9 GROUP BY srtn_cd ORDER BY srtn_cd LIMIT 1").fetchone()
        rows = con.execute(
            "SELECT a.bas_dt, p.clpr, a.adj_clpr, a.cum_factor FROM price_adjusted a JOIN price_daily p USING (bas_dt, srtn_cd) "
            "WHERE a.srtn_cd = ? AND a.bas_dt <= ? ORDER BY a.bas_dt DESC LIMIT 15", (code, day)).fetchall()
        latest = con.execute("SELECT cum_factor FROM price_adjusted WHERE srtn_cd = ? ORDER BY bas_dt DESC LIMIT 1", (code,)).fetchone()[0]
    finally:
        con.close()
    assert rows and latest == pytest.approx(1.0)                       # 가장 최근 날 계수는 1 — 평소 주문에서는 단위가 같다
    for _, raw, adj, factor in rows:
        assert factor < 0.9 and adj == pytest.approx(raw * factor)      # 계수가 바뀐 앞날들 — 수정 = 원래 × 계수
        atr_adj = 0.05 * adj                                           # 수정 단위의 거리 하나(값은 아무것)
        assert adjusted_to_raw(atr_adj, factor) == pytest.approx(0.05 * raw)
