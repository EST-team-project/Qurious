"""SCH-ROB 의견용 — trials.json(110개)만으로 만든 민감도 표. 새 백테스트 없음(읽기 전용)."""
import json
import statistics as st
import sys

sys.stdout.reconfigure(encoding="utf-8")
P = r"docs/phase-3/04-testing/기준전략-시도-2026-10-30/trials.json"
j = json.load(open(P, encoding="utf-8"))
T = j["trials"]
print("합격선:", json.dumps(j["pass_line"], ensure_ascii=False))
print("nearest:", json.dumps(j["nearest"], ensure_ascii=False)[:300])
print("시도", len(T), "· 합격", sum(1 for t in T if t["pass"]))

by = {}
for t in T:
    by.setdefault((t["short"], t["long"]), {})[t["symbol"]] = t
combos = sorted(by)
print("\n[1] 조합별 10종목 요약 (샤프 중앙값 · 샤프>0 종목 수 · PF 중앙값 · MDD 중앙값 · 수익률 중앙값 · 매수보유 대비 이긴 종목)")
print("조합      샤프중앙 샤프>0  PF중앙  MDD중앙  수익률중앙  이김")
for c in combos:
    xs = list(by[c].values())
    sh = [x["sharpe_ratio"] for x in xs]
    pf = [x["profit_factor"] for x in xs]
    md = [x["mdd_pct"] for x in xs]
    rt = [x["total_return_pct"] for x in xs]
    win = sum(1 for x in xs if x["total_return_pct"] > x["buy_hold_return_pct"])
    print(f"{c[0]:>2}·{c[1]:<4}  {st.median(sh):>7.3f} {sum(1 for s in sh if s>0):>5}  {st.median(pf):>6.3f} {st.median(md):>7.2f} {st.median(rt):>9.2f} {win:>5}")

print("\n[2] 가장 가까운 시도(SK하이닉스 20·60)의 이웃 — 같은 종목에서 조합만 한 칸 옮김")
sym = [t["symbol"] for t in T if t["short"] == 20 and t["long"] == 60 and "000660" in t["symbol"]][0]
for c in [(20, 40), (20, 60), (20, 120), (10, 60), (10, 120), (10, 40)]:
    x = by[c][sym]
    print(f"{sym} {c[0]:>2}·{c[1]:<4} 샤프 {x['sharpe_ratio']:>6.3f}  PF {x['profit_factor']:>6.3f}  MDD {x['mdd_pct']:>6.2f}  수익률 {x['total_return_pct']:>7.2f}  매수보유 {x['buy_hold_return_pct']:>8.2f}  거래 {x['trades']}  합격 {x['pass']}")

print("\n[3] 20·60 이 다른 종목에서도 버티는가 — 종목별 20·60 샤프 · 순위(그 종목 11개 조합 중)")
rows = []
for s in sorted({t['symbol'] for t in T}):
    allc = sorted([(by[c][s]['sharpe_ratio'], c) for c in combos], reverse=True)
    rank = [i + 1 for i, (_, c) in enumerate(allc) if c == (20, 60)][0]
    x = by[(20, 60)][s]
    rows.append((s, x['sharpe_ratio'], rank, x['profit_factor'], x['mdd_pct'], x['total_return_pct'], x['buy_hold_return_pct']))
    print(f"{s:<10} 샤프 {x['sharpe_ratio']:>6.3f}  11개 중 {rank:>2}위  PF {x['profit_factor']:>6.3f}  MDD {x['mdd_pct']:>6.2f}  수익률 {x['total_return_pct']:>7.2f}  매수보유 {x['buy_hold_return_pct']:>8.2f}")
print("20·60 샤프>0 종목:", sum(1 for r in rows if r[1] > 0), "/ 10 · 중앙값 순위:", st.median([r[2] for r in rows]))

print("\n[4] 어떤 시도도 매수 후 보유를 이긴 적이 있나")
print("이긴 시도:", sum(1 for t in T if t['total_return_pct'] > t['buy_hold_return_pct']), "/", len(T))
print("샤프>=1.0:", sum(1 for t in T if t['sharpe_ratio'] >= 1.0), " 샤프 최대:", max(t['sharpe_ratio'] for t in T))
print("0주 거래가 있는 시도:", sum(1 for t in T if t['zero_qty_trades'] > 0), "· 평균 비중 중앙값 %:", st.median(t['avg_weight_pct'] for t in T))
