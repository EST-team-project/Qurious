"""수정주가 — 끊긴 가격 계열을 조정계수로 이어 붙이고, 배당을 더한 총수익과 비교하는 예제.

실행    python adjusted_price.py      (표준 라이브러리만)
자료    금융위원회 「주식시세정보」(공공데이터포털) · 배당은 DART 공시 — 설명에 필요한 몇 줄만 교육용으로 인용했다(재배포용 자료가 아니다).
        카카오(035720) 액면분할 2021-04-15 · 가온전선(000500) 권리락 2026-06-30 · 삼성전자(005930) 배당락 2025-12-29

함수
    factors(rows)          날마다 「그날 가격이 직전과 이어지나」 를 나타내는 계수 = (종가 − 전일대비) ÷ 직전 종가
    cumulative(fs)         날마다 곱할 누적 계수 — 가장 최근 날이 1.0, 끊김은 그 이전 전부에 곱한다
    weekly(bars)           월~금을 봉 하나로(이 예제의 자료에는 거래정지일이 없다)
"""
from __future__ import annotations

from datetime import date


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


# 기준일 · 종가 · 전일대비(원자료 vs)
KAKAO = [(_d(d), int(c), int(v)) for d, c, v in (line.split() for line in """
20210408 548000 6000
20210409 558000 10000
20210412 558000 0
20210413 558000 0
20210414 558000 0
20210415 120500 8500
20210416 119000 -1500
""".strip().splitlines())]

# 기준일 · 시가 · 고가 · 저가 · 종가 · 전일대비
GAON = [(_d(d), int(o), int(h), int(l), int(c), int(v)) for d, o, h, l, c, v in (line.split() for line in """
20260622 353500 360000 321000 338500 1000
20260623 349500 384000 328000 331500 -7000
20260624 328500 332000 299000 311500 -20000
20260625 319500 320000 292500 298500 -13000
20260626 308000 343500 283000 329000 30500
20260629 329500 353500 320500 343000 14000
20260630 240000 244000 210500 233500 42900
20260701 262000 303500 257000 300500 67000
20260702 273000 326000 270000 280000 -20500
20260703 311500 313500 261500 277500 -2500
""".strip().splitlines())]

# 삼성전자 기준일 · 종가 — 2025-12-29 가 배당락일(1주당 결산배당 566원)
SAMSUNG = [(_d("20251224"), 111100), (_d("20251226"), 117000), (_d("20251229"), 119500), (_d("20251230"), 119900)]
DIVIDEND = {_d("20251229"): 566}


def factors(rows: list[tuple]) -> list[tuple[date, float]]:
    """rows 의 각 줄은 (날짜, …, 종가, 전일대비) — 끝의 두 칸만 쓴다."""
    out, prev = [], None
    for r in rows:
        day, close, vs = r[0], r[-2], r[-1]
        f = (close - vs) / prev if prev else 1.0      # 첫날은 비교할 직전이 없다
        out.append((day, f))
        prev = close
    return out


def cumulative(fs: list[tuple[date, float]]) -> dict[date, float]:
    cum, c = {}, 1.0
    for day, f in reversed(fs):                       # 뒤에서 앞으로 — 오늘 가격은 그대로 둔다
        cum[day] = c
        c *= f
    return cum


def weekly(bars: list[tuple]) -> list[tuple]:
    """bars 의 각 줄은 (날짜, 시가, 고가, 저가, 종가). 주(ISO)마다 (마지막 날, 시가, 고가, 저가, 종가)."""
    weeks: dict[tuple[int, int], list[tuple]] = {}
    for b in bars:
        weeks.setdefault(b[0].isocalendar()[:2], []).append(b)
    return [(w[-1][0], w[0][1], max(b[2] for b in w), min(b[3] for b in w), w[-1][4]) for w in weeks.values()]


def won(x: float) -> str:
    return f"{x:>9,.0f}"


def main() -> None:
    print("① 카카오 — 계수가 1 이 아닌 날")
    fs = factors(KAKAO)
    for (day, close, vs), (_, f) in zip(KAKAO, fs):
        if abs(f - 1) > 1e-9:
            print(f"  {day}  계수 {f:.7f}  (기준가 {close - vs:,} ÷ 직전 종가 558,000)")
    print(f"  「1주를 5주로」 만 보고 나누면 계수 0.2 · 기준가 {558000 / 5:,.0f} — 실제 기준가와 {112000 - 558000 / 5:,.0f}원 차이")

    print("② 카카오 — 2021-04-15 하루 수익률")
    cum = cumulative(fs)
    raw = 120500 / 558000 - 1
    adj = 120500 / (558000 * cum[_d("20210414")]) - 1
    print(f"  원 가격    120,500 ÷ 558,000 − 1 = {raw:+.2%}")
    print(f"  수정 가격  120,500 ÷ (558,000 × {cum[_d('20210414')]:.7f}) − 1 = {adj:+.2%}")

    print("③ 가온전선 — 권리락(2026-06-30 화)이 낀 주의 주봉")
    g_fs = factors(GAON)
    g_cum = cumulative(g_fs)
    for day, f in g_fs:
        if abs(f - 1) > 1e-9:
            print(f"  계수가 1 이 아닌 날 {day}  계수 {f:.7f}  → 그 전날까지 곱할 누적 계수 {g_cum[_d('20260629')]:.7f}")
    raw_bars = [(d, o, h, l, c) for d, o, h, l, c, _ in GAON]
    adj_bars = [(d, o * g_cum[d], h * g_cum[d], l * g_cum[d], c * g_cum[d]) for d, o, h, l, c, _ in GAON]
    rw, aw = weekly(raw_bars), weekly(adj_bars)
    print("                          시가       고가       저가       종가   주간 수익률")
    print(f"  원 주봉            {won(rw[1][1])}  {won(rw[1][2])}  {won(rw[1][3])}  {won(rw[1][4])}   {rw[1][4] / rw[0][4] - 1:+.1%}")
    print(f"  원 주봉 × 계수 1.0 {won(rw[1][1])}  {won(rw[1][2])}  {won(rw[1][3])}  {won(rw[1][4])}   (그 주 마지막 날의 누적 계수는 1.0 — 고쳐지는 것이 없다)")
    print(f"  수정 일봉을 묶음   {won(aw[1][1])}  {won(aw[1][2])}  {won(aw[1][3])}  {won(aw[1][4])}   {aw[1][4] / aw[0][4] - 1:+.1%}")

    print("④ 삼성전자 — 배당락일 2025-12-29 (1주당 566원)")
    prev = None
    for day, close in SAMSUNG:
        if prev:
            pr = close / prev - 1
            tr = (close + DIVIDEND.get(day, 0)) / prev - 1
            mark = "  ← 배당락" if day in DIVIDEND else ""
            print(f"  {day}  종가 {close:,}  가격 수익률 {pr:+.2%}  총수익 {tr:+.2%}{mark}")
        prev = close


def live() -> None:
    """같은 날의 「수정 가격」 이 출처마다 다른지 — 야후(yfinance)와 견준다. 네트워크 · yfinance 필요."""
    import yfinance as yf
    df = yf.download("035720.KS", start="2021-04-08", end="2021-04-16", interval="1d", progress=False,
                     auto_adjust=False, multi_level_index=False)
    fs = factors(KAKAO)
    cum = cumulative(fs)
    print("⑤ 카카오 2021-04-09 종가 — 출처마다 다른 「수정 가격」")
    row = df.loc["2021-04-09"]
    print(f"  원 가격(거래소 원자료)              {558000:>11,.1f}")
    print(f"  기준가 계수로 고친 값 × {cum[_d('20210409')]:.7f}    {558000 * cum[_d('20210409')]:>11,.1f}")
    print(f"  야후 Close (분할 비율 1/5 로 고침)   {row['Close']:>11,.1f}")
    print(f"  야후 Adj Close (배당까지 고침)       {row['Adj Close']:>11,.1f}")
    print(f"  야후 거래량 {int(row['Volume']):,} = 원자료 788,839 × {row['Volume'] / 788839:.4f}")


if __name__ == "__main__":
    import sys
    main()
    if "--live" in sys.argv:
        live()
