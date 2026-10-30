"""기준 전략 시도 — 조합표(설계서 4.5)의 이동평균 교차 11개를 판 2 카드 값으로 모두 돌리고 합격선으로 가른다(`P02-①-3`).

무엇을 하나
-----------
- 조합: 단기 {5, 10, 20} × 장기 {20, 40, 60, 120} · 단기 < 장기 = 11개(#363 제안 · 반대 없음). 시도는 모두 적는다.
- 카드: 판 2 예시 값 그대로(다음 봉 시가 체결 · ATR 14 × 2 손절 · 손익비 2 익절 · 종가 판정) — 이동평균 기간만 바꾼다.
  엔진은 `quant_pipeline.backtest`(강민석 님 · #381 · #382) 그대로 부른다. 위험 1% 수량은 엔진에 아직 없어 전액 진입이다.
- 비용: 국내 실제 요율(`trading_cost.KrxCostModel` 기본값 · 매도에만 세금). 모든 숫자는 비용을 뗀 뒤.
- 자료: 수집 DB 일봉(수정주가) · 2026-08-31 까지(봉인 구간 D7 — 2026-09-01 뒤 시세는 쓰지 않는다).
- 합격선(D6 ⑦ 확정 · 교안 05.md): PF > 1.5 · MDD > −15% · 샤프 > 1.0 을 동시에 · PF · 승률은 거래 단위.
  엔진은 거래 단위 PF · 승률을 내지 않아, 엔진과 같은 식으로 일별 순수익을 다시 만들어 거래(진입 ~ 청산)마다 묶는다.
  다시 만든 누적 수익이 엔진의 `total_return_pct` 와 같은지 시도마다 맞댄다(다르면 멈춘다).
- DSR(보조 · 강민석 님 `evaluation_risk.calculate_all_metrics` · #399 근사): 시도마다 그 일별 순수익으로 내고,
  `n_trials` 는 조합표 줄 수(`len(GRID)`) — 조합표 밖 시도가 없으니 조합 수가 곧 시도 수다(#363). 합격 판정에는 쓰지 않는다.

쓰는 법:  .venv/bin/python scripts/baseline_trials.py [--symbol 005930.KS] [--end 2026-08-31] [--out <결과 폴더>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import evaluation_risk, quant_pipeline, ta_utils, trading_cost  # noqa: E402
from app.services.collector_db import read_daily_candles  # noqa: E402
from app.services.strategy_card_store import template  # noqa: E402

GRID = [(s, l) for s in (5, 10, 20) for l in (20, 40, 60, 120) if s < l]
PASS = {"profit_factor": 1.5, "mdd_pct": -15.0, "sharpe_ratio": 1.0}


def _frame(symbol: str, end: date) -> pd.DataFrame:
    data = read_daily_candles(symbol, "max", today=end)
    if not data:
        raise SystemExit(f"수집 DB 에서 {symbol} 일봉을 읽지 못했습니다(이 PC 에 수집 DB 가 있어야 합니다).")
    df = pd.DataFrame(data["candles"])
    df.index = pd.to_datetime(df["time"], unit="s")
    return df[df.index.date <= end][["open", "high", "low", "close"]].astype(float)


def _net_daily(df: pd.DataFrame, held: pd.Series, cost) -> pd.Series:
    """엔진(`quant_pipeline.backtest` 의 open 갈래)과 같은 식 — 진입일 시가→종가 · 보유일 종가→종가 · 청산일 전일 종가→시가 − 비용."""
    close, open_ = df["close"], df["open"]
    ret = close.pct_change().fillna(0)
    entry = (held == 1) & (held.shift(1, fill_value=0) == 0)
    exit_ = (held == 0) & (held.shift(1, fill_value=0) == 1)
    g = pd.Series(0.0, index=df.index)
    g[entry] = (close / open_ - 1)[entry]
    g[(held == 1) & ~entry] = ret[(held == 1) & ~entry]
    g[exit_] = (open_ / close.shift(1) - 1)[exit_]
    return g - cost.turnover_cost(held)


def _trades(net: pd.Series, held: pd.Series) -> list[float]:
    """거래마다 복리 수익 — 진입일부터 청산일(보유가 1→0 인 날 · 그날 시가에 판다)까지."""
    out, cur = [], None
    prev = 0.0
    for t, h in held.items():
        if h == 1 and prev == 0:
            cur = 1.0
        if cur is not None:
            cur *= 1 + net[t]
            if h == 0:                                    # 청산일 — 그날 손익(갭 · 매도 비용)까지 넣고 닫는다
                out.append(cur - 1)
                cur = None
        prev = h
    if cur is not None:                                   # 끝날까지 들고 있던 거래 — 마지막 종가로 평가
        out.append(cur - 1)
    return out


def _dsr(net: pd.Series) -> float | None:
    """시도 수 = 조합표 줄 수로 낸 DSR(보조). 값이 안 나오면(표본 부족 등) None."""
    v = evaluation_risk.calculate_all_metrics(net.values, n_trials=len(GRID))["Deflated Sharpe Ratio"]
    return None if v != v else round(float(v), 4)


def run(symbol: str, end: date) -> dict:
    df = _frame(symbol, end)
    card = template()
    st = card["stops"]
    cost = trading_cost.KrxCostModel()
    rows = []
    for n, (short, long) in enumerate(GRID, 1):
        sig = (ta_utils.sma(df["close"], short) > ta_utils.sma(df["close"], long)).astype(int)
        res = quant_pipeline.backtest(df, sig, cost=cost, entry_mode=card["entry_mode"], exit_mode=card["exit_mode"],
                                      atr_period=st["atr_period"], atr_mult=st["atr_mult"], take_rr=st["take_rr"])
        # 엔진과 같은 보유 상태(손절 · 익절 반영)를 다시 만든다
        pos = sig.shift(1).fillna(0)
        held = (pos == 1).astype(float)
        atr = ta_utils.atr(df["high"], df["low"], df["close"], st["atr_period"])
        held, _ = quant_pipeline.apply_stops(df["close"], held, None, None, return_exits=True, atr_values=atr,
                                             atr_mult=st["atr_mult"], take_rr=st["take_rr"], entry_mode=card["entry_mode"],
                                             open_=df["open"])
        net = _net_daily(df, held, cost)
        total = float((1 + net).prod() - 1) * 100
        if abs(total - res["total_return_pct"]) > 0.01:
            raise SystemExit(f"시도 {n}: 다시 만든 누적 수익 {total:.4f}% ≠ 엔진 {res['total_return_pct']}% — 식이 갈렸다")
        tr = _trades(net, held)
        gain, loss = sum(x for x in tr if x > 0), -sum(x for x in tr if x < 0)
        pf = round(gain / loss, 3) if loss > 0 else None
        row = {"trial": n, "short": short, "long": long, "trades": len(tr),
               "win_rate_trade_pct": round(100 * sum(x > 0 for x in tr) / len(tr), 2) if tr else None,
               "profit_factor": pf, "total_return_pct": res["total_return_pct"], "sharpe_ratio": res["sharpe_ratio"],
               "mdd_pct": res["mdd_pct"], "buy_hold_return_pct": res["buy_hold_return_pct"], "cost_drag_pct": res["cost_drag_pct"],
               "stop_exits": res["stop_loss_exits"], "take_exits": res["take_profit_exits"]}
        row["dsr"] = _dsr(net)
        row["pass"] = bool(pf is not None and pf > PASS["profit_factor"] and res["mdd_pct"] > PASS["mdd_pct"]
                           and res["sharpe_ratio"] > PASS["sharpe_ratio"])
        rows.append(row)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"symbol": symbol, "start": df.index[0].date().isoformat(), "end": df.index[-1].date().isoformat(), "bars": len(df),
            "card": {k: card[k] for k in ("strategy_id", "version", "entry_mode", "exit_mode")} | {"stops": st},
            "cost": trading_cost.describe(cost), "definition": ta_utils.DEFINITION, "pass_line": PASS, "commit": commit,
            "n_trials": len(rows), "dsr_n_trials": len(GRID), "trials": rows}


def main() -> None:
    for stream in (sys.stdout, sys.stderr):                # Windows 콘솔(cp949)에서도 ✅ · — 가 찍히게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="005930.KS")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--out", default=None, help="결과 JSON 을 쓸 폴더(없으면 화면에만)")
    a = ap.parse_args()
    out = run(a.symbol, date.fromisoformat(a.end))
    print(f"{out['symbol']} · {out['start']} ~ {out['end']} · {out['bars']}봉 · 시도 {out['n_trials']}개")
    print("| # | 단기 | 장기 | 거래 | 승률(거래) | PF | 수익(비용 뒤) | 샤프 | MDD | DSR(보조) | 합격 |")
    for r in out["trials"]:
        print(f"| {r['trial']} | {r['short']} | {r['long']} | {r['trades']} | {r['win_rate_trade_pct']} | {r['profit_factor']} | "
              f"{r['total_return_pct']} | {r['sharpe_ratio']} | {r['mdd_pct']} | {r['dsr']} | {'✅' if r['pass'] else '—'} |")
    if a.out:
        p = Path(a.out)
        p.mkdir(parents=True, exist_ok=True)
        (p / "trials.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
