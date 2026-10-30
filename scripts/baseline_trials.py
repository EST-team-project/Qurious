"""기준 전략 시도 — 조합표(설계서 4.5)의 이동평균 교차 11개를 종목 10개에서 판 2 카드 값으로 모두 돌리고 합격선으로 가른다(`P02-①-3`).

무엇을 하나
-----------
- 조합: 단기 {5, 10, 20} × 장기 {20, 40, 60, 120} · 단기 < 장기 = 11개(#363 제안 · 반대 없음). 시도는 모두 적는다.
- 종목: 2020-01-02(자료 첫날) 코스피 시가총액 상위 10(`SYMBOLS` · 수집 DB `price_daily.mrkt_tot_amt` · 우선주 005935 뺌) —
  시도 수 = 11 × 10 = 110(#363 2026-10-30 · 이동원 님 · 오준영 님 의견대로). 10-29 의 005930 전액 진입 11개는 넣지 않는다.
- 카드: 판 2 예시 값 그대로(다음 봉 시가 체결 · ATR 14 × 2 손절 · 손익비 2 익절 · 종가 판정 · 위험 1% 수량 · 종목 비중 30%) —
  이동평균 기간만 바꾼다. 엔진은 `quant_pipeline.backtest`(강민석 님 · #381 · #382) 에 `risk_pct` 를 넘겨 부른다(#435).
- 비용: 국내 실제 요율(`trading_cost.KrxCostModel` 기본값 · 매도에만 세금). 모든 숫자는 비용을 뗀 뒤.
- 자료: 수집 DB 일봉(수정주가) · 2026-08-31 까지(봉인 구간 D7 — 2026-09-01 뒤 시세는 쓰지 않는다).
- 합격선(D6 ⑦ 확정 · 교안 05.md): PF > 1.5 · MDD > −15% · 샤프 > 1.0 을 동시에 · PF · 승률은 거래 단위.
  거래 단위 PF · 승률은 엔진 응답 `sizing.trades` 의 거래마다 손익(원 · 비용 뒤)으로 센다. DSR 에 쓸 일별 순수익은 엔진과 같은
  보유 상태 · 같은 수량 함수(`size_positions`)로 다시 만들고, 그 누적 수익이 엔진의 `total_return_pct` 와 같은지 시도마다 맞댄다.
- DSR(보조 · 강민석 님 `evaluation_risk.calculate_all_metrics` · #399 근사): `n_trials` = 110. 합격 판정에는 쓰지 않는다.
- 합격이 0 이면 「기준 전략 없음」 — 가장 가까운 조합(`nearest` · 실행 전에 정한 규칙)은 참고로만 적는다.

쓰는 법:  .venv/bin/python scripts/baseline_trials.py [--symbol 005930.KS ...] [--end 2026-08-31] [--out <결과 폴더>]
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
#: 2020-01-02(자료 첫날) 코스피 시가총액 상위 10 — 수집 DB `price_daily.mrkt_tot_amt` · 같은 회사 우선주 005935 뺌(#363)
SYMBOLS = ["005930.KS", "000660.KS", "035420.KS", "207940.KS", "005380.KS",
           "012330.KS", "068270.KS", "051910.KS", "005490.KS", "028260.KS"]
PASS = {"profit_factor": 1.5, "mdd_pct": -15.0, "sharpe_ratio": 1.0}
CAPITAL = 10_000_000.0                                    # 엔진 기본값과 같은 시작 자금(자동매매 가상계좌)


def _frame(symbol: str, end: date) -> pd.DataFrame:
    data = read_daily_candles(symbol, "max", today=end)
    if not data:
        raise SystemExit(f"수집 DB 에서 {symbol} 일봉을 읽지 못했습니다(이 PC 에 수집 DB 가 있어야 합니다).")
    df = pd.DataFrame(data["candles"])
    df.index = pd.to_datetime(df["time"], unit="s")
    return df[df.index.date <= end][["open", "high", "low", "close"]].astype(float)


def _trade_stats(trades: list[dict]) -> dict:
    """거래 단위 PF · 승률 — 엔진 `sizing.trades` 의 거래마다 손익(원 · 비용 뗀 뒤)으로 센다. 0주 거래는 따로 센다."""
    pnl = [t["pnl"] for t in trades if t["quantity"] > 0]
    gain, loss = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    return {"trades": len(pnl), "zero_qty_trades": len(trades) - len(pnl),
            "win_rate_trade_pct": round(100 * sum(x > 0 for x in pnl) / len(pnl), 2) if pnl else None,
            "profit_factor": round(gain / loss, 3) if loss > 0 else None}


def _dsr(net: pd.Series) -> float | None:
    """시도 수 = 조합표 줄 수 × 종목 수(110)로 낸 DSR(보조). 값이 안 나오면(표본 부족 등) None."""
    v = evaluation_risk.calculate_all_metrics(net.values, n_trials=len(GRID) * len(SYMBOLS))["Deflated Sharpe Ratio"]
    return None if v != v else round(float(v), 4)


def _passed(row: dict) -> bool:
    pf = row["profit_factor"]
    return bool(pf is not None and pf > PASS["profit_factor"] and row["mdd_pct"] > PASS["mdd_pct"]
                and row["sharpe_ratio"] > PASS["sharpe_ratio"])


def nearest(rows: list[dict]) -> dict | None:
    """합격이 없을 때 참고로만 보이는 「가장 가까운 조합」 — 넘은 기준 수가 많은 것 → 같으면 샤프가 높은 것.

    실행 전에 정한 규칙이다(결과를 본 뒤 고치지 않는다 · #363 2026-10-30). 고르는 것이 아니다.
    """
    if not rows or any(r["pass"] for r in rows):
        return None
    def met(r):
        return sum([r["profit_factor"] is not None and r["profit_factor"] > PASS["profit_factor"],
                    r["mdd_pct"] > PASS["mdd_pct"], r["sharpe_ratio"] > PASS["sharpe_ratio"]])
    best = max(rows, key=lambda r: (met(r), r["sharpe_ratio"]))
    return {"symbol": best["symbol"], "short": best["short"], "long": best["long"], "criteria_met": met(best)}


def run(symbol: str, end: date) -> dict:
    df = _frame(symbol, end)
    card = template()
    st, ps = card["stops"], card["position_sizing"]
    cost = trading_cost.KrxCostModel()
    size = {"risk_pct": ps["risk_pct"], "max_position_pct": ps["max_position_pct"], "initial_capital": CAPITAL}
    rows = []
    for short, long in GRID:
        sig = (ta_utils.sma(df["close"], short) > ta_utils.sma(df["close"], long)).astype(int)
        res = quant_pipeline.backtest(df, sig, cost=cost, entry_mode=card["entry_mode"], exit_mode=card["exit_mode"],
                                      atr_period=st["atr_period"], atr_mult=st["atr_mult"], take_rr=st["take_rr"], **size)
        # 엔진과 같은 보유 상태(손절 · 익절 반영) · 같은 수량 함수로 일별 순수익을 다시 만든다(DSR 에 쓴다)
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
            raise SystemExit(f"{symbol} {short}·{long}: 다시 만든 누적 수익 {total:.4f}% ≠ 엔진 {res['total_return_pct']}% — 식이 갈렸다")
        row = {"symbol": symbol, "short": short, "long": long} | _trade_stats(res["sizing"]["trades"]) | {
               "total_return_pct": res["total_return_pct"], "sharpe_ratio": res["sharpe_ratio"],
               "mdd_pct": res["mdd_pct"], "buy_hold_return_pct": res["buy_hold_return_pct"], "cost_drag_pct": res["cost_drag_pct"],
               "stop_exits": res["stop_loss_exits"], "take_exits": res["take_profit_exits"],
               "avg_weight_pct": round(sum(t["weight_pct"] for t in res["sizing"]["trades"]) / len(res["sizing"]["trades"]), 2)
               if res["sizing"]["trades"] else None}
        row["dsr"] = _dsr(net)
        row["pass"] = _passed(row)
        rows.append(row)
    return {"symbol": symbol, "start": df.index[0].date().isoformat(), "end": df.index[-1].date().isoformat(),
            "bars": len(df), "card": card, "trials": rows}


def run_all(end: date, symbols: list[str] | None = None) -> dict:
    """조합표 11개 × 종목 10개 = 110개를 모두 돌린다 — 시도 번호는 종목 순서 · 조합표 순서."""
    per = [run(s, end) for s in (symbols or SYMBOLS)]
    rows = [r for p in per for r in p["trials"]]
    for n, r in enumerate(rows, 1):
        r["trial"] = n
    card = per[0]["card"]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"symbols": [{k: p[k] for k in ("symbol", "start", "end", "bars")} for p in per],
            "card": {k: card[k] for k in ("strategy_id", "version", "entry_mode", "exit_mode")}
                    | {"stops": card["stops"], "position_sizing": card["position_sizing"]},
            "initial_capital": CAPITAL, "cost": trading_cost.describe(trading_cost.KrxCostModel()),
            "definition": ta_utils.DEFINITION, "pass_line": PASS, "commit": commit,
            "n_trials": len(rows), "dsr_n_trials": len(GRID) * len(SYMBOLS), "passed": sum(r["pass"] for r in rows),
            "nearest": nearest(rows), "trials": rows}


def main() -> None:
    for stream in (sys.stdout, sys.stderr):                # Windows 콘솔(cp949)에서도 ✅ · — 가 찍히게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", action="append", default=None, help="종목만 골라 돌리기(시험용) — 없으면 SYMBOLS 10개")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--out", default=None, help="결과 JSON 을 쓸 폴더(없으면 화면에만)")
    a = ap.parse_args()
    out = run_all(date.fromisoformat(a.end), a.symbol)
    for m in out["symbols"]:
        print(f"{m['symbol']} · {m['start']} ~ {m['end']} · {m['bars']}봉")
    print(f"시도 {out['n_trials']}개 · 합격 {out['passed']}개 · 참고(가장 가까움) {out['nearest']}")
    print("| # | 종목 | 단기 | 장기 | 거래 | 승률(거래) | PF | 수익(비용 뒤) | 샤프 | MDD | 평균 비중 | DSR(보조) | 합격 |")
    for r in out["trials"]:
        print(f"| {r['trial']} | {r['symbol'][:6]} | {r['short']} | {r['long']} | {r['trades']} | {r['win_rate_trade_pct']} | "
              f"{r['profit_factor']} | {r['total_return_pct']} | {r['sharpe_ratio']} | {r['mdd_pct']} | {r['avg_weight_pct']} | "
              f"{r['dsr']} | {'✅' if r['pass'] else '—'} |")
    if a.out:
        p = Path(a.out)
        p.mkdir(parents=True, exist_ok=True)
        (p / "trials.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
