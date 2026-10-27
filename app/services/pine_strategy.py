"""전략 카드(규칙 명세 JSON) → TradingView Pine v6 `strategy()` 코드 (생성기 v0.2 · 할 일 ①-07 · `P02-③-1`).

설계 `docs/phase-3/02-design/system/TradingView-교차검증-설계.md` 3.2 (카드 칸 → Pine 줄 대응표) · 3.3 (TradingView 가 우리와 구조적으로 다른 곳).
순수 함수 — 네트워크 · 시각 · 난수가 없다. **같은 카드 + 같은 입력 → 바이트까지 같은 코드**(대사표가 첫 줄 지문으로 카드를 가리킨다).

만드는 것 — 판 1 (계약 칸만; `stops` 가 없는 카드)
    일봉 · `ma_cross` 상태 판정(`fast > slow` — 교차 순간이 아니다) · 한 종목씩 · 수량 상한(`max_position_pct`) · 수수료 · 슬리피지 · 시작 자본 · `pyramiding=0`
만드는 것 — 판 2 (`stops` 가 있는 카드 · 신장환 님 #314/#353 · 설계서 v0.5)
    ATR 손절선 · 위험 비율 익절선(`take_rr`) · `risk_pct` 수량(= min(위험 금액 수량, 비중 상한 수량)) · 체결 시점(`entry_mode` · `exit_mode`) · 새 신호에서만 재진입(`reentry`)
    · 워밍업(`warmup_bars`). 손절 · 익절선은 **진입 체결가(`strategy.position_avg_price` — 슬리피지 포함, 사용자 결정 2026-10-27)** 에서 잰다.
만들지 않는 것 (조용히 다르게 만들지 않고 **거부**한다)
    일봉이 아닌 주기 · `lightgbm` 가중 > 0 · `ma_cross` 가 아닌 지표 · 수량 상한이 없는 카드 · 진입 · 청산의 이동평균 기간이 다른 카드
    · 판 2: `judge = next_open`(판정 봉과 체결 봉이 어긋날 수 있다 — 신장환 님 4.3 정의 확인 전 · 설계서 8절) · `stop_kind` 가 atr 이 아닌 것 · `take_kind` 가 rr 이 아닌 것
      · `lock` 이 entry 가 아닌 것 · `entry_mode` ≠ `exit_mode` · `reentry` 가 new_signal 이 아닌 것 · `size_kind` 가 risk_pct 가 아닌 것(`fixed_budget` 은 예산 칸이 카드에 없다)
      · `price_basis` 가 adj_base 가 아닌 것
옮기지 않는 것 (**경고**로 남긴다 — `stops` 가 없는 카드에 판 2 칸이 따로 있을 때)
    판 2 칸: `size_kind` · `judge` · `reentry` · `entry_mode` · `exit_mode` 등

컴파일 확인은 TradingView 편집기에서 손으로 한 번 한다(공식 문법 검사기가 없다). 이 모듈의 시험(`TC-PN`)은 코드에서 다시 뽑은 숫자가 카드 값과 같은지 본다.

    python -m app.services.pine_strategy card.json --ref-price 70000 --mintick 100 --out ma_cross_kr.pine
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

#: 판 2 칸 — 신장환 님 청산 칸(#161 A1) 이름이 확정되면 옮긴다. 그 전에는 코드에 넣지 않는다.
#: 최상위 이름(`size_kind` · `judge` 는 예전 초안의 자리 — 놓치지 않으려 남긴다) + #314 제안(2026-10-27 · 확정 전)의 중첩 자리.
V2_KEYS = ("stops", "size_kind", "judge", "reentry", "entry_mode", "exit_mode", "warmup_bars", "price_basis")
V2_NESTED = (("position_sizing", "size_kind"), ("position_sizing", "risk_pct"))
#: ma_cross 조건 → Pine 비교식(상태 판정)
_COND = {"short_above_long": "fast > slow", "short_below_long": "fast < slow"}


class GenerationError(ValueError):
    """이 카드는 v0.1 이 만들 수 없다 — 그 까닭 한 줄."""


@dataclass
class PineResult:
    code: str
    card_id: str
    version: int
    sha12: str
    symbol: str
    extracted: Dict
    warnings: List[str] = field(default_factory=list)
    skipped_v2: List[str] = field(default_factory=list)
    slippage_ticks: int = 0
    slippage_effective_bp: float = 0.0
    commission_one_way_pct: str = ""
    commission_round_trip_pct: str = ""


def _dec(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _num(v) -> str:
    return _dec(Decimal(str(v)))


def fingerprint(spec: Dict) -> str:
    """카드 지문 — 키 순서와 상관없는 정규 JSON 의 sha256 앞 12자."""
    canon = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def _rule(spec: Dict, key: str, label: str) -> tuple:
    rule = spec.get(key) or {}
    if not rule:
        raise GenerationError(f"{label} 규칙({key})이 카드에 없다")
    if rule.get("indicator") != "ma_cross":
        raise GenerationError(f"{label} 지표 {rule.get('indicator')!r} — v0.1 은 ma_cross 만 만든다")
    cond = rule.get("condition")
    if cond not in _COND:
        raise GenerationError(f"{label} 조건 {cond!r} 은 v0.1 이 모른다(short_above_long · short_below_long 만)")
    p = rule.get("params") or {}
    try:
        s, l = int(p.get("short_window", 5)), int(p.get("long_window", 20))
    except (TypeError, ValueError):
        raise GenerationError(f"{label} 이동평균 기간이 숫자가 아니다") from None
    if s < 1 or l < 1 or s >= l:
        raise GenerationError(f"{label}: 짧은 창({s})이 긴 창({l})보다 짧아야 한다")
    return cond, s, l


def _need(value, label: str, *, hi: Optional[float] = None, integer: bool = False):
    """0 보다 큰 유한한 숫자(``hi`` 가 있으면 그 이하, ``integer`` 면 정수)만 받는다 — 아니면 거부."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise GenerationError(f"{label} 이(가) 숫자가 아니거나 카드에 없다") from None
    if not math.isfinite(v) or v <= 0 or (hi is not None and v > hi) or (integer and v != int(v)):
        raise GenerationError(f"{label} 값 {value!r} 은(는) 범위 밖이다")
    return int(v) if integer else v


def _v2_params(spec: Dict) -> Dict:
    """판 2 카드(``stops`` 가 있는 카드)의 칸을 검사해 값을 뽑는다 — 모르는 값은 조용히 다르게 만들지 않고 거부한다."""
    stops = spec.get("stops") or {}
    sizing = spec.get("position_sizing") or {}
    if stops.get("stop_kind") != "atr":
        raise GenerationError(f"stops.stop_kind {stops.get('stop_kind')!r} — 판 2 는 atr 만 만든다")
    if stops.get("take_kind") != "rr":
        raise GenerationError(f"stops.take_kind {stops.get('take_kind')!r} — 판 2 는 rr 만 만든다")
    judge = stops.get("judge")
    if judge == "next_open":
        raise GenerationError("stops.judge = next_open — 판정 봉과 체결 봉이 Pine 에서 어긋날 수 있어(신장환 님 4.3 정의 확인 전 · 설계서 8절) 만들지 않는다")
    if judge not in ("close", "intrabar"):
        raise GenerationError(f"stops.judge {judge!r} 는 모른다(close · intrabar 만)")
    if stops.get("lock") != "entry":
        raise GenerationError(f"stops.lock {stops.get('lock')!r} — 손절선은 진입 때 고정(entry)만 만든다")
    entry_mode, exit_mode = spec.get("entry_mode"), spec.get("exit_mode")
    if entry_mode not in ("open", "close") or exit_mode not in ("open", "close"):
        raise GenerationError(f"entry_mode {entry_mode!r} · exit_mode {exit_mode!r} — open · close 만 안다")
    if entry_mode != exit_mode:
        raise GenerationError(f"entry_mode({entry_mode}) 와 exit_mode({exit_mode}) 가 다르다 — Pine 은 체결 시점을 전략 전체에 하나만 둔다(process_orders_on_close)")
    if spec.get("reentry") != "new_signal":
        raise GenerationError(f"reentry {spec.get('reentry')!r} — new_signal(청산 뒤 새 매수 신호에서만)만 만든다")
    kind = sizing.get("size_kind")
    if kind == "fixed_budget":
        raise GenerationError("position_sizing.size_kind = fixed_budget — 예산 칸 이름이 카드에 정의돼 있지 않아 만들지 않는다")
    if kind != "risk_pct":
        raise GenerationError(f"position_sizing.size_kind {kind!r} — 판 2 는 risk_pct 만 만든다")
    if spec.get("price_basis") != "adj_base":
        raise GenerationError(f"price_basis {spec.get('price_basis')!r} — adj_base 만 만든다")
    return {
        "judge": judge, "mode": entry_mode,
        "risk_pct": _need(sizing.get("risk_pct"), "position_sizing.risk_pct", hi=100),
        "atr_period": _need(stops.get("atr_period"), "stops.atr_period", integer=True),
        "atr_mult": _need(stops.get("atr_mult"), "stops.atr_mult"),
        "take_rr": _need(stops.get("take_rr"), "stops.take_rr"),
        "warmup_bars": _need(spec.get("warmup_bars"), "warmup_bars", integer=True),
    }


def generate(spec: Dict, *, symbol: Optional[str] = None, ref_price: Optional[float] = None, mintick: Optional[float] = None,
             fee_pct="0.015", sell_tax_pct="0.18", slippage_bp=10, initial_capital: int = 10_000_000) -> PineResult:
    """카드 한 장 → Pine v6 코드 한 벌. 만들 수 없으면 ``GenerationError``.

    ``ref_price`` · ``mintick`` — 슬리피지(bp)를 TradingView 의 틱 단위로 바꾸는 입력(3.3 ②). 없으면 슬리피지 0 으로 두고 경고한다.
    수수료는 편도 근사 = 수수료 + 매도세 ÷ 2 (3.3 ③ · 제안 0.105%) — 왕복 합계는 0.21% 로 같다.
    """
    if str(spec.get("timeframe") or "1d") != "1d":
        raise GenerationError(f"카드 timeframe {spec.get('timeframe')!r} — v0.1 은 일봉(1d)만 만든다")
    if float((spec.get("signal_weights") or {}).get("lightgbm", 0) or 0) > 0:
        raise GenerationError("signal_weights.lightgbm > 0 — LightGBM 점수는 Pine 으로 옮길 수 없다(비목표)")
    e_cond, e_s, e_l = _rule(spec, "entry", "진입")
    x_cond, x_s, x_l = _rule(spec, "exit", "청산")
    if (e_s, e_l) != (x_s, x_l):
        raise GenerationError(f"진입({e_s}/{e_l})과 청산({x_s}/{x_l})의 이동평균 기간이 다르다 — v0.1 은 한 쌍의 이동평균만 만든다")
    pct = (spec.get("position_sizing") or {}).get("max_position_pct")
    if pct is None or not (0 < float(pct) <= 100):
        raise GenerationError("position_sizing.max_position_pct 가 없거나 0 ~ 100 이 아니다 — 수량 상한이 없는 카드는 만들지 않는다")

    universe = [str(u) for u in (spec.get("universe") or [])]
    if not universe:
        raise GenerationError("universe 가 비었다 — 한 종목 이상 필요하다")
    if symbol is None and len(universe) > 1:
        raise GenerationError(f"종목이 {len(universe)}개다 — v0.1 은 한 종목씩 만든다(symbol 로 고른다: {', '.join(universe)})")
    sym = str(symbol) if symbol is not None else universe[0]
    if sym not in universe:
        raise GenerationError(f"{sym} 는 카드 유니버스({', '.join(universe)}) 안에 없다")

    warnings: List[str] = []
    v2 = _v2_params(spec) if "stops" in spec else None
    skipped: List[str] = []
    if v2 is None:                          # 판 1 — 판 2 칸이 따로 있으면 옮기지 않고 경고
        skipped = [k for k in V2_KEYS if k in spec] + [f"{a}.{b}" for a, b in V2_NESTED if b in (spec.get(a) or {})]
        if skipped:
            warnings.append(f"판 2 칸 {', '.join(skipped)} 는 `stops` 가 없는 카드라 코드에 옮기지 않았다 — "
                            f"손절 · 익절 · 위험 % 수량 · 체결 시점이 TradingView 에 반영되지 않는다")
    else:
        warnings.append("price_basis = adj_base — TradingView 차트의 수정주가(Adjust data) 설정을 우리 수집 DB 수정주가와 같은 상태로 두고 대사한다. Pine 코드로는 정할 수 없다")
        if v2["mode"] == "close":
            warnings.append("entry_mode · exit_mode = close — 같은 종가에 체결(process_orders_on_close = true). 현실에서는 불가한 가정이다")
        if v2["judge"] == "intrabar":
            warnings.append("judge = intrabar — 봉 안에서 선에 닿으면 체결(strategy.exit). 우리 일봉 종가 판정과 다르다 — 대사 범위 밖(설계서 3.3 ①)")
    sw = spec.get("signal_weights") or {}
    if "buy_threshold" in sw or "sell_threshold" in sw:
        warnings.append("signal_weights 의 buy/sell_threshold 는 Pine 에 옮기지 않는다 — 진입 · 청산은 entry · exit 규칙의 상태만 본다")

    one_way = Decimal(str(fee_pct)) + Decimal(str(sell_tax_pct)) / 2
    round_trip = Decimal(str(fee_pct)) * 2 + Decimal(str(sell_tax_pct))
    ticks, eff = 0, 0.0
    if ref_price and mintick and float(ref_price) > 0 and float(mintick) > 0:
        raw = float(ref_price) * float(slippage_bp) / 10000 / float(mintick)
        ticks = int(math.floor(raw + 0.5))
        eff = ticks * float(mintick) / float(ref_price) * 10000
        if ticks == 0:
            warnings.append(f"슬리피지 {slippage_bp}bp 가 호가 단위 {_num(mintick)}원 기준 0틱이 되어 슬리피지가 통째로 빠진다 — 더 큰 값이 필요하다")
        elif abs(eff - float(slippage_bp)) > 0.01:
            warnings.append(f"슬리피지 {slippage_bp}bp 를 호가 단위 {_num(mintick)}원으로 환산하면 {ticks}틱(실효 {eff:.1f}bp)으로 반올림된다 — "
                            f"환산 오차는 대사표 cost 원인 코드로 적는다")
    else:
        warnings.append("슬리피지를 틱으로 환산할 기준가나 호가 단위(mintick)가 없어 0틱으로 두었다")

    sha = fingerprint(spec)
    sid, ver = spec.get("strategy_id"), spec.get("version")
    on_close = "true" if v2 and v2["mode"] == "close" else "false"
    head = [
        "//@version=6",
        f"// Qurious card {sid} v{ver} sha256:{sha}",
        f"// universe: {sym} · timeframe: 1d · 생성기 " + ("v0.1 (판 1 — 계약 칸만)" if v2 is None else "v0.2 (판 2 — 손절 · 익절 · 위험 % 수량 · 체결 시점)"),
    ]
    if v2 is not None:
        head.append("// price_basis: adj_base — 차트의 수정주가(Adjust data) 설정을 우리 수집 DB 수정주가와 같게 두고 대사한다")
        head.append("// 손절 · 익절선은 진입 체결가(strategy.position_avg_price — 슬리피지 포함)에서 잰다")
    lines = head + [
        f'strategy("Qurious {sid} v{ver}", overlay = true, initial_capital = {int(initial_capital)}, pyramiding = 0, '
        f"default_qty_type = strategy.fixed, commission_type = strategy.commission.percent, commission_value = {_dec(one_way)}, "
        f"slippage = {ticks}, process_orders_on_close = {on_close}, calc_on_every_tick = false)",
        "",
        "if not timeframe.isdaily",
        '    runtime.error("카드는 일봉용")',
        "",
        f"shortLen = {e_s}",
        f"longLen = {e_l}",
        "fast = ta.sma(close, shortLen)",
        "slow = ta.sma(close, longLen)",
        "",
        f"positionPct = {_num(pct)}",
    ]
    if v2 is None:
        lines += [
            "qty = math.floor(strategy.equity * positionPct / 100 / close)",
            "",
            f"entryCond = {_COND[e_cond]}",
            f"exitCond = {_COND[x_cond]}",
            "",
            "if entryCond and strategy.position_size == 0 and qty > 0",
            '    strategy.entry("L", strategy.long, qty = qty)',
            "if exitCond and strategy.position_size > 0",
            '    strategy.close("L")',
        ]
    else:
        lines += [
            f"riskPct = {_num(v2['risk_pct'])}",
            f"atrPeriod = {v2['atr_period']}",
            f"atrMult = {_num(v2['atr_mult'])}",
            f"takeRr = {_num(v2['take_rr'])}",
            f"warmupBars = {v2['warmup_bars']}",
            "",
            "atrNow = ta.atr(atrPeriod)",
            "ready = bar_index + 1 >= warmupBars",
            "",
            f"entryCond = {_COND[e_cond]}",
            f"exitCond = {_COND[x_cond]}",
            "",
            "riskQty = atrNow > 0 ? math.floor(strategy.equity * riskPct / 100 / (atrMult * atrNow)) : 0",
            "capQty = math.floor(strategy.equity * positionPct / 100 / close)",
            "qty = math.min(riskQty, capQty)",
            "",
            "var float atrEntry = na",
            "var float stopPx = na",
            "var float takePx = na",
            "var bool needFresh = false",
            "",
            "if not entryCond",
            "    needFresh := false",
            "",
            "if strategy.position_size == 0",
            "    stopPx := na",
            "    takePx := na",
            "else if na(stopPx)",
            "    stopPx := strategy.position_avg_price - atrMult * atrEntry",
            "    takePx := strategy.position_avg_price + takeRr * (strategy.position_avg_price - stopPx)",
            "",
        ]
        if v2["judge"] == "close":
            lines += [
                "stopHit = strategy.position_size > 0 and close <= stopPx",
                "takeHit = strategy.position_size > 0 and close >= takePx",
                "if strategy.position_size > 0 and (stopHit or takeHit or exitCond)",
                '    strategy.close("L")',
                "    if stopHit or takeHit",
                "        needFresh := true",
            ]
        else:
            lines += [
                "if strategy.position_size > 0",
                '    strategy.exit("X", "L", stop = stopPx, limit = takePx)',
                "if strategy.position_size > 0 and exitCond",
                '    strategy.close("L")',
                "if strategy.position_size[1] > 0 and strategy.position_size == 0 and entryCond",
                "    needFresh := true",
            ]
        lines += [
            "",
            "if entryCond and strategy.position_size == 0 and ready and not needFresh and qty > 0",
            "    atrEntry := atrNow",
            '    strategy.entry("L", strategy.long, qty = qty)',
        ]
    lines += [
        "",
        'plot(fast, "fast", color = color.orange)',
        'plot(slow, "slow", color = color.blue)',
        "",
    ]
    code = "\n".join(lines)
    return PineResult(code=code, card_id=str(sid), version=int(ver or 0), sha12=sha, symbol=sym, extracted=read_back(code),
                      warnings=warnings, skipped_v2=skipped, slippage_ticks=ticks, slippage_effective_bp=eff,
                      commission_one_way_pct=_dec(one_way), commission_round_trip_pct=_dec(round_trip))


def _as_number(s: str):
    return float(s) if "." in s else int(s)


def read_back(code: str) -> Dict:
    """생성한 코드에서 숫자를 다시 뽑는다 — `TC-PN` 이 카드 · 입력 값과 견주는 쪽(생성 로직과 따로 읽는다)."""
    def grab(pat: str, flags: int = 0) -> Optional[str]:
        m = re.search(pat, code, flags)
        return m.group(1) if m else None

    head = re.search(r"^(strategy|indicator)\(", code, re.M)
    cap, slip, pyr = grab(r"initial_capital = (\d+)"), grab(r"slippage = (\d+)"), grab(r"pyramiding = (\d+)")
    out = {
        "version": int(grab(r"^//@version=(\d+)", re.M) or 0),
        "declaration": head.group(1) if head else None,
        "initial_capital": int(cap) if cap else None,
        "commission_type": grab(r"commission_type = strategy\.commission\.(\w+)"),
        "commission_value": grab(r"commission_value = ([\d.]+)"),
        "slippage_ticks": int(slip) if slip else None,
        "pyramiding": int(pyr) if pyr else None,
        "process_orders_on_close": grab(r"process_orders_on_close = (true|false)") == "true",
        "short_len": int(grab(r"^shortLen = (\d+)", re.M) or 0),
        "long_len": int(grab(r"^longLen = (\d+)", re.M) or 0),
        "position_pct": _as_number(grab(r"^positionPct = ([\d.]+)", re.M) or "0"),
        "entry_cond": grab(r"^entryCond = (.+)$", re.M),
        "exit_cond": grab(r"^exitCond = (.+)$", re.M),
        "daily_only": "if not timeframe.isdaily" in code and "runtime.error(" in code,
    }
    if re.search(r"^atrPeriod = ", code, re.M):                      # 판 2 코드일 때만
        out.update({
            "risk_pct": _as_number(grab(r"^riskPct = ([\d.]+)", re.M) or "0"),
            "atr_period": int(grab(r"^atrPeriod = (\d+)", re.M) or 0),
            "atr_mult": _as_number(grab(r"^atrMult = ([\d.]+)", re.M) or "0"),
            "take_rr": _as_number(grab(r"^takeRr = ([\d.]+)", re.M) or "0"),
            "warmup_bars": int(grab(r"^warmupBars = (\d+)", re.M) or 0),
            "judge": "intrabar" if "strategy.exit(" in code else "close",
            "new_signal_guard": "if not entryCond" in code and "needFresh" in code,
        })
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="전략 카드(JSON) → Pine v6 strategy() 코드")
    ap.add_argument("card", help="전략 카드 JSON 파일")
    ap.add_argument("--symbol", help="유니버스가 둘 이상일 때 만들 한 종목")
    ap.add_argument("--ref-price", type=float, help="슬리피지를 틱으로 바꿀 기준가(원)")
    ap.add_argument("--mintick", type=float, help="그 가격대의 호가 단위(원) — TradingView 심볼의 mintick")
    ap.add_argument("--fee-pct", default="0.015")
    ap.add_argument("--sell-tax-pct", default="0.18")
    ap.add_argument("--capital", type=int, default=10_000_000)
    ap.add_argument("--out", help="쓸 .pine 파일(기본: 카드 옆 <카드이름>.pine)")
    a = ap.parse_args(argv)
    card = Path(a.card)
    try:
        spec = json.loads(card.read_text(encoding="utf-8"))
        r = generate(spec, symbol=a.symbol, ref_price=a.ref_price, mintick=a.mintick, fee_pct=a.fee_pct,
                     sell_tax_pct=a.sell_tax_pct, initial_capital=a.capital)
    except (OSError, ValueError) as e:           # GenerationError 는 ValueError 의 한 갈래(깨진 JSON 도 여기)
        print(f"🔴 만들지 못했다 — {e}", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else card.with_suffix(".pine")
    out.write_text(r.code, encoding="utf-8", newline="\n")
    print(f"✅ {out} · 카드 {r.card_id} v{r.version} sha256:{r.sha12} · 종목 {r.symbol} · 수수료 편도 {r.commission_one_way_pct}% "
          f"(왕복 {r.commission_round_trip_pct}%) · 슬리피지 {r.slippage_ticks}틱")
    for w in r.warnings:
        print(f"🟡 {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
