"""리밸런싱 세 방식 — 비중 이탈 · 신호 판정 · 주문안 · 규칙별 횟수 비교 (합성 데이터).

실행    python rebalance_rules.py      (numpy 와 표준 라이브러리만 · 외부 접속 없음)
자료    ①~④ 는 손으로 정한 가격 · 수량. ⑤ 는 난수로 만든 두 자산 수익률이다(실제 시세가 아니다).
        ①~④ 의 규칙은 앱의 app/services/rebalance_policy.py 와 같은 판정을 짧게 옮긴 것이다
        (같은 입력으로 앱 함수를 돌려 숫자가 같음을 확인했다).

함수
    bp(percent)                           퍼센트 → 만분율 정수(ROUND_HALF_UP). 소수 그대로 비교하면 경계에서 흔들린다
    weights(cash, holdings, targets, th)  지금 비중 · 목표와의 차이 · 가장 크게 벗어난 값
    choose_triggers(...)                  시간 · 이탈률 · 현금흐름 신호 중 켜지는 것
    cashflow_signal(excess, budget, th)   입출금 신호
    orders(...)                           목표 금액과 지금 금액의 차이 → 정수 수량 주문 (ETF 만)
    simulate(rule, ...)                   규칙별 횟수 · 최대 이탈 · 변동성 (합성 수익률)

그림 만드는 코드(tools/learn_figs/rebalancing-methods.py)도 이 파일의 함수를 그대로 불러 쓴다.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import unicodedata

import numpy as np

# 비용 상수(편도 비율) — 2026-11-03 앱의 비용 모델과 같은 값 · 온라인 계좌. ETF 는 증권거래세가 없다.
FEE_ONLINE_KRX = 0.000140527
FEE_CLEARING = 0.000036396

MONTHS, PATHS, SEED = 240, 1000, 11     # 20년 × 1,000경로
TARGET = 0.6                            # 목표 주식 비중


def pad(text: str, width: int) -> str:
    """한글을 두 칸으로 세어 오른쪽을 공백으로 채운다(표 열이 맞게)."""
    cols = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - cols)


def bp(percent: float) -> int:
    """퍼센트 × 100 을 반올림한 정수(0.01%p 단위). 66.6951… 같은 소수를 그대로 비교하면 경계(5.0%p)에서 판정이 흔들린다."""
    return int((Decimal(str(percent)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def weights(cash, holdings, targets, threshold_pct):
    """holdings {종목: 평가금액}, targets {종목: 목표 %}. 현금 목표 = 100 − 목표 합. 이탈 = |지금 − 목표| 의 최댓값."""
    total = cash + sum(holdings.values())
    rows = []
    for sym in sorted(set(targets) | set(holdings)):
        cur = holdings.get(sym, 0) / total * 100
        rows.append((sym, bp(cur) / 100, targets.get(sym, 0.0), (bp(cur) - bp(targets.get(sym, 0.0))) / 100))
    cash_target = 100 - sum(targets.values())
    cash_cur = cash / total * 100
    rows.append(("현금", bp(cash_cur) / 100, cash_target, (bp(cash_cur) - bp(cash_target)) / 100))
    worst = max(abs(r[3]) for r in rows)
    # 경계값(정확히 기준)에서도 켜진다: 「이상」(>=)
    return dict(total=total, rows=rows, max_drift=worst, drift_due=bp(worst) >= bp(threshold_pct))


def choose_triggers(time_due, drift_due, mode, cashflow_due):
    """always: 시간 · 이탈률이 각각 켜진다. scheduled: 정기일이면서 이탈이 기준 이상일 때만 둘이 함께 켜진다."""
    out = []
    if mode == "scheduled":
        if time_due and drift_due:
            out += ["TIME", "DRIFT"]
    else:
        if time_due:
            out.append("TIME")
        if drift_due:
            out.append("DRIFT")
    if cashflow_due:
        out.append("CASHFLOW")
    return out


def cashflow_signal(excess, budget, threshold):
    """남는(+) 또는 모자란(−) 현금과 아직 배분하지 않은 입출금 예산의 부호가 같을 때, 작은 쪽이 기준 이상이면 켜진다."""
    eligible = min(abs(excess), abs(budget)) if excess * budget > 0 else 0
    return dict(due=eligible > 0 and eligible >= threshold, usable=eligible, plan="buy_only" if budget > 0 else "sell_only")


def etf_cost(price, qty):
    """ETF 한 건의 수수료(거래소 + 청산) — 증권거래세 없음. 원 단위."""
    return price * qty * (FEE_ONLINE_KRX + FEE_CLEARING)


def orders(total, cash, rows, cash_target_pct, min_order):
    """rows: [(종목, 목표%, 보유수량, 가격)]. 차액 → 정수 수량, 매도 먼저, 매수는 현금 목표를 남기는 만큼만, 최소 주문금액 미만은 뺌."""
    reserve = total * cash_target_pct / 100
    todo = []
    for sym, tgt, qty_held, price in rows:
        diff = total * tgt / 100 - qty_held * price
        side = "BUY" if diff > 0 else "SELL"
        qty = int(abs(diff) // price)
        if side == "SELL":
            qty = min(qty, qty_held)
        if qty > 0 and qty * price >= min_order:
            todo.append((0 if side == "SELL" else 1, -abs(diff), sym, side, qty, price))
    todo.sort()
    out, spent_cost = [], 0.0
    for _, _, sym, side, qty, price in todo:
        if side == "BUY":
            unit = price + etf_cost(price, 1)
            qty = min(qty, int(max(0, cash - reserve) // unit))
            if qty <= 0 or qty * price < min_order:
                continue
            cash -= price * qty + etf_cost(price, qty)
        else:
            cash += price * qty - etf_cost(price, qty)
        spent_cost += etf_cost(price, qty)
        out.append((side, sym, qty, price, etf_cost(price, qty)))
    return out, cash, spent_cost


def make_returns(paths=PATHS, months=MONTHS, seed=SEED):
    """합성 월 수익률. 주식 연 7% · 변동성 16%, 채권 연 3% · 변동성 5%, 서로 독립. 실제 시장이 아니다."""
    rng = np.random.default_rng(seed)
    rs = rng.normal(0.07 / 12, 0.16 / np.sqrt(12), (paths, months))
    rb = rng.normal(0.03 / 12, 0.05 / np.sqrt(12), (paths, months))
    return rs, rb


RULES = {
    "안 함": None,
    "시간 12개월": lambda m, w: np.full(w.shape, (m + 1) % 12 == 0),
    "시간 3개월": lambda m, w: np.full(w.shape, (m + 1) % 3 == 0),
    "이탈률 5%p(월 점검)": lambda m, w: np.abs(w - TARGET) >= 0.05,
    "이탈률 2%p(월 점검)": lambda m, w: np.abs(w - TARGET) >= 0.02,
    "시간 12개월 + 5%p": lambda m, w: ((m + 1) % 12 == 0) & (np.abs(w - TARGET) >= 0.05),
    "현금흐름만(매달 입금 1)": "cashflow",
}


def simulate(rule, rs, rb, keep_path=None):
    """자산 100(주식 60 · 채권 40)에서 시작. 규칙이 켜지면 목표 60/40 으로 되돌린다(비용 · 세금 없음).
    현금흐름 규칙은 매달 1 을 입금해 목표보다 모자란 쪽에만 넣는다(매도 없음).
    keep_path 가 경로 번호면 그 경로의 (월별 주식 비중, 리밸런싱한 달) 도 돌려준다."""
    paths, months = rs.shape
    s, b = np.full(paths, 60.0), np.full(paths, 40.0)
    events = np.zeros(paths); worst = np.zeros(paths); wsum = np.zeros(paths)
    traded = np.zeros(paths); asum = np.zeros(paths); rets = np.zeros((paths, months))
    wpath, fired = [], []
    for m in range(months):
        before = s + b
        s = s * (1 + rs[:, m]); b = b * (1 + rb[:, m])
        total = s + b
        rets[:, m] = total / before - 1
        w = s / total
        worst = np.maximum(worst, np.abs(w - TARGET))
        if rule == "cashflow":                       # 입금 1 을 모자란 쪽에 (갭보다 많이 넣지 않는다)
            gap_s = np.maximum(TARGET * total - s, 0); gap_b = np.maximum((1 - TARGET) * total - b, 0)
            s = s + np.minimum(1.0, gap_s); b = b + np.minimum(1.0, gap_b)
            total = s + b
            w = s / total
            fire = np.zeros(paths, dtype=bool)
        elif rule is None:
            fire = np.zeros(paths, dtype=bool)
        else:
            fire = rule(m, w)
            traded += np.where(fire, np.abs(s - TARGET * total), 0)     # 한쪽(매도액 = 매수액)
            s = np.where(fire, TARGET * total, s); b = np.where(fire, (1 - TARGET) * total, b)
            events += fire
        wsum += w; asum += total
        if keep_path is not None:
            wpath.append(float(w[keep_path])); fired.append(bool(fire[keep_path]))
    out = dict(events=events.mean(), equity=wsum.mean() / months * 100, worst=worst.mean() * 100,
               traded=(traded / (asum / months)).mean() * 100, vol=rets.std(axis=1, ddof=1).mean() * np.sqrt(12) * 100)
    return (out, np.array(wpath), np.array(fired)) if keep_path is not None else out


def main() -> None:
    targets = {"STOCK": 60.0, "BOND": 35.0}

    def show(title, cash, holdings):
        snap = weights(cash, holdings, targets, 5.0)
        print(f"{title} 총자산 {snap['total']:,.0f}원")
        for sym, cur, tgt, drift in snap["rows"]:
            print(f"  {pad(sym, 5)} 지금 {cur:.2f}% · 목표 {tgt:.1f}% · 벗어남 {drift:+.2f}%p")
        print(f"  가장 크게 벗어남 {snap['max_drift']:.2f}%p · 기준 5.0%p 이상: {snap['drift_due']}")
        return snap

    print("① 비중은 저절로 바뀝니다 (목표 STOCK 60% · BOND 35% · 현금 5% · 합성 가격)")
    show("[처음]", 500_000, {"STOCK": 6_000_000, "BOND": 3_500_000})
    after = show("[주식 +30% · 채권 -3% 뒤]", 500_000, {"STOCK": 7_800_000, "BOND": 3_395_000})

    print("② 신호 판정 (현금흐름 없음)")
    print("  정기일  이탈률  always                scheduled")
    for td, dd in ((False, True), (True, True), (True, False), (False, False)):
        a = choose_triggers(td, dd, "always", False); s = choose_triggers(td, dd, "scheduled", False)
        print(f"  {'도래' if td else '아님'}    {'이상' if dd else '미만'}    {str(a):<21} {s}")

    print("③ 현금흐름 신호 (기준 100,000원)")
    for label, ex, bud in (("입금 300만 원", 3_000_000, 3_000_000), ("입금 5만 원", 50_000, 50_000),
                           ("출금 예산인데 남는 현금", 3_000_000, -3_000_000)):
        r = cashflow_signal(ex, bud, 100_000)
        print(f"  {pad(label, 24)} → 켜짐 {r['due']} · 쓸 수 있는 돈 {r['usable']:,}원 · 계획 {r['plan']}")

    print("④ 주문안 (STOCK 600주 × 13,000원 · BOND 350주 × 9,700원 · 최소 주문금액 10,000원 · ETF 로 가정)")
    plan, cash_after, cost = orders(after["total"], 500_000, [("STOCK", 60.0, 600, 13_000), ("BOND", 35.0, 350, 9_700)], 5.0, 10_000)
    for side, sym, qty, price, c in plan:
        print(f"  {side:<4} {sym:<5} {qty}주 × {price:,}원 · 비용 {c:,.0f}원")
    print(f"  주문 뒤 현금(추정) {cash_after:,.0f}원 · 비용 합 {cost:,.0f}원")

    rs, rb = make_returns()
    print(f"⑤ 규칙별 비교 (합성 데이터 · 주식 연 7% 변동성 16% · 채권 연 3% 변동성 5% · 서로 독립 · {PATHS:,}경로 × {MONTHS}개월 평균 · 시드 {SEED} · 비용 없음)")
    print(f"  {pad('규칙', 24)}{'횟수':>5}  {'평균 주식%':>8}  {'최대 이탈%p':>9}  {'매매액%':>6}  {'연변동성%':>7}")
    for name, rule in RULES.items():
        r = simulate(rule, rs, rb)
        print(f"  {pad(name, 24)}{r['events']:>5.1f}  {r['equity']:>8.1f}  {r['worst']:>9.1f}  {r['traded']:>6.0f}  {r['vol']:>7.1f}")


if __name__ == "__main__":
    main()
