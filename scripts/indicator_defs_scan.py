"""지표 정의 대조 — 앱 안의 RSI · 볼린저 · ATR 구현이 실제 종목에서 얼마나 갈리나.

목표 기능 ② 설계서 v0.1 의 3절(지금 상태) 근거를 만든다. 기준은 RTM `P01-②-1` 의 인수 기준
「TradingView 정의(RSI = Wilder 평활 · 표준편차 = 모집단)」다.

무엇을 재나
-----------
1. RSI 14 — 기준(TradingView `ta.rsi`: 첫 14개 단순평균으로 시작하는 Wilder 평활)과 앱 안의 RSI 가 나오는 길 셋
     · `ta_utils.rsi`        — quant_pipeline(피처 · XAI · 커스텀 백테스트) · patterns · formula · investment_research
     · `stock._calc_rsi`     — `API-STK-04`(기본 인디케이터 전략 · 전략 분석 · 퀀트 대시보드 화면)
     · `ml_symbol_score`     — 자동매매 종목 점수(공통 RSI를 사용하는 피처 표의 정규화된 RSI 칸)
   값 차이(평균 · 95% · 최대)와 「RSI < 30 · > 70」 판정이 기준과 다른 날의 비율
2. 볼린저 20 · 2σ — (가) 정의 차이: 표준편차 n − 1 과 n(TradingView)을 반올림 없이 견준다
                    (나) 앱 갈래: `ta_utils.bollinger` 와 `stock._calc_bollinger`(화면용 · 소수 둘째 자리)
   밴드 밖 판정은 반올림 단위의 절반(EPS)보다 더 벗어날 때만 센다 — 거래정지로 가격이 평평한 구간은
   밴드 폭이 0 이라 종가 = 밴드인데, 반올림한 밴드와 견주면 「밖」 으로 잘못 세기 때문이다.
3. ATR 14 — `ta_utils.atr` 와 TradingView `ta.atr`(Wilder 평활)
4. 화면 B1 규칙 — 「전일 등락률 ±2%」 판정(public/js/indicator.js)이 실제 밴드 이탈과 얼마나 겹치나
5. 결론이 뒤집히나 — 같은 RSI 역추세 규칙(30 아래 매수 · 70 위 매도 · 다음 날부터 보유 · 비용 없음)을
   구현만 바꿔 돌렸을 때 종목별 누적 수익의 부호가 기준과 달라지는 비율

2026-10-06 판(지표 한 벌로 바꾸기 전)의 결과는 설계서 3.3 표, PR #122 뒤는 3.4 다.
자동매매 종목 점수도 공통 RSI를 사용한다. 이 스크립트로 반올림 차이를 포함한 실제 데이터의 일치 여부를 확인한다.

데이터 — 수집 DB(`collector.config.DB_PATH`)의 수정주가(`price_adjusted`), 앱의 일봉 다리
(`collector_db`)와 같은 값. 코스피 · 코스닥, 기준일에 상장돼 있고 봉이 300개 이상인 종목.
처음 100봉은 평활 시작값의 영향이 남으므로 비교에서 뺀다(--warmup).
봉인 구간(모의투자 검증용 · 시작일 미정 · 가장 이른 시작 가능일 2026-09-01)은 개봉 기록 없이 읽지 않으므로
기본 끝날은 2026-08-31 이다(--end · 설계서 3.2).

    python scripts/indicator_defs_scan.py
    python scripts/indicator_defs_scan.py --limit 200 --json data/local-run/indicator_defs_scan.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import ta_utils as ta  # noqa: E402
from app.services.ml_symbol_score import _features as ml_features  # noqa: E402
from app.services.stock import _calc_bollinger, _calc_rsi  # noqa: E402
from collector import config  # noqa: E402

DB = config.DB_PATH
RSI_N, BB_N, BB_K, ATR_N = 14, 20, 2.0, 14
LO, HI = 30.0, 70.0
EPS = 0.005   # 화면용 값의 반올림 단위(0.01)의 절반


# ── 기준 정의 (TradingView Pine v5 · ta.rma / ta.rsi / ta.stdev / ta.atr 문서의 식) ──────────
def rma(x: pd.Series, n: int) -> pd.Series:
    """Wilder 평활 — 첫 값은 처음 n개의 단순평균, 그 뒤 alpha = 1/n."""
    v = x.to_numpy(dtype=float)
    out = np.full_like(v, np.nan)
    start = np.flatnonzero(~np.isnan(v))
    if len(start) < n:
        return pd.Series(out, index=x.index)
    i0 = start[0] + n - 1
    out[i0] = np.nanmean(v[start[0]:i0 + 1])
    for i in range(i0 + 1, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / n
    return pd.Series(out, index=x.index)


def rsi_tv(close: pd.Series, n: int = RSI_N) -> pd.Series:
    d = close.diff()
    up, dn = rma(d.clip(lower=0), n), rma(-d.clip(upper=0), n)
    r = 100 - 100 / (1 + up / dn)
    # Pine: down == 0 ? 100 : up == 0 ? 0 : … — 둘 다 0 이면 100 이 먼저다
    r = r.where(up != 0, 0.0).where(dn != 0, 100.0)
    return r.where(up.notna())


def atr_tv(h: pd.Series, l: pd.Series, c: pd.Series, n: int = ATR_N) -> pd.Series:
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def load(limit: int | None, min_bars: int, end: str) -> tuple[dict[str, pd.DataFrame], str]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    as_of = con.execute("SELECT max(bas_dt) FROM price_adjusted WHERE bas_dt <= ?", (end,)).fetchone()[0]
    codes = [r[0] for r in con.execute(
        "SELECT srtn_cd FROM price_daily WHERE bas_dt = ? AND mrkt_ctg IN ('KOSPI','KOSDAQ') ORDER BY srtn_cd",
        (as_of,))]
    if limit:
        codes = codes[:limit]
    q = ("SELECT a.srtn_cd, a.bas_dt, a.adj_clpr, a.adj_hipr, a.adj_lopr, d.mkp "
         "FROM price_adjusted a JOIN price_daily d ON d.bas_dt = a.bas_dt AND d.srtn_cd = a.srtn_cd "
         f"WHERE a.srtn_cd IN ({','.join('?' * len(codes))}) AND a.bas_dt <= ? ORDER BY a.srtn_cd, a.bas_dt")
    df = pd.read_sql_query(q, con, params=[*codes, as_of])
    con.close()
    out = {}
    for code, g in df.groupby("srtn_cd", sort=False):
        g = g.set_index("bas_dt")
        # 거래 없는 날(시가 0)은 앱 다리처럼 고가 · 저가를 종가로 둔다
        flat = g["mkp"].fillna(0) <= 0
        g = g.copy()
        for col in ("adj_hipr", "adj_lopr"):
            g[col] = g[col].where(~flat, g["adj_clpr"])
        if len(g) >= min_bars:
            out[code] = g.rename(columns={"adj_clpr": "close", "adj_hipr": "high", "adj_lopr": "low"})
    return out, as_of


def bucket(v: float) -> int:
    """RSI 구간 — 과매도 −1 · 중립 0 · 과매수 1 · 값 없음 0."""
    return 0 if pd.isna(v) else (-1 if v < LO else 1 if v > HI else 0)


def strat_return(close: pd.Series, rsi: pd.Series) -> float:
    """RSI < 30 매수 · > 70 매도 · 신호 다음 날부터 보유 · 비용 없음 — 누적 수익률."""
    reg = pd.Series(np.nan, index=close.index)
    reg[rsi < LO] = 1.0
    reg[rsi > HI] = 0.0
    pos = reg.ffill().fillna(0.0).shift(1).fillna(0.0)
    return float((1 + close.pct_change().fillna(0) * pos).prod() - 1)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, help="앞에서부터 이만큼 종목만 (빠른 확인용)")
    p.add_argument("--min-bars", type=int, default=300)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--end", default="20260831", help="끝날 YYYYMMDD (기본: 봉인 구간의 가장 이른 시작 가능일 전날)")
    p.add_argument("--json", help="결과를 JSON 으로도 쓴다")
    a = p.parse_args(argv)
    if not DB.exists():
        print(f"수집 DB 가 없다: {DB} — scripts/hf_dataset.py restore 로 되살린 뒤 돌린다")
        return 1

    t0 = time.time()
    data, as_of = load(a.limit, a.min_bars, a.end)
    if not data:
        print(f"비교할 종목이 없다 — 끝날 {a.end} · 봉 {a.min_bars}개 이상 조건을 확인한다")
        return 1
    names = ["ta_utils.rsi", "stock._calc_rsi", "ml_symbol_score"]
    diffs = {k: [] for k in names}
    flip_lo = {k: [0, 0] for k in names}   # [판정이 다른 날, 비교한 날]
    flip_hi = {k: [0, 0] for k in names}
    cnt_lo = {k: 0 for k in ["기준"] + names}
    last_bucket_diff = {k: 0 for k in names}
    sign_flip = {k: 0 for k in names}
    ret_gap = {k: [] for k in names}
    bb = {"bars": 0, "touch_s": 0, "touch_p": 0, "differ": 0, "app_differ": 0, "width_ratio": []}
    b1 = {"chg_flag": 0, "chg_and_band": 0, "band": 0, "band_and_chg": 0}
    atr_rel = []
    n_bars = 0

    for code, g in data.items():
        c, h, l = g["close"].astype(float), g["high"].astype(float), g["low"].astype(float)
        ref = rsi_tv(c)
        cand = {
            "ta_utils.rsi": ta.rsi(c, RSI_N),
            "stock._calc_rsi": pd.Series(_calc_rsi(c.tolist(), RSI_N), index=c.index, dtype=float),
            # 피처 표의 7번째 칸이 RSI/100 이다 — 거래량은 RSI 와 무관해 1 로 채운다
            "ml_symbol_score": pd.Series(ml_features(c.to_numpy(), np.ones(len(c)))[:, 6] * 100, index=c.index),
        }
        w = slice(a.warmup, None)
        r0 = ref.iloc[w]
        ok0 = r0.notna()
        n_bars += int(ok0.sum())
        cnt_lo["기준"] += int((r0[ok0] < LO).sum())
        ret_ref = strat_return(c, ref)
        for k, s in cand.items():
            s1 = s.iloc[w]
            m = ok0 & s1.notna()
            diffs[k].append((s1[m] - r0[m]).abs().to_numpy())
            flip_lo[k][0] += int(((s1[m] < LO) != (r0[m] < LO)).sum()); flip_lo[k][1] += int(m.sum())
            flip_hi[k][0] += int(((s1[m] > HI) != (r0[m] > HI)).sum()); flip_hi[k][1] += int(m.sum())
            cnt_lo[k] += int((s1[m] < LO).sum())
            last_bucket_diff[k] += int(bucket(s.iloc[-1]) != bucket(ref.iloc[-1]))
            rk = strat_return(c, s)
            sign_flip[k] += int(np.sign(rk) != np.sign(ret_ref))
            ret_gap[k].append(abs(rk - ret_ref))

        # (가) 정의 차이 — n − 1 과 n, 반올림 없이
        mid = c.rolling(BB_N).mean()
        sd1, sd0 = c.rolling(BB_N).std(ddof=1), c.rolling(BB_N).std(ddof=0)
        m = sd0.notna()
        out = lambda sd: ((c < mid - BB_K * sd - EPS) | (c > mid + BB_K * sd + EPS))[m]
        ts, tp = out(sd1), out(sd0)
        bb["bars"] += int(m.sum()); bb["touch_s"] += int(ts.sum()); bb["touch_p"] += int(tp.sum())
        bb["differ"] += int((ts != tp).sum())
        wr = (sd1 / sd0)[m & (sd0 > 0)]
        bb["width_ratio"].append(wr.to_numpy())
        # (나) 앱 갈래 — ta_utils 와 화면용(API-STK-04)
        up_t, _, lo_t = ta.bollinger(c, BB_N, BB_K)
        up_a, _, lo_a = (pd.Series(x, index=c.index, dtype=float) for x in _calc_bollinger(c.tolist(), BB_N, BB_K))
        ma = up_t.notna() & up_a.notna()
        ta_out = ((c < lo_t - EPS) | (c > up_t + EPS))[ma]
        app_out = ((c < lo_a - EPS) | (c > up_a + EPS))[ma]
        bb["app_differ"] += int((ta_out != app_out).sum())
        # 화면 B1 — 「전일 등락률 < −2%」 와 실제 하단 이탈(모집단 · 반올림 없음)
        chg = c.pct_change() * 100
        flag = (chg[m] < -2)                      # 화면 B1: 「하단 이탈 · 매수」
        band = (c < mid - BB_K * sd0 - EPS)[m]    # 실제: 종가 < 하단밴드
        b1["chg_flag"] += int(flag.sum()); b1["chg_and_band"] += int((flag & band).sum())
        b1["band"] += int(band.sum()); b1["band_and_chg"] += int((band & flag).sum())

        a_s, a_t = ta.atr(h, l, c, ATR_N), atr_tv(h, l, c, ATR_N)
        mm = a_t.notna() & a_s.notna() & (a_t > 0)
        atr_rel.append(((a_s - a_t).abs() / a_t)[mm].iloc[a.warmup:].to_numpy())

    n = len(data)
    pct = lambda x, y: round(100 * x / y, 2) if y else None
    res = {"as_of": as_of, "stocks": n, "bars_compared": n_bars, "warmup": a.warmup, "rsi": {}, "seconds": None}
    for k in names:
        d = np.concatenate(diffs[k]) if diffs[k] else np.array([])
        res["rsi"][k] = {
            "mean_abs": round(float(d.mean()), 3), "p95_abs": round(float(np.percentile(d, 95)), 3),
            "max_abs": round(float(d.max()), 3),
            "lt30_differs_pct": pct(*flip_lo[k]), "gt70_differs_pct": pct(*flip_hi[k]),
            "lt30_days_vs_ref": round(cnt_lo[k] / cnt_lo["기준"], 3) if cnt_lo["기준"] else None,
            "last_day_bucket_differs": last_bucket_diff[k], "last_day_bucket_differs_pct": pct(last_bucket_diff[k], n),
            "strategy_sign_flip": sign_flip[k], "strategy_sign_flip_pct": pct(sign_flip[k], n),
            "strategy_ret_gap_median_pp": round(float(np.median(ret_gap[k])) * 100, 2),
        }
    wr = np.concatenate(bb["width_ratio"])
    res["bollinger"] = {"bars": bb["bars"], "touch_sample_pct": pct(bb["touch_s"], bb["bars"]),
                        "touch_population_pct": pct(bb["touch_p"], bb["bars"]),
                        "touch_differs_pct": pct(bb["differ"], bb["bars"]),
                        "app_ta_vs_screen_differs_pct": pct(bb["app_differ"], bb["bars"]),
                        "touch_count_ratio_sample_over_pop": round(bb["touch_s"] / bb["touch_p"], 3),
                        "width_ratio_median": round(float(np.median(wr)), 4)}
    res["b1_rule"] = {"chg_lt_-2_days": b1["chg_flag"],
                      "of_which_below_band_pct": pct(b1["chg_and_band"], b1["chg_flag"]),
                      "below_band_days": b1["band"],
                      "of_which_chg_lt_-2_pct": pct(b1["band_and_chg"], b1["band"])}
    ar = np.concatenate(atr_rel)
    res["atr"] = {"rel_diff_median_pct": round(float(np.median(ar)) * 100, 2),
                  "rel_diff_p95_pct": round(float(np.percentile(ar, 95)) * 100, 2)}
    res["seconds"] = round(time.time() - t0, 1)

    print(f"기준일 {as_of} · 종목 {n:,} · 비교한 봉 {n_bars:,} (종목마다 처음 {a.warmup}봉 제외) · {res['seconds']}초\n")
    print("| RSI 14 구현 | 평균 차 | 95% 차 | 최대 차 | <30 판정 다름 | >70 판정 다름 | <30 날 수(기준=1) | 마지막 날 구간 다름 | 전략 수익 부호 뒤집힘 | 수익 차 중앙값 |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for k, v in res["rsi"].items():
        print(f"| {k} | {v['mean_abs']} | {v['p95_abs']} | {v['max_abs']} | {v['lt30_differs_pct']}% | {v['gt70_differs_pct']}% "
              f"| {v['lt30_days_vs_ref']} | {v['last_day_bucket_differs']} ({v['last_day_bucket_differs_pct']}%) "
              f"| {v['strategy_sign_flip']} ({v['strategy_sign_flip_pct']}%) | {v['strategy_ret_gap_median_pp']}%p |")
    print("\n볼린저 20 · 2σ:", json.dumps(res["bollinger"], ensure_ascii=False))
    print("화면 B1 규칙  :", json.dumps(res["b1_rule"], ensure_ascii=False))
    print("ATR 14       :", json.dumps(res["atr"], ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
