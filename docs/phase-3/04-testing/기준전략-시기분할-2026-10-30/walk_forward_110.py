"""SCH-ROB 후속(11번 사전 등록) — 110개 시도의 앞 기간(IS) · 뒤 기간(OOS) 샤프. 저장소 코드는 수정하지 않는다.

기준은 11-2026-10-30-후속댓글초안-이동원.md 3절에 실행 전에 적었다: IS = 2020-01-02 ~ 2023-12-29, OOS = 2024-01-02 ~ 2026-08-31.
전체 기간을 한 번 돌려 얻은 일별 순수익을 날짜로 나눈다(baseline_trials.run 과 같은 식).
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.services import quant_pipeline, ta_utils, trading_cost  # noqa: E402
from app.services.collector_db import read_daily_candles  # noqa: E402
from app.services.strategy_card_store import template  # noqa: E402

GRID = [(s, l) for s in (5, 10, 20) for l in (20, 40, 60, 120) if s < l]
SYMBOLS = ["005930.KS", "000660.KS", "035420.KS", "207940.KS", "005380.KS",
           "012330.KS", "068270.KS", "051910.KS", "005490.KS", "028260.KS"]
END = date(2026, 8, 31)
IS_END = pd.Timestamp("2023-12-29")
OOS_START = pd.Timestamp("2024-01-02")
CAPITAL = 10_000_000.0


def sharpe(x: pd.Series) -> float:
    x = x.dropna()
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(252)) if len(x) > 2 and sd > 0 else float("nan")


def frame(symbol: str) -> pd.DataFrame:
    data = read_daily_candles(symbol, "max", today=END)
    df = pd.DataFrame(data["candles"])
    df.index = pd.to_datetime(df["time"], unit="s")
    return df[df.index.date <= END][["open", "high", "low", "close"]].astype(float)


card = template()
st, ps = card["stops"], card["position_sizing"]
cost = trading_cost.KrxCostModel()
size = {"risk_pct": ps["risk_pct"], "max_position_pct": ps["max_position_pct"], "initial_capital": CAPITAL}
rows = []
for sym in SYMBOLS:
    df = frame(sym)
    for short, long in GRID:
        sig = (ta_utils.sma(df["close"], short) > ta_utils.sma(df["close"], long)).astype(int)
        res = quant_pipeline.backtest(df, sig, cost=cost, entry_mode=card["entry_mode"], exit_mode=card["exit_mode"],
                                      atr_period=st["atr_period"], atr_mult=st["atr_mult"], take_rr=st["take_rr"], **size)
        held = (sig.shift(1).fillna(0) == 1).astype(float)
        atr = ta_utils.atr(df["high"], df["low"], df["close"], st["atr_period"])
        held, _ = quant_pipeline.apply_stops(df["close"], held, None, None, return_exits=True, atr_values=atr,
                                             atr_mult=st["atr_mult"], take_rr=st["take_rr"], entry_mode=card["entry_mode"],
                                             open_=df["open"])
        sized = quant_pipeline.size_positions(df, held, cost=cost, entry_mode=card["entry_mode"], exit_mode=card["exit_mode"],
                                              atr_values=atr, atr_mult=st["atr_mult"], **size)
        net = sized["net_ret"]
        total = float((1 + net).prod() - 1) * 100
        if abs(total - res["total_return_pct"]) > 0.01:
            raise SystemExit(f"{sym} {short}·{long}: 누적 수익이 엔진과 다르다 {total:.4f} vs {res['total_return_pct']}")
        rows.append({"symbol": sym, "short": short, "long": long,
                     "sh_full": sharpe(net), "sh_engine": res["sharpe_ratio"],
                     "sh_is": sharpe(net[net.index <= IS_END]), "sh_oos": sharpe(net[net.index >= OOS_START]),
                     "n_is": int((net.index <= IS_END).sum()), "n_oos": int((net.index >= OOS_START).sum())})

df = pd.DataFrame(rows)
out = Path(sys.argv[2])
df.to_csv(out, index=False, encoding="utf-8")
print("행", len(df), "· IS 일수", df["n_is"].iloc[0], "· OOS 일수", df["n_oos"].iloc[0])

# 먼저 맞대기: 내 전체 기간 샤프가 엔진 샤프와 가까운가(어긋나면 이 샤프를 쓰지 않는다는 사전 조건)
d = (df["sh_full"] - df["sh_engine"]).abs()
print(f"[맞대기] 전체 기간 샤프 − 엔진 샤프: 최대 차이 {d.max():.3f} · 중앙값 {d.median():.3f} · 0.05 초과 {int((d > 0.05).sum())}/110")

ok = df.dropna(subset=["sh_is", "sh_oos"])
rho = ok["sh_is"].rank().corr(ok["sh_oos"].rank())
print(f"[1] IS↔OOS 샤프 스피어만 ρ = {rho:.3f}  (n={len(ok)})")

hit, tot = 0, 0
for sym, g in df.groupby("symbol"):
    g = g.dropna(subset=["sh_is", "sh_oos"]).copy()
    best = g.loc[g["sh_is"].idxmax()]
    g["rk"] = g["sh_oos"].rank(ascending=False)
    r = float(g.loc[best.name, "rk"])
    tot += 1
    hit += r < 6
    print(f"   {sym}  IS 최고 {int(best.short)}·{int(best.long)} (IS {best.sh_is:.3f}) → OOS 샤프 {best.sh_oos:.3f} · OOS 순위 {r:.0f}/{len(g)}")
print(f"[2] IS 최고 조합이 OOS 에서 6위보다 위인 종목: {hit}/{tot} (무작위 기대 5)")

x = df[(df.symbol == "000660.KS") & (df.short == 20) & (df.long == 60)].iloc[0]
cond = (x.sh_oos > 0) and (x.sh_oos >= 0.5 * x.sh_is) if x.sh_is > 0 else False
print(f"[3] 000660 20·60: IS {x.sh_is:.3f} · OOS {x.sh_oos:.3f} · 전체 {x.sh_full:.3f} → 기준 충족 {cond}")
print("   참고) OOS 샤프 중앙값(110) %.3f · IS 샤프 중앙값 %.3f · OOS 샤프>=1.0 시도 %d개" % (ok.sh_oos.median(), ok.sh_is.median(), int((ok.sh_oos >= 1.0).sum())))
