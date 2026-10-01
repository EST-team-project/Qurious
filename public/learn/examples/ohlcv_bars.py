"""봉과 OHLCV — 일봉을 주봉으로 묶고, 봉이 지켜야 할 값 규칙을 검사하는 예제.

실행    python ohlcv_bars.py          (표준 라이브러리만 · pandas 가 있으면 비교 한 단락을 더 찍는다)
자료    카카오(035720) 2021-04-05 ~ 04-23 · 삼성전자(005930) 2025-09-25 ~ 10-17 일봉
        출처 금융위원회 「주식시세정보」(공공데이터포털) — 설명에 필요한 몇 줄만 교육용으로 인용했다(재배포용 자료가 아니다).
        정규장 가격이 없던 날(거래정지 등)은 원자료가 시가 · 고가 · 저가를 0 으로, 종가를 직전 종가로 준다.

이 파일의 함수 넷:
    problems(bar)          봉 하나가 어긴 값 규칙의 이름들
    flatten(bars)          시가가 0 인 날을 「평평한 봉」 으로 바꾼다(지우지 않는다 · 거래량은 그대로)
    weekly(bars)           월~금 한 주를 봉 하나로 — 가격이 있던 날만으로 시가 · 고가 · 저가를 정한다
    weekly_naive(bars)     흔한 실수: 원자료의 0 까지 그대로 묶는다
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date


@dataclass(frozen=True)
class Bar:
    day: date          # 봉이 속한 거래일 (주봉이면 그 주의 마지막 거래일)
    open: int
    high: int
    low: int
    close: int
    volume: int        # 주(株)


def _rows(text: str) -> list[Bar]:
    out = []
    for line in text.strip().splitlines():
        d, o, h, l, c, v = line.split()
        out.append(Bar(date(int(d[:4]), int(d[4:6]), int(d[6:])), int(o), int(h), int(l), int(c), int(v)))
    return out


# 기준일 · 시가 · 고가 · 저가 · 종가 · 거래량 (원자료 그대로)
KAKAO = _rows("""
20210405 503000 505000 500000 502000   310400
20210406 506000 545000 505000 544000  1724958
20210407 544000 544000 526000 542000   820896
20210408 539000 561000 534000 548000   912514
20210409 554000 561000 551000 558000   788839
20210412      0      0      0 558000        0
20210413      0      0      0 558000        0
20210414      0      0      0 558000        0
20210415 120500 132500 118000 120500 17115015
20210416 115500 120500 115500 119000 13709555
20210419 120000 122000 117500 119000  5441693
20210420 119000 121000 118000 119500  2952174
20210421 119500 119500 117000 118000  4461636
20210422 118000 119500 117500 117500  2279180
20210423 116500 118500 114500 117500  2473720
""")

SAMSUNG = _rows("""
20250925 84400 86200 84100 86100 19665151
20250926 85000 85300 82400 83300 24071193
20250929 83300 85000 83200 84200 13069094
20250930 84600 84900 83400 83900 16319061
20251001 84900 86200 84700 86000 22039361
20251002 89300 90300 88700 89000 49883028
20251010 94000 94500 92700 94400 35269748
20251013 91300 93400 90700 93300 23883308
20251014 95300 96000 90200 91600 35545235
20251015 92300 95300 92100 95000 21050111
20251016 95300 97700 95000 97700 28141060
20251017 97200 99100 96700 97900 22730809
""")


def problems(bar: Bar) -> list[str]:
    """값 규칙: ① 가격 > 0  ② 저가 ≤ 시가 · 종가 ≤ 고가  ③ 거래량 ≥ 0."""
    found = []
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        found.append("가격이 0 이하")
    elif not (bar.low <= min(bar.open, bar.close) and max(bar.open, bar.close) <= bar.high):
        found.append("저가 ≤ 시가·종가 ≤ 고가 를 어김")
    if bar.volume < 0:
        found.append("거래량이 음수")
    return found


def flatten(bars: list[Bar]) -> list[Bar]:
    """정규장 가격이 없던 날(시가 0)을 시가 = 고가 = 저가 = 종가 인 평평한 봉으로 바꾼다. 거래량은 그대로 둔다."""
    return [replace(b, open=b.close, high=b.close, low=b.close) if b.open == 0 else b for b in bars]


def _week(d: date) -> tuple[int, int]:
    y, w, _ = d.isocalendar()           # 월요일에 시작하는 ISO 주
    return y, w


def weekly(bars: list[Bar]) -> list[Bar]:
    """주봉: 시가 = 그 주에 가격이 있던 첫날의 시가 · 고가 · 저가 = 가격이 있던 날의 최고 · 최저
    (마지막 날 종가가 그 밖이면 그 종가까지) · 종가 = 마지막 거래일 종가 · 거래량 = 합 · 날짜 = 그 주의 마지막 거래일.
    한 주 내내 가격이 없으면(정지) 마지막 종가로 평평한 봉."""
    groups: dict[tuple[int, int], list[Bar]] = {}
    for b in bars:
        groups.setdefault(_week(b.day), []).append(b)
    out = []
    for days in groups.values():
        priced = [b for b in days if b.open > 0] or flatten(days[-1:])
        close = days[-1].close                 # 마지막 날에 거래가 없으면 기준가 — 범위를 거기까지 넓힌다
        out.append(Bar(days[-1].day, priced[0].open, max(max(b.high for b in priced), close),
                       min(min(b.low for b in priced), close), close, sum(b.volume for b in days)))
    return out


def weekly_naive(bars: list[Bar]) -> list[Bar]:
    """흔한 실수 — 원자료를 그대로(0 포함) 묶는다."""
    groups: dict[tuple[int, int], list[Bar]] = {}
    for b in bars:
        groups.setdefault(_week(b.day), []).append(b)
    return [Bar(d[-1].day, d[0].open, max(b.high for b in d), min(b.low for b in d), d[-1].close,
                sum(b.volume for b in d)) for d in groups.values()]


def show(title: str, bars: list[Bar]) -> None:
    print(title)
    for b in bars:
        bad = problems(b)
        print(f"  {b.day}  시가 {b.open:>7,}  고가 {b.high:>7,}  저가 {b.low:>7,}  종가 {b.close:>7,}  "
              f"거래량 {b.volume:>11,}  {'✗ ' + ', '.join(bad) if bad else '✓'}")


def main() -> None:
    print("① 원자료 일봉의 값 규칙 — 카카오")
    bad = [(b.day, problems(b)) for b in KAKAO if problems(b)]
    print(f"  {len(KAKAO)}개 중 {len(bad)}개가 규칙을 어김: " + ", ".join(f"{d}" for d, _ in bad))
    show("② 원자료를 그대로 묶은 주봉 (흔한 실수)", weekly_naive(KAKAO))
    show("③ 가격이 있던 날로만 시가 · 고가 · 저가를 정한 주봉", weekly(KAKAO))
    show("④ 휴장이 낀 주 — 삼성전자 2025년 추석 전후", weekly(SAMSUNG))
    try:
        import pandas as pd
    except ImportError:
        return
    df = pd.DataFrame([b.__dict__ for b in SAMSUNG]).set_index("day")
    df.index = pd.to_datetime(df.index)
    wk = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    print("⑤ pandas resample('W-FRI') 로 묶은 같은 자료 — 줄 이름(날짜)을 보세요")
    for d, r in wk.iterrows():
        print(f"  {d.date()}  시가 {int(r.open):>7,}  종가 {int(r.close):>7,}  거래량 {int(r.volume):>11,}")


if __name__ == "__main__":
    main()
