"""Pine v6 `strategy()` 생성기 시험 (TC-PN) — 설계 `docs/phase-3/02-design/system/TradingView-교차검증-설계.md` 3.2 · 3.3 (`P02-③-1` · 할 일 ①-07).

지키려는 것 —
1. 같은 카드 → 같은 코드(바이트 동일) · 카드가 바뀌면 첫 줄 지문과 코드가 바뀐다.
2. 코드에서 다시 뽑은 숫자(기간 · 수수료 · 슬리피지 · 시작 자본 · 수량 식)가 카드 값과 같다 — 컴파일은 TradingView 에서 손으로 한 번 확인한다.
3. 비목표(일봉이 아님 · LightGBM 가중 · 한 종목이 아님 · ma_cross 가 아님 · 수량 상한 없음)는 거부한다 — 조용히 다르게 만들지 않는다.
4. 슬리피지 환산(10bp → 틱)이 0 이 되어 통째로 빠지거나 반올림 오차가 크면 경고한다(3.3 ②).
5. 판 2 카드(`stops` 가 있는 카드 · 설계서 v0.5)는 손절 · 익절 · 위험 % 수량 · 체결 시점 · 새 신호 재진입 · 워밍업을 코드로 옮기고(PN-11), 모르는 값은 거부한다(PN-12).
   `stops` 가 없는 카드에 판 2 칸이 따로 있으면 옮기지 않고 경고로 남긴다(PN-08).
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
    """TC-PN-08 · `stops` 가 없는 카드에 판 2 칸이 따로 있으면 **중첩 위치**로 찾아(position_sizing 안의 size_kind · risk_pct,
    최상위의 entry_mode · exit_mode · reentry · warmup_bars · price_basis) 코드로 옮기지 않고 경고로 남긴다 — 손절 코드가 없고, 조용히 빠지는 칸이 없다.
    (`stops` 가 있는 판 2 카드는 PN-11 에서 코드로 옮긴다.)"""
    spec = copy.deepcopy(SPEC)
    spec["position_sizing"].update(size_kind="risk_pct", risk_pct=1.0)
    spec.update(reentry="new_signal", entry_mode="open", exit_mode="open", warmup_bars=60, price_basis="adjusted")
    r = ps.generate(spec, ref_price=70000, mintick=100)
    assert set(r.skipped_v2) == {"reentry", "entry_mode", "exit_mode", "warmup_bars", "price_basis",
                                 "position_sizing.size_kind", "position_sizing.risk_pct"}
    assert "strategy.exit" not in r.code and "atr" not in r.code.lower()
    assert any("판 2" in w and "stops" in w and "position_sizing.size_kind" in w for w in r.warnings)
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


V2_CARD = "docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v2.json"


def v2_spec():
    from pathlib import Path
    return json.loads(Path(V2_CARD).read_text(encoding="utf-8"))


def test_pn11_v2_card_is_translated_and_values_read_back_equal_the_card():
    """TC-PN-11 · 판 2 카드(`stops` 가 있는 카드 — 신장환 님 #353 예시)는 코드로 옮긴다: ATR 손절 · rr 익절 · 위험 % 수량 · 워밍업 · 새 신호 재진입.
    코드에서 다시 뽑은 값이 카드 값과 같고, 손절 · 익절선은 진입 체결가(슬리피지 포함 `position_avg_price`)에서 잰다(사용자 결정 2026-10-27)."""
    spec = v2_spec()
    a = ps.generate(copy.deepcopy(spec), ref_price=70000, mintick=100)
    assert a.code == ps.generate(copy.deepcopy(spec), ref_price=70000, mintick=100).code, "같은 카드 → 같은 바이트"
    assert a.skipped_v2 == [] and "생성기 v0.2" in a.code.splitlines()[2]
    got = ps.read_back(a.code)
    stops, sizing = spec["stops"], spec["position_sizing"]
    assert (got["risk_pct"], got["position_pct"]) == (sizing["risk_pct"], sizing["max_position_pct"])
    assert (got["atr_period"], got["atr_mult"], got["take_rr"]) == (stops["atr_period"], stops["atr_mult"], stops["take_rr"])
    assert got["warmup_bars"] == spec["warmup_bars"] and got["judge"] == "close" and got["new_signal_guard"]
    assert got["process_orders_on_close"] is False, "entry_mode · exit_mode = open → 다음 봉 시가 체결"
    code = a.code
    assert "stopPx := strategy.position_avg_price - atrMult * atrEntry" in code
    assert "takePx := strategy.position_avg_price + takeRr * (strategy.position_avg_price - stopPx)" in code
    assert "stopHit = strategy.position_size > 0 and close <= stopPx" in code and "takeHit = strategy.position_size > 0 and close >= takePx" in code
    assert "qty = math.min(riskQty, capQty)" in code and "atrEntry := atrNow" in code, "수량은 위험 금액과 비중 상한 중 작은 쪽 · ATR 은 판단 봉 값을 고정"
    assert "strategy.exit" not in code
    assert any("adj_base" in w and "수정주가" in w for w in a.warnings)
    v1 = gen()                                                      # 판 1 카드는 그대로 — 판 2 코드가 섞이지 않는다
    assert "생성기 v0.1" in v1.code.splitlines()[2] and "atrPeriod" not in v1.code and "stopPx" not in v1.code
    assert "risk_pct" not in ps.read_back(v1.code)


@pytest.mark.parametrize("mutate,why", [
    (lambda s: s["stops"].update(judge="next_open"), "next_open"),
    (lambda s: s["stops"].update(judge="weird"), "judge"),
    (lambda s: s["stops"].update(stop_kind="percent"), "stop_kind"),
    (lambda s: s["stops"].update(take_kind="fixed"), "take_kind"),
    (lambda s: s["stops"].update(lock="trailing"), "lock"),
    (lambda s: s.update(exit_mode="close"), "entry_mode"),
    (lambda s: s.update(reentry="immediate"), "reentry"),
    (lambda s: s["position_sizing"].update(size_kind="fixed_budget"), "fixed_budget"),
    (lambda s: s["position_sizing"].update(size_kind="shares"), "size_kind"),
    (lambda s: s.update(price_basis="adjusted"), "price_basis"),
    (lambda s: s.pop("warmup_bars"), "warmup_bars"),
    (lambda s: s["stops"].update(atr_mult=0), "atr_mult"),
    (lambda s: s["position_sizing"].update(risk_pct=150), "risk_pct"),
])
def test_pn12_v2_values_the_generator_does_not_know_are_refused_with_a_reason(mutate, why):
    """TC-PN-12 · 판 2 에서 정의가 없거나 판정 봉과 체결 봉이 어긋날 수 있는 값은 조용히 다르게 만들지 않고 거부한다
    (`judge = next_open` — 신장환 님 4.3 정의 확인 전 · 설계서 8절)."""
    spec = v2_spec()
    mutate(spec)
    with pytest.raises(ps.GenerationError) as e:
        ps.generate(spec, ref_price=70000, mintick=100)
    assert why in str(e.value)


def test_pn13_intrabar_uses_strategy_exit_and_close_mode_fills_on_the_same_bar_both_with_a_warning():
    """TC-PN-13 · `judge = intrabar` 는 strategy.exit 로 만들되 대사 범위 밖이라 경고 · `entry_mode = exit_mode = close` 는 process_orders_on_close = true 와 경고."""
    spec = v2_spec()
    spec["stops"]["judge"] = "intrabar"
    r = ps.generate(spec, ref_price=70000, mintick=100)
    assert 'strategy.exit("X", "L", stop = stopPx, limit = takePx)' in r.code and ps.read_back(r.code)["judge"] == "intrabar"
    assert "stopHit" not in r.code and any("intrabar" in w and "대사 범위 밖" in w for w in r.warnings)
    spec = v2_spec()
    spec.update(entry_mode="close", exit_mode="close")
    r = ps.generate(spec, ref_price=70000, mintick=100)
    assert ps.read_back(r.code)["process_orders_on_close"] is True
    assert any("같은 종가" in w for w in r.warnings)
