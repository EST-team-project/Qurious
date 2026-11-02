"""신호 적중 대조 — 다중 주기 신호(T2 와 같은 정의)를 봉인 전 기간에 다시 내고 5거래일 뒤 실제와 맞댄다 (#161 A9).

T2(`signal_snapshots`)에 쌓이는 신호와 같은 함수(`mtf_signals.signal_at` — 그날까지의 봉만 씀)로, 기록이 쌓이기 전의
날들을 다시 계산한다. 대상은 분봉 유니버스(`u2-20260930` · 401종목 · 11-02 까지 T2 가 기록하던 대상)이고, 기간은 60분봉이 30일 쌓인 날부터
봉인 구간 앞날(2026-08-31)까지다 — 60분 · 일 · 주 세 주기가 모두 있는 날만 쓴다.

날은 공통 거래일에서 5거래일마다 하나씩 뽑는다 — 5거래일 뒤 수익끼리 겹치지 않는다(패턴 통계 `thin` 과 같은 까닭).
5거래일 뒤 수익 = 그 종목의 그날 종가 → 5봉 뒤 종가(수정주가 · 비용 없음) · 코스피 대비 = 같은 두 날 코스피 수익을 뺀 값.
적중 = 매수 쪽이면 5일 뒤 수익 > 0 · 매도 쪽이면 < 0 (관망은 적중을 세지 않는다).

    python scripts/signal_hit_scan.py                 # 401종목 · 6프로세스 약 50분(이 노트북) → data/local-run/signal_hits/
    python scripts/signal_hit_scan.py --limit 10      # 앞 10종목만

만드는 파일
  summary.json    신호 · 강도별 횟수 · 평균 · 오른 비율 · 적중률 · 코스피 대비 · 신뢰도 구간별 적중률 + 조건
  rows.csv        (날 · 종목) 한 줄 — 신호 · 신뢰도 · 5일 뒤 수익 · 코스피 대비
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import data_ohlcv, mtf_signals  # noqa: E402
from app.services import pattern_stats as ps  # noqa: E402
from collector import config  # noqa: E402

DB = config.DB_PATH
BENCHMARK = "KOSPI:코스피"
DEFAULT_END = "2026-08-31"   # 봉인 구간 시작 가능일 전날
OUT = ROOT / "data" / "local-run" / "signal_hits"
#: 신뢰도 구간(0 ~ 1 · 확률이 아님 — mtf_signals 머리말) — 구간마다 적중률을 낸다
CONF_BINS = (0.0, 0.25, 0.5, 0.75, 1.0001)


def first_full_day() -> str:
    """60분봉이 처음 쌓인 날 + 60분 주기가 돌아보는 30일 — 이날부터 세 주기가 모두 있다."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        first = con.execute("SELECT MIN(trade_date) FROM price_intraday WHERE timeframe = '60m'").fetchone()[0]
    finally:
        con.close()
    return (date.fromisoformat(first) + mtf_signals.TIMEFRAMES[0][3]).isoformat()


def sample_days(days: list[str], horizon: int = ps.HORIZON) -> list[str]:
    """공통 거래일에서 `horizon` 거래일마다 하나 — 5거래일 뒤가 끝날 안에 있는 날만."""
    return [d for i, d in enumerate(days) if i % horizon == 0 and i + horizon < len(days)]


def benchmark(end: str) -> pd.Series:
    rows = data_ohlcv.read_ohlcv(BENCHMARK, "1d", start="2000-01-01", end=end, path=DB)["rows"]
    return pd.Series([r["close"] for r in rows], index=[r["trade_date"] for r in rows], dtype=float)


def one(args: tuple[str, str, str, list[str], pd.Series]) -> list[dict]:
    code, start, end, picks, bench = args
    bars = mtf_signals.load_bars(code, start, end, path=DB)
    days = [r["trade_date"] for r in bars.daily]
    at = {d: i for i, d in enumerate(days)}
    out = []
    for d in picks:
        i = at.get(d)
        if i is None or i + ps.HORIZON >= len(days):      # 그날 시세가 없거나 5봉 뒤가 끝날 밖
            continue
        s = mtf_signals.signal_at(bars, d)
        if s is None:
            continue
        exit_day = days[i + ps.HORIZON]
        ret = bars.daily[i + ps.HORIZON]["close"] / bars.daily[i]["close"] - 1
        bench_ret = bench[exit_day] / bench[d] - 1 if d in bench.index and exit_day in bench.index else None
        out.append({"as_of": d, "symbol": code, "signal": s["signal"], "strength": s["strength"],
                    "confidence": s["confidence"], "composite": s["composite"], "exit_day": exit_day,
                    "ret_5d": ret, "excess_5d": None if bench_ret is None else ret - bench_ret})
    return out


def hit(signal: str, ret: float) -> bool | None:
    """매수 쪽은 오르면 · 매도 쪽은 내리면 적중 · 관망은 세지 않는다(None)."""
    if signal == mtf_signals.BUY:
        return ret > 0
    if signal == mtf_signals.SELL:
        return ret < 0
    return None


def summarize(rows: pd.DataFrame) -> dict:
    """신호 · 강도별 묶음과 신뢰도 구간별 적중률 — 기준선은 뽑은 날 전체의 5일 뒤 수익."""
    rows = rows.assign(hit=[hit(s, r) for s, r in zip(rows["signal"], rows["ret_5d"])])
    base = {"n": int(len(rows)), "mean_ret_5d": float(rows["ret_5d"].mean()),
            "up_ratio": float((rows["ret_5d"] > 0).mean()), "mean_excess_5d": float(rows["excess_5d"].mean())}
    groups = []
    for (sig, strength), g in rows.groupby(["signal", rows["strength"].fillna("")], sort=False):
        h = g["hit"].dropna()
        groups.append({"signal": sig, "strength": strength or None, "n": int(len(g)),
                       "mean_ret_5d": float(g["ret_5d"].mean()), "median_ret_5d": float(g["ret_5d"].median()),
                       "up_ratio": float((g["ret_5d"] > 0).mean()), "mean_excess_5d": float(g["excess_5d"].mean()),
                       "hit_ratio": float(h.mean()) if len(h) else None})
    order = {(mtf_signals.BUY, mtf_signals.STRONG): 0, (mtf_signals.BUY, mtf_signals.NORMAL): 1,
             (mtf_signals.HOLD, None): 2, (mtf_signals.SELL, mtf_signals.NORMAL): 3, (mtf_signals.SELL, mtf_signals.STRONG): 4}
    groups.sort(key=lambda g: order.get((g["signal"], g["strength"]), 9))
    directed = rows[rows["hit"].notna()]
    bins = []
    for lo, hi in zip(CONF_BINS, CONF_BINS[1:]):
        g = directed[(directed["confidence"] >= lo) & (directed["confidence"] < hi)]
        bins.append({"from": lo, "to": min(hi, 1.0), "n": int(len(g)),
                     "hit_ratio": float(g["hit"].astype(float).mean()) if len(g) else None})
    return {"baseline": base, "groups": groups, "confidence_bins": bins}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):                # Windows 콘솔(cp949)에서도 — 가 찍히게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--end", default=DEFAULT_END, help="결과 기간 끝날(포함 · YYYY-MM-DD) — 5거래일 뒤도 이 안")
    ap.add_argument("--limit", type=int, help="유니버스 앞에서부터 이만큼 종목만")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.end >= ps.SEAL_START:
        print(f"끝날 {a.end} 이 봉인 구간({ps.SEAL_START} ~) 안이다 — 개봉 기록 없이 읽지 않는다(설계서 3.2)")
        return 2

    t0 = time.time()
    start = first_full_day()
    codes = mtf_signals.universe(path=DB)[: a.limit] if a.limit else mtf_signals.universe(path=DB)
    picks = sample_days(mtf_signals.trading_days(start, a.end, path=DB))
    bench = benchmark(a.end)
    print(f"{len(codes)}종목 · {start} ~ {a.end} · 뽑은 날 {len(picks)}개 · 코스피 {len(bench):,}일")

    rows: list[dict] = []
    with ProcessPoolExecutor(a.workers) as ex:
        for part in ex.map(one, ((c, start, a.end, picks, bench) for c in codes), chunksize=4):
            rows.extend(part)
    df = pd.DataFrame(rows)
    print(f"(날 · 종목) {len(df):,}줄 · {time.time() - t0:.0f}초")

    meta = {
        "definition": "tv-2026", "universe": mtf_signals.UNIVERSE, "symbols": int(df["symbol"].nunique()),
        "start": start, "end": a.end, "seal_start": ps.SEAL_START, "horizon": ps.HORIZON, "sampled_days": len(picks),
        "first_day": str(df["as_of"].min()), "last_day": str(df["as_of"].max()), "benchmark": BENCHMARK,
        "rules": "신호 = mtf_signals.signal_at(그날까지의 봉) · 5거래일마다 한 날 · t 종가 → t+5 봉 종가(수정주가 · 비용 없음)"
                 " · 적중 = 매수 쪽 > 0 · 매도 쪽 < 0",
        "note": "가격 움직임의 통계이지 전략 성과가 아니다 — 신뢰도는 확률이 아니다 · 투자 권유가 아니다",
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps({"meta": meta, **summarize(df)}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    df.to_csv(a.out / "rows.csv", index=False, encoding="utf-8")
    print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
