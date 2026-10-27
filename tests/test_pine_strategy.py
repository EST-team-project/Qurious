"""Pine v6 `strategy()` 생성기 시험 (TC-PN) — 설계 `docs/phase-3/02-design/system/TradingView-교차검증-설계.md` 3.2 · 3.3 (`P02-③-1` · 할 일 ①-07).

지키려는 것 —
1. 같은 카드 → 같은 코드(바이트 동일) · 카드가 바뀌면 첫 줄 지문과 코드가 바뀐다.
2. 코드에서 다시 뽑은 숫자(기간 · 수수료 · 슬리피지 · 시작 자본 · 수량 식)가 카드 값과 같다 — 컴파일은 TradingView 에서 손으로 한 번 확인한다.
3. 비목표(일봉이 아님 · LightGBM 가중 · 한 종목이 아님 · ma_cross 가 아님 · 수량 상한 없음)는 거부한다 — 조용히 다르게 만들지 않는다.
4. 슬리피지 환산(10bp → 틱)이 0 이 되어 통째로 빠지거나 반올림 오차가 크면 경고한다(3.3 ②).
5. 판 2 칸(손절 · 익절 · 수량 방식 · 다시 진입)은 신장환 님 A1 확정 전이라 **코드에 옮기지 않고** 경고로 남긴다.
"""
from __future__ import annotations

import copy
import json

import pytest

from app.services import pine_strategy as ps

SPEC = {
    "strategy_id": "ma_cross_kr", "version": 2, "universe": ["005930"], "timeframe": "1d",
    "entry": {"indicator": "ma_cross", "condition": "short_above_long", "params": {"short_window": 20, "long_window": 60}},
    "exit": {"indicator": "ma_cross", "condition": "short_below_long", "params": {"short_window": 20, "long_window": 60}},
    "signal_weights": {"technical": 1.0, "lightgbm": 0, "buy_threshold": 0.25, "sell_threshold": -0.25},
    "position_sizing": {"max_position_pct": 10, "max_symbols": 1},
}


def gen(spec=None, **kw):
    kw.setdefault("ref_price", 70000)
    kw.setdefault("mintick", 100)
    return ps.generate(copy.deepcopy(spec or SPEC), **kw)


def test_pn01_same_card_same_bytes_and_a_changed_card_changes_the_fingerprint():
    """TC-PN-01 · 같은 카드는 바이트까지 같은 코드 · 카드 한 값이 바뀌면 첫 줄 지문과 코드가 바뀐다 · 시각 같은 비결정 값이 없다."""
    a, b = gen(), gen()
    assert a.code == b.code and a.sha12 == b.sha12
    first = a.code.splitlines()[1]
    assert first == f"// Qurious card ma_cross_kr v2 sha256:{a.sha12}" and len(a.sha12) == 12
    changed = copy.deepcopy(SPEC)
    changed["entry"]["params"]["long_window"] = changed["exit"]["params"]["long_window"] = 90
    c = gen(changed)
    assert c.sha12 != a.sha12 and c.code != a.code
    reordered = json.loads(json.dumps(SPEC, sort_keys=True))               # 키 순서만 다른 같은 카드
    assert gen(reordered).code == a.code
    assert not any(w in a.code for w in ("timenow", "time(", "year(", "month("))


def test_pn02_values_read_back_from_the_code_equal_the_card():
    """TC-PN-02 · 코드에서 뽑은 숫자가 카드 · 입력 값과 같다 — 기간 · 비중 · 시작 자본 · 수수료 · 슬리피지 틱 · 피라미딩 0 · v6 strategy()."""
    r = gen(initial_capital=10_000_000)
    got = ps.read_back(r.code)
    assert got == {"version": 6, "declaration": "strategy", "initial_capital": 10_000_000, "commission_type": "percent",
                   "commission_value": "0.105", "slippage_ticks": 1, "pyramiding": 0, "process_orders_on_close": False,
                   "short_len": 20, "long_len": 60, "position_pct": 10, "entry_cond": "fast > slow", "exit_cond": "fast < slow",
                   "daily_only": True}
    assert "indicator(" not in r.code.replace("strategy(", ""), "indicator() 로는 Strategy Tester 가 켜지지 않는다"
    assert r.extracted == got


def test_pn03_commission_is_one_way_fee_plus_half_the_sell_tax_and_round_trip_stays_021():
    """TC-PN-03 · 편도 근사 = 수수료 + 매도세 ÷ 2 (0.015 + 0.18 ÷ 2 = 0.105) · 왕복 합계 0.21 · 값은 입력으로 바꿀 수 있고 코드에 그대로 나온다."""
    r = gen()
    assert r.commission_one_way_pct == "0.105" and r.commission_round_trip_pct == "0.21"
    custom = gen(fee_pct="0.02", sell_tax_pct="0.20")
    assert custom.commission_one_way_pct == "0.12" and ps.read_back(custom.code)["commission_value"] == "0.12"
    assert custom.commission_round_trip_pct == "0.24"


@pytest.mark.parametrize("ref,tick,ticks,warn", [
    (70000, 100, 1, "반올림"),       # 10bp = 70원 = 0.7틱 → 1틱(14.3bp) — 환산 오차
    (100000, 100, 1, None),         # 10bp = 100원 = 정확히 1틱
    (30000, 100, 0, "통째로 빠진"),  # 10bp = 30원 = 0.3틱 → 0틱 — 슬리피지가 사라진다
    (270000, 500, 1, "반올림"),      # 10bp = 270원 = 0.54틱 → 1틱
])
def test_pn04_slippage_ticks_conversion_warns_when_it_vanishes_or_rounds_badly(ref, tick, ticks, warn):
    """TC-PN-04 · 슬리피지 환산 `ticks = round(기준가 × 10bp ÷ mintick)` — 0 이 되어 슬리피지가 통째로 빠지거나 반올림 오차가 있으면 경고 · 실효 bp 를 돌려준다."""
    r = gen(ref_price=ref, mintick=tick)
    assert r.slippage_ticks == ticks and ps.read_back(r.code)["slippage_ticks"] == ticks
    assert r.slippage_effective_bp == pytest.approx(ticks * tick / ref * 10000)
    text = " ".join(r.warnings)
    assert (warn in text) if warn else ("슬리피지" not in text)


def test_pn05_without_price_or_tick_slippage_is_zero_and_says_so():
    """TC-PN-05 · 기준가나 호가 단위를 모르면 슬리피지를 0 으로 두되 경고한다 — 조용히 만들지 않는다."""
    r = ps.generate(copy.deepcopy(SPEC))
    assert r.slippage_ticks == 0 and any("슬리피지" in w and "호가" in w for w in r.warnings)


@pytest.mark.parametrize("mutate,why", [
    (lambda s: s.__setitem__("timeframe", "1h"), "일봉"),
    (lambda s: s["signal_weights"].__setitem__("lightgbm", 0.3), "LightGBM"),
    (lambda s: s["entry"].__setitem__("indicator", "momentum"), "ma_cross"),
    (lambda s: s["position_sizing"].pop("max_position_pct"), "max_position_pct"),
    (lambda s: s["entry"]["params"].__setitem__("short_window", 90), "짧은"),
    (lambda s: s["entry"].__setitem__("condition", "never"), "조건"),
])
def test_pn06_non_goals_are_refused_with_a_reason(mutate, why):
    """TC-PN-06 · 일봉이 아님 · LightGBM 가중 · ma_cross 가 아님 · 수량 상한 없음 · 짧은 창이 더 김 · 모르는 조건 — 거부하고 까닭을 말한다."""
    spec = copy.deepcopy(SPEC)
    mutate(spec)
    with pytest.raises(ps.GenerationError, match=why):
        ps.generate(spec, ref_price=70000, mintick=100)


def test_pn07_one_symbol_at_a_time():
    """TC-PN-07 · 종목이 둘 이상이면 한 종목씩 — symbol 이 필요하고 유니버스 안이어야 한다 · 하나뿐이면 생략 가능 · 코드에는 심볼이 들어가지 않는다."""
    two = copy.deepcopy(SPEC)
    two["universe"] = ["005930", "000660"]
    with pytest.raises(ps.GenerationError, match="한 종목씩"):
        ps.generate(two, ref_price=70000, mintick=100)
    with pytest.raises(ps.GenerationError, match="유니버스"):
        ps.generate(two, symbol="035420", ref_price=70000, mintick=100)
    r = ps.generate(two, symbol="000660", ref_price=70000, mintick=100)
    assert "universe: 000660" in r.code and "005930" not in r.code.split("strategy(", 1)[1], "차트에서 사용자가 종목을 고른다 — 심볼은 주석에만"
    assert "universe: 005930" in gen().code


def test_pn08_v2_fields_are_listed_but_not_translated():
    """TC-PN-08 · 판 2 칸은 신장환 님 #314 제안(2026-10-27 · 확정 전)의 **중첩 위치**로 찾는다 — position_sizing 안의 size_kind · risk_pct, stops 안의 judge · lock,
    최상위의 entry_mode · exit_mode · reentry · warmup_bars · price_basis. 코드로 옮기지 않고 경고로 남긴다 — strategy.exit 가 없고, 조용히 빠지는 칸이 없다."""
    spec = copy.deepcopy(SPEC)
    spec["position_sizing"].update(size_kind="risk_pct", risk_pct=1.0)
    spec.update(stops={"stop_kind": "atr", "atr_period": 14, "atr_mult": 2.0, "take_kind": "rr", "take_rr": 2.0, "judge": "close", "lock": "entry"},
                reentry="new_signal", entry_mode="open", exit_mode="open", warmup_bars=60, price_basis="adjusted")
    r = ps.generate(spec, ref_price=70000, mintick=100)
    assert set(r.skipped_v2) == {"stops", "reentry", "entry_mode", "exit_mode", "warmup_bars", "price_basis",
                                 "position_sizing.size_kind", "position_sizing.risk_pct"}
    assert "strategy.exit" not in r.code and "atr" not in r.code.lower()
    assert any("판 2" in w and "A1" in w and "position_sizing.size_kind" in w for w in r.warnings)
    legacy = copy.deepcopy(SPEC)                                    # 예전 초안의 최상위 이름도 놓치지 않는다
    legacy.update(size_kind="risk_pct", judge="close")
    assert set(ps.generate(legacy, ref_price=70000, mintick=100).skipped_v2) == {"size_kind", "judge"}
    assert gen().skipped_v2 == []


def test_pn09_signal_is_a_state_not_a_cross_and_entries_never_pyramid():
    """TC-PN-09 · 진입은 교차 순간이 아니라 상태(fast > slow) · 포지션이 없을 때만 진입 · 청산은 반대 상태 · 일봉이 아니면 실행을 멈춘다 · 조건 방향이 카드대로 뒤집힌다."""
    code = gen().code
    assert "strategy.position_size == 0" in code and "strategy.position_size > 0" in code
    assert "ta.crossover" not in code and "ta.crossunder" not in code
    assert "if not timeframe.isdaily" in code and "runtime.error(" in code
    flipped = copy.deepcopy(SPEC)
    flipped["entry"]["condition"], flipped["exit"]["condition"] = "short_below_long", "short_above_long"
    got = ps.read_back(gen(flipped).code)
    assert (got["entry_cond"], got["exit_cond"]) == ("fast < slow", "fast > slow")


def test_pn10_cli_writes_the_file_next_to_the_card(tmp_path, capsys):
    """TC-PN-10 · 명령줄 — 카드 JSON 에서 .pine 파일을 쓰고 지문 · 경고를 화면에 보인다(10-28 실제 CSV 때 같은 Pine 을 붙여 넣는 길)."""
    card = tmp_path / "card.json"
    card.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "ma_cross_kr.pine"
    rc = ps.main([str(card), "--ref-price", "70000", "--mintick", "100", "--out", str(out)])
    assert rc == 0 and out.read_text(encoding="utf-8") == gen().code
    shown = capsys.readouterr().out
    assert gen().sha12 in shown and "반올림" in shown
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**SPEC, "timeframe": "1h"}), encoding="utf-8")
    assert ps.main([str(bad), "--out", str(tmp_path / "x.pine")]) == 2 and not (tmp_path / "x.pine").exists()
