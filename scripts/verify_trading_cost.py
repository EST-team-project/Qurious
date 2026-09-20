"""매매비용 계산을 검증한다 — 요율표 대조 + 실데이터 재현.

왜 스크립트로 남기는가
--------------------
Issue #40 의 실측(무비용 28.09% → 실제 비용 14.37% → 슬리피지 20bp −6.95%)은
일회용 스크립트로 계산해 남아 있지 않았다. 그래서 같은 값을 다시 만들 수 없고,
구현이 그 결론을 재현하는지도 확인할 수 없었다. 계산을 파일로 남겨 둔다.

쓰는 법 ::

    PYTHONPATH=<저장소 루트> python scripts/verify_trading_cost.py          # 요율표만
    PYTHONPATH=<저장소 루트> python scripts/verify_trading_cost.py --repro   # 실데이터 재현까지

`--repro` 는 수집기 SQLite(`data/market.sqlite3`)의 `price_total_return` 을 읽는다.
그 표가 없으면(수집 전) 요율표 검증만 돌고 재현은 건너뛴다.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from app.services import trading_cost as tc
from app.services.quant_pipeline import backtest

#: Issue #40 5.3 표의 매도세 합계 — 코스피와 코스닥이 같아야 한다
EXPECTED_SELL_TAX = {
    2019: 0.0025, 2020: 0.0025, 2021: 0.0023, 2022: 0.0023,
    2023: 0.0020, 2024: 0.0018, 2025: 0.0015, 2026: 0.0020,
}

#: Issue #40 6절 실측 — S33 에 별도 스크립트로 계산한 값 (표본 선정이 달라 오차가 있다)
ISSUE40_MEDIAN = {
    "무비용": 28.09, "현행 flat 10bps": 16.62, "실제(슬립 0)": 14.37,
    "실제+슬립 10bp": 2.81, "실제+슬립 20bp": -6.95,
}


def check_tax_table() -> bool:
    """요율표가 Issue #40 5.3 과 맞는지, 세목 분리가 합계를 보존하는지."""
    print("── 1. 연도별 매도세 합계 (코스피 = 거래세+농특세 / 코스닥 = 거래세) ──")
    ok = True
    for year, want in sorted(EXPECTED_SELL_TAX.items()):
        got = {}
        for market in ("KOSPI", "KOSDAQ"):
            transfer, rural = tc.tax_rates(f"{year}-07-01", market)
            got[market] = transfer + rural
        same = abs(got["KOSPI"] - got["KOSDAQ"]) < 1e-12
        right = abs(got["KOSPI"] - want) < 1e-12
        ok = ok and same and right
        mark = "OK" if (same and right) else "틀림"
        print(f"   {year}  코스피 {got['KOSPI']*100:.4f}%  코스닥 {got['KOSDAQ']*100:.4f}%  "
              f"(기대 {want*100:.2f}%)  {mark}")

    print("\n── 2. 방향 · ETF · 시장 구분 ──")
    buy = tc.cost_rate("buy", "2026-09-18", slippage_bps=10.0)
    sell = tc.cost_rate("sell", "2026-09-18", slippage_bps=10.0)
    etf = tc.cost_rate("sell", "2026-09-18", slippage_bps=10.0, is_etf=True)
    print(f"   매수 편도 {buy*100:.6f}%  ·  매도 편도 {sell*100:.6f}%  ·  매도 ETF {etf*100:.6f}%")
    print(f"   왕복 2026 {tc.round_trip_rate('2026-09-18')*100:.6f}%  vs  "
          f"현행 대칭 10bp {0.2:.6f}%  → {tc.round_trip_rate('2026-09-18')/0.002:.2f}배")
    ok = ok and buy < sell and abs(etf - buy) < 1e-12

    print("\n── 3. 정산금액 (삼성전자 100주 @70,000 · 2026년) ──")
    for side in ("buy", "sell"):
        oc = tc.order_costs(side, 70_000, 100, "2026-09-18")
        print(f"   {side:4} 체결 {oc.gross_amount:>11,.0f}  수수료 {oc.commission:>8,.2f}  "
              f"유관 {oc.fee_clearing:>7,.2f}  거래세 {oc.tax_transfer:>9,.2f}  "
              f"농특 {oc.tax_rural:>9,.2f}  → 정산 {oc.net_amount:>12,.2f}")
    b = tc.order_costs("buy", 70_000, 100, "2026-09-18")
    s = tc.order_costs("sell", 70_000, 100, "2026-09-18")
    # 매수는 현금이 더 나가고, 매도는 덜 들어온다
    ok = ok and b.net_amount > b.gross_amount and s.net_amount < s.gross_amount
    # 세목을 쪼개도 합계는 시장과 무관하게 같다 (코넥스만 예외)
    kq = tc.order_costs("sell", 70_000, 100, "2026-09-18", market="KOSDAQ")
    ok = ok and abs((s.tax_transfer + s.tax_rural) - (kq.tax_transfer + kq.tax_rural)) < 1e-9

    print("\n── 4. 세율 경계에서 실제로 갈리는가 ──")
    for day in ("2019-06-02", "2019-06-03", "2024-12-31", "2025-01-02", "2025-12-31", "2026-01-02"):
        t, r = tc.tax_rates(day, "KOSPI")
        print(f"   {day}  코스피 매도세 {(t+r)*100:.4f}%")

    print("\n── 5. 보유비중 변화가 매수분·매도분으로 갈리는가 ──")
    idx = pd.to_datetime(["2025-12-29", "2025-12-30", "2026-01-02", "2026-01-05"])
    held = pd.Series([0.0, 1.0, 1.0, 0.0], index=idx)
    series = tc.KrxCostModel(slippage_bps=10.0).turnover_cost(held)
    for when, h, v in zip(idx, held, series):
        print(f"   {when.date()}  보유 {h:.0f}  차감 {v*100:.6f}%")
    ok = ok and abs(series.iloc[1] - tc.cost_rate("buy", "2025-12-30")) < 1e-12
    ok = ok and abs(series.iloc[3] - tc.cost_rate("sell", "2026-01-05")) < 1e-12
    return ok


def repro_issue40(limit: int = 300) -> None:
    """Issue #40 6절 실측을 다시 계산한다 — 5/20 이동평균 교차 롱온리."""
    try:
        from collector import db as cdb
    except ImportError:
        print("수집기를 불러올 수 없다 — 재현을 건너뛴다")
        return
    conn = cdb.connect()
    try:
        rows = conn.execute("""
            SELECT srtn_cd, COUNT(*) AS n FROM price_total_return
             GROUP BY srtn_cd HAVING n > 1200 ORDER BY srtn_cd LIMIT ?
        """, (limit,)).fetchall()
    except Exception as exc:
        print(f"price_total_return 을 읽을 수 없다 ({exc}) — 재현을 건너뛴다")
        conn.close()
        return
    if not rows:
        print("TR 계열이 비어 있다 — `python -m collector.total_return build` 가 먼저다")
        conn.close()
        return

    scenarios = {
        "무비용": None,
        "현행 flat 10bps": tc.FlatCostModel(cost_bps=10.0),
        "실제(슬립 0)": tc.KrxCostModel(slippage_bps=0.0),
        "실제+슬립 10bp": tc.KrxCostModel(slippage_bps=10.0),
        "실제+슬립 20bp": tc.KrxCostModel(slippage_bps=20.0),
    }
    out: dict[str, list[float]] = {k: [] for k in scenarios}
    trades: list[int] = []

    for (code, _n) in rows:
        raw = conn.execute(
            "SELECT bas_dt, tr_index FROM price_total_return WHERE srtn_cd=? ORDER BY bas_dt",
            (code,),
        ).fetchall()
        df = pd.DataFrame(raw, columns=["bas_dt", "close"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna()
        if len(df) < 200:
            continue
        df.index = pd.to_datetime(df["bas_dt"].astype(str), format="%Y%m%d")
        df = df[["close"]]
        if df["close"].le(0).any():
            continue

        ma_short = df["close"].rolling(5).mean()
        ma_long = df["close"].rolling(20).mean()
        regime = pd.Series(np.nan, index=df.index)
        regime.loc[(ma_short > ma_long) & (ma_short.shift(1) <= ma_long.shift(1))] = 1.0
        regime.loc[(ma_short < ma_long) & (ma_short.shift(1) >= ma_long.shift(1))] = 0.0
        signals = regime.ffill().fillna(0.0)

        for i, (name, model) in enumerate(scenarios.items()):
            bt = backtest(df, signals, cost=model)
            out[name].append(bt["total_return_pct"])
            if i == 0:
                trades.append(bt["trade_count"])
    conn.close()

    base = np.array(out["무비용"])
    print(f"\n── Issue #40 6절 재현 · 표본 {len(base)}종목 · 매매횟수 중앙값 {np.median(trades):.0f}회 ──")
    print(f"   {'시나리오':<18}{'중앙값':>9}{'#40 값':>9}{'차이':>8}{'손실':>7}{'이익→손실':>10}")
    gained = base > 0
    for name in scenarios:
        arr = np.array(out[name])
        med = float(np.median(arr))
        want = ISSUE40_MEDIAN[name]
        print(f"   {name:<18}{med:>9.2f}{want:>9.2f}{med-want:>8.2f}"
              f"{int((arr <= 0).sum()):>7}{int((gained & (arr <= 0)).sum()):>10}")
    print(f"   무비용에서 이익이던 종목 {int(gained.sum())}개")
    print("   ※ 표본 선정 규칙이 S33 스크립트와 같은지 확인할 수 없어 중앙값에 오차가 남는다.")


if __name__ == "__main__":
    passed = check_tax_table()
    print(f"\n요율표 검증: {'통과' if passed else '실패'}")
    if "--repro" in sys.argv:
        repro_issue40()
    if not passed:
        sys.exit(1)
