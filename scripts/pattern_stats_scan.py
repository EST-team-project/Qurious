"""패턴 통계 — 전 종목 · 과거 모든 날의 패턴 뒤 5거래일 수익률 (목표 기능 ② 설계서 5.2 · `P01-②-2`).

설계서 <표 9> 의 사건 연구를 수집 DB 전 종목에 돌려 집계 파일을 만든다(설계서 6절 — 표로 두지 않고 다시 만들 수
있는 파일). 규칙 · 정의는 [`app/services/pattern_stats.py`](../app/services/pattern_stats.py) 에 있다.

데이터 — 수집 DB 의 수정주가를 앱 일봉 다리(`collector_db._candle`)와 같은 규칙으로 봉으로 만든 뒤 화면 탐지기와
같은 `preprocess` 를 거친다. 대상은 끝날까지 한 번이라도 코스피 · 코스닥에 있던 종목 전부 — 상장폐지 종목도
넣는다(그날 살아 있던 종목만 보면 망한 종목의 패턴이 빠진다). 다만 t+5 봉이 없는 사건(그 안에 상장폐지)은 빠진다.
코스피 = 지수 `KOSPI:코스피`(`ohlcv-v1` 읽기).

봉인 구간(2026-09-01 ~ · 설계서 3.2)은 읽지 않는다 — DB 에서 끝날까지만 꺼내고, 끝날을 봉인 구간 안으로 주면 멈춘다.

    python scripts/pattern_stats_scan.py                       # 전 종목 · 약 몇 분 → data/local-run/pattern_stats/
    python scripts/pattern_stats_scan.py --limit 100 --events  # 일부 종목 · 사건 표도 쓴다

만드는 파일
  summary.json    패턴별 횟수 · 평균 · 중앙값 · 오른 비율 · 코스피 대비 · 기준선과의 차 + 조건
  by_symbol.csv   패턴 × 종목 한 줄
  events.csv      사건 한 줄(--events)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import collector_db, data_ohlcv  # noqa: E402
from app.services import pattern_stats as ps  # noqa: E402
from app.services.quant_pipeline import preprocess  # noqa: E402
from collector import config  # noqa: E402

DB = config.DB_PATH
BENCHMARK = "KOSPI:코스피"
DEFAULT_END = "2026-08-31"   # 봉인 구간 시작 가능일 전날
OUT = ROOT / "data" / "local-run" / "pattern_stats"

_QUERY = """
SELECT a.srtn_cd, a.bas_dt, a.adj_clpr, a.adj_mkp, a.adj_hipr, a.adj_lopr, a.cum_factor, d.mkp, d.trqu
  FROM price_adjusted AS a
  JOIN price_daily    AS d ON d.bas_dt = a.bas_dt AND d.srtn_cd = a.srtn_cd
 WHERE a.srtn_cd IN ({codes}) AND a.bas_dt <= ?
 ORDER BY a.srtn_cd, a.bas_dt
"""


def load(end: str, limit: int | None) -> dict[str, list[tuple]]:
    end_ymd = end.replace("-", "")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    codes = [r[0] for r in con.execute(
        "SELECT DISTINCT srtn_cd FROM price_daily WHERE mrkt_ctg IN ('KOSPI','KOSDAQ') AND bas_dt <= ? ORDER BY srtn_cd",
        (end_ymd,))]
    if limit:
        codes = codes[:limit]
    rows = con.execute(_QUERY.format(codes=",".join("?" * len(codes))), (*codes, end_ymd)).fetchall()
    con.close()
    out: dict[str, list[tuple]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(r[1:])
    return out


def benchmark(end: str) -> pd.Series:
    rows = data_ohlcv.read_ohlcv(BENCHMARK, "1d", start="2000-01-01", end=end, path=DB)["rows"]
    return pd.Series([r["close"] for r in rows], index=pd.to_datetime([r["trade_date"] for r in rows]), dtype=float)


def one(args: tuple[str, list[tuple], pd.Series, str]) -> tuple[str, pd.DataFrame, dict] | None:
    code, rows, bench, end = args
    candles = [c for c in map(collector_db._candle, rows) if c is not None]
    if len(candles) < ps.MIN_BARS + ps.HORIZON:
        return None
    df = preprocess(candles)
    ev, base = ps.event_study(df, bench, end=end)
    return code, ev, base


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap =argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--end", default=DEFAULT_END, help="결과 기간 끝날(포함 · YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, help="앞에서부터 이만큼 종목만")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--events", action="store_true", help="사건 표(events.csv)도 쓴다")
    a = ap.parse_args()
    if a.end >= ps.SEAL_START:
        print(f"끝날 {a.end} 이 봉인 구간({ps.SEAL_START} ~) 안이다 — 개봉 기록 없이 읽지 않는다(설계서 3.2)")
        return 2

    t0 = time.time()
    data = load(a.end, a.limit)
    bench = benchmark(a.end)
    print(f"읽음 {len(data):,}종목 · 코스피 {len(bench):,}일 · {time.time() - t0:.0f}초")

    events, bases = [], {}
    with ProcessPoolExecutor(a.workers) as ex:
        jobs = ((code, rows, bench, a.end) for code, rows in data.items())
        for res in ex.map(one, jobs, chunksize=16):
            if res is None:
                continue
            code, ev, base = res
            bases[code] = base
            if len(ev):
                events.append(ev.assign(symbol=code, baseline=base["baseline"]))
    ev = pd.concat(events, ignore_index=True)
    print(f"사건 {len(ev):,}개 · {len(bases):,}종목 · {time.time() - t0:.0f}초")

    summary = ps.summarize(ev)
    by_sym = (ev.groupby(["key", "symbol"])
                .agg(events=("forward_ret_5d", "size"), mean_ret_5d=("forward_ret_5d", "mean"),
                     median_ret_5d=("forward_ret_5d", "median"),
                     up_ratio=("forward_ret_5d", lambda r: float((r > 0).mean())),
                     mean_excess_5d=("excess_ret_5d", "mean"), baseline=("baseline", "first"))
                .reset_index())
    base_days = sum(b["baseline_days"] for b in bases.values())
    base_mean = sum(b["baseline"] * b["baseline_days"] for b in bases.values() if b["baseline_days"]) / base_days
    base_up = sum(b["baseline_up"] * b["baseline_days"] for b in bases.values() if b["baseline_days"]) / base_days
    meta = {
        "definition": "tv-2026", "horizon": ps.HORIZON, "end": a.end, "seal_start": ps.SEAL_START,
        "benchmark": BENCHMARK, "symbols": len(bases), "events": int(len(ev)), "baseline_days": base_days,
        "baseline_mean_5d": base_mean, "baseline_up_ratio": base_up,
        "first_event": str(ev["date"].min()), "last_event": str(ev["date"].max()),
        "rules": "t 종가 → t+5 종가 · 같은 종목 · 패턴 5거래일 안 재발 제외 · 거래량 0 인 날 제외 · 비용 없음",
        "note": "가격 움직임의 통계이지 전략 성과가 아니다 — 투자 권유가 아니다",
    }
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps({"meta": meta, "patterns": summary}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    by_sym.to_csv(a.out / "by_symbol.csv", index=False, encoding="utf-8")
    if a.events:
        ev.to_csv(a.out / "events.csv", index=False, encoding="utf-8")

    print(f"\n{'패턴':<22}{'횟수':>9}{'평균':>9}{'중앙값':>9}{'오른 비율':>9}{'코스피 대비':>11}{'기준선 대비':>11}")
    for r in summary:
        if not r["events"]:
            print(f"{r['name']:<22}{0:>9}")
            continue
        print(f"{r['name']:<22}{r['events']:>9,}{r['mean_ret_5d']:>9.2%}{r['median_ret_5d']:>9.2%}"
              f"{r['up_ratio']:>9.1%}{r['mean_excess_5d']:>11.2%}{r['mean_vs_baseline']:>11.2%}")
    print(f"\n기준선 — 후보 날 {base_days:,} 의 5일 수익률 평균 {base_mean:.2%} · 오른 비율 {base_up:.1%} · 쓴 파일 {a.out} · {time.time() - t0:.0f}초")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
