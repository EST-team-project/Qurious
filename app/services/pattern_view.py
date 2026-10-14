"""패턴 화면(`robo-patterns`) 응답에 더하는 것 — 목표 기능 ② 설계서 <표 13> `API-STK-34` · `API-STK-35` · W4.

- 패턴 통계 묶음: 전 종목 11종(`pattern_stats_summary.json` — `scripts/pattern_stats_scan.py` 결과 그대로)과
  그 종목(수집 DB 일봉을 같은 규칙 `pattern_stats.event_study` 로 · 봉인 구간 전까지). 설계서 3.5 — 화면은 둘을 나란히 보인다.
- 가격 수준: 가장 가까운 지지 · 저항과 ATR(14) — 설명 요약에 붙일 한 줄과 그 값(#161 A5).
- 다중 주기 신호: 매일 기록(T2)이 있으면 그 줄(기록 날짜를 함께), 없으면 그 자리 계산 — 둘 다 같은 설명(`signal_explain`)을 붙인다(#153 B4).

패턴 통계는 가격 움직임의 통계이지 전략 성과가 아니다. 화면은 패턴을 「오를 · 내릴 신호」 로 말하지 않는다(설계서 5.4.1).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.services import collector_db, data_ohlcv
from app.services import mtf_signals as ms
from app.services import pattern_stats as ps
from app.services import signal_explain as se
from app.services import ta_utils as ta
from app.services.quant_pipeline import preprocess

logger = logging.getLogger(__name__)

SUMMARY_PATH = Path(__file__).with_name("pattern_stats_summary.json")
#: 화면 다중 주기(`patterns.TIMEFRAMES`)의 주기 이름 → T2 · 설명이 쓰는 이름
_TF = {"60m": "60m", "1d": "1d", "1wk": "1w"}
LEVEL_NOTE = "지지 · 저항은 과거에 여러 번 멈췄던 가격대이고, ATR 은 최근 하루 움직임의 평균 폭입니다. 다음에도 그 자리에서 멈추거나 그만큼만 움직인다는 뜻은 아닙니다."


# ── 패턴 통계 ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_summary() -> dict:
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


class _NoData(Exception):
    """그 종목 일봉이 없거나 짧다 — 저장하지 않는다(다음 요청이 다시 읽는다)."""


@lru_cache(maxsize=1)
def _benchmark(end: str) -> pd.Series:
    # 읽지 못하면 OhlcvError 가 그대로 나간다 — lru_cache 는 예외를 저장하지 않는다
    rows = data_ohlcv.read_ohlcv(load_summary()["meta"]["benchmark"], "1d", start="2000-01-01", end=end,
                                 limit=data_ohlcv.MAX_LIMIT)["rows"]
    return pd.Series([r["close"] for r in rows], index=pd.to_datetime([r["trade_date"] for r in rows]), dtype=float)


def symbol_stats(symbol: str) -> dict | None:
    """그 종목의 패턴별 5거래일 뒤 결과 — 전 종목 집계와 같은 끝날 · 같은 규칙. 수집 DB 에 없거나 읽지 못하면 None."""
    try:
        return _symbol_stats(symbol.strip().upper())
    except _NoData:
        return None
    except Exception:
        logger.warning("종목 패턴 통계를 내지 못했다 — %s", symbol, exc_info=True)
        return None


@lru_cache(maxsize=512)
def _symbol_stats(symbol: str) -> dict:
    # 끝날이 봉인 구간 전이라 결과는 바뀌지 않는다 — 종목마다 한 번 계산해 둔다(실패는 저장하지 않는다)
    end = load_summary()["meta"]["end"]
    data = collector_db.read_daily_candles(symbol, "max", today=date.fromisoformat(end))
    if not data or len(data["candles"]) < ps.MIN_BARS + ps.HORIZON:
        raise _NoData(symbol)
    ev, base = ps.event_study(preprocess(data["candles"]), _benchmark(end), end=end)
    out = {"baseline_mean_5d": base["baseline"], "baseline_up_ratio": base["baseline_up"],
           "baseline_days": base["baseline_days"], "patterns": {}}
    for key, g in ev.groupby("key"):
        r, x = g["forward_ret_5d"], g["excess_ret_5d"].dropna()
        out["patterns"][key] = {"events": int(len(g)), "mean_ret_5d": float(r.mean()),
                                "up_ratio": float((r > 0).mean()),
                                "mean_excess_5d": float(x.mean()) if len(x) else None}
    return out


def stats_block(symbol: str) -> dict:
    """`API-STK-34` 의 `stats` — 전 종목 11종과 그 종목을 패턴마다 나란히."""
    s = load_summary()
    one = symbol_stats(symbol)
    meta = s["meta"]
    patterns = []
    for p in s["patterns"]:
        mine = None if one is None else one["patterns"].get(p["key"], {"events": 0})
        patterns.append({
            "key": p["key"], "name": p["name"], "direction": p["direction"],
            "all": {k: p.get(k) for k in ("events", "symbols", "mean_ret_5d", "up_ratio", "mean_excess_5d", "mean_vs_baseline")},
            "symbol": mine,
        })
    return {
        "end": meta["end"], "horizon": meta["horizon"], "rules": meta["rules"], "note": meta["note"],
        "all_symbols": meta["symbols"],
        "baseline": {"all": {"mean_ret_5d": meta["baseline_mean_5d"], "up_ratio": meta["baseline_up_ratio"]},
                     "symbol": None if one is None else {"mean_ret_5d": one["baseline_mean_5d"],
                                                         "up_ratio": one["baseline_up_ratio"]}},
        "patterns": patterns,
    }


# ── 가격 수준 ─────────────────────────────────────────────────────────────

def levels_text(support: dict | None, resistance: dict | None, atr: float | None, atr_pct: float | None) -> str:
    """설명 요약에 붙일 가격 수준 한 줄(#161 A5) — 「가장 가까운 지지 · 저항 · ATR 변동 폭」."""
    def won(v: float) -> str:          # 원화(큰 값)는 정수 · 해외 종목(작은 값)은 소수 둘째 자리
        return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"

    parts = []
    if support:
        parts.append(f"가장 가까운 지지 {won(support['price'])}({support['distance_pct']:+.1f}%)")
    if resistance:
        parts.append(f"저항 {won(resistance['price'])}({resistance['distance_pct']:+.1f}%)")
    if atr is not None:
        parts.append(f"하루 평균 변동 폭(ATR 14일) {won(atr)}({atr_pct:.1f}%)")
    return " · ".join(parts)


def price_levels(candles: list[dict], sr: dict) -> dict:
    """가장 가까운 지지 · 저항과 ATR(14 · Wilder) — 설명 요약의 가격 수준 한 줄(#161 A5)."""
    df = preprocess(candles)
    atr = ta.atr(df["high"].astype(float), df["low"].astype(float), df["close"].astype(float), 14).iloc[-1]
    last = float(df["close"].iloc[-1])
    ok = pd.notna(atr) and last > 0
    atr14 = round(float(atr), 2) if ok else None
    atr_pct = round(float(atr) / last * 100, 2) if ok else None
    support, resistance = sr.get("nearest_support"), sr.get("nearest_resistance")
    return {
        "as_of": df.index[-1].strftime("%Y-%m-%d"), "last_price": round(last, 2),
        "support": support, "resistance": resistance, "atr14": atr14, "atr_pct": atr_pct,
        "text": levels_text(support, resistance, atr14, atr_pct), "note": LEVEL_NOTE,
    }


# ── 다중 주기 신호 ────────────────────────────────────────────────────────

def label(signal: str, strength: str | None) -> str:
    """화면에 보이는 신호 낱말 — 「강력 매수」 → 「매수 · 강」 (#161 A7 · #153). 보통 강도는 「매수」 그대로.
    코드의 `action`(「강력 매수」)은 바꾸지 않는다 — 자동매매가 그 글자를 읽는다."""
    return f"{signal} · {strength}" if strength == ms.STRONG else signal


def _action(signal: str, strength: str | None) -> str:
    # 자동매매가 읽는 옛 낱말 — 바꾸지 않는다(#161 A7)
    return f"강력 {signal}" if strength == ms.STRONG else signal


def from_record(snapshot: dict) -> dict:
    """T2 한 줄 → 화면 응답(지금 화면이 읽는 칸 + 신호 · 강도 · 설명)."""
    tfs = []
    for t in snapshot.get("timeframes") or []:
        row = {"label": t["label"], "weight": t["weight"], "as_of": t.get("last_bar")}
        row.update({k: t[k] for k in ("score", "rsi", "ma5", "ma20", "reasons", "error") if k in t})
        tfs.append(row)
    as_of = snapshot["as_of"]
    return {
        "source": "record", "as_of": as_of.isoformat() if isinstance(as_of, date) else str(as_of),
        "definition": snapshot["definition"], "timeframes": tfs, **_signal_fields(snapshot),
        "explanation": se.explain(snapshot),
    }


def from_live(symbol: str, live: dict) -> dict:
    """`patterns.multi_timeframe_signal` 결과(그 자리 계산) → 같은 모양 · 같은 설명."""
    rows = []
    for t in live["timeframes"]:
        rows.append({"timeframe": _TF.get(t.get("interval"), t.get("interval")), "label": t["label"],
                     "weight": t["weight"], **{k: v for k, v in t.items() if k not in ("interval", "range", "label", "weight")}})
    combined = ms.combine(rows)
    pat = live.get("pattern") or {}
    # 기준일 = 마지막 일봉 날(오늘이 아니라) — 기록(T2)의 as_of 와 같은 뜻 · 설명의 「그날 패턴」 이 이 날로 맞춰진다
    daily = next((t for t in live["timeframes"] if t.get("interval") == "1d" and t.get("as_of")), None)
    as_of = pat.get("as_of") or (daily["as_of"][:10] if daily else _today().isoformat())
    patterns = None if "patterns" not in pat else (
        [{"key": p["key"], "name": p["name"], "direction": p["direction"], "date": p["date"]} for p in pat["patterns"]]
        + [{"key": e["key"], "name": e["name"], "direction": e["direction"], "date": as_of} for e in pat.get("breakouts", [])])
    snapshot = {"as_of": date.fromisoformat(as_of), "symbol": se.normalize_symbol(symbol), "definition": ta.DEFINITION,
                **combined, "timeframes": rows, "patterns": patterns}
    fields = _signal_fields(snapshot)
    if live.get("disclaimer"):          # 그 자리 계산이 쓴 시세 범위(분봉 1개월 · 주봉 5년)도 함께
        fields["disclaimer"] = f"{se.DISCLAIMER} {live['disclaimer']}"
    return {
        "source": "live", "as_of": as_of, "definition": ta.DEFINITION,
        "timeframes": live["timeframes"], "pattern": live.get("pattern"), **fields,
        "explanation": se.explain(snapshot),
    }


def _signal_fields(snapshot: dict) -> dict:
    signal, strength = snapshot["signal"], snapshot.get("strength")
    conf = float(snapshot["confidence"])
    return {
        "signal": signal, "strength": strength, "label": label(signal, strength),
        "action": _action(signal, strength),
        # 신뢰도 · 방향 일치도는 T2 와 같은 0 ~ 1(설계서 <표 13>) — 화면이 % 로 바꿔 보인다
        "confidence": round(conf, 4),
        "agreement": round(float(snapshot.get("agreement") or 0), 4),
        "composite": round(float(snapshot["composite"]), 2),
        "disclaimer": se.DISCLAIMER,
    }


def _today() -> date:
    return datetime.now(data_ohlcv.KST).date()
