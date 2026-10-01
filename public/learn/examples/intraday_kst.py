"""분봉과 시간대 — UTC 로 온 봉 시각을 한국 시간(KST)으로 바꾸고, 장 시간 안팎을 가르는 예제.

실행    python intraday_kst.py           시간대 계산만 (표준 라이브러리 · 네트워크 없음)
        python intraday_kst.py --live    야후에서 삼성전자(005930.KS) 5분봉을 받아 하루 봉 수 · 거래량을 일봉과 맞춰 본다
                                         (yfinance · pandas 필요 · 결과는 받는 날마다 다르다)

함수
    to_kst(utc_text)        '2026-09-30T00:00:00Z' 같은 UTC 시각 → KST 시각(시간대가 붙은 datetime)
    session(kst)            그 시각이 정규장 · 시가 단일가 · 종가 단일가 · 장 밖 중 어디인가
    trade_day(kst)          봉이 속한 거래일 — KST 날짜
"""
from __future__ import annotations

import sys
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 장 시간 (유가증권시장 · 코스닥 정규시장)
OPEN_AUCTION = (time(8, 30), time(9, 0))      # 시가를 정하는 주문 접수 — 09:00 에 한 가격으로 체결
REGULAR = (time(9, 0), time(15, 30))          # 정규장
CLOSE_AUCTION = (time(15, 20), time(15, 30))  # 종가를 정하는 단일가 — 15:30 에 한 가격으로 체결


def to_kst(utc_text: str) -> datetime:
    """끝의 Z 는 UTC 라는 표시다. fromisoformat 은 'Z' 를 3.11 부터 받는다."""
    return datetime.fromisoformat(utc_text.replace("Z", "+00:00")).astimezone(KST)


def session(kst: datetime) -> str:
    t = kst.timetz().replace(tzinfo=None)
    if CLOSE_AUCTION[0] <= t < CLOSE_AUCTION[1]:
        return "종가 단일가"
    if REGULAR[0] <= t < REGULAR[1]:
        return "정규장"
    if OPEN_AUCTION[0] <= t < OPEN_AUCTION[1]:
        return "시가 단일가(주문만)"
    return "장 밖"


def trade_day(kst: datetime) -> str:
    return kst.date().isoformat()


SAMPLES = [
    "2026-09-30T00:00:00Z",   # 야후가 준 5분봉 첫 봉
    "2026-09-30T05:55:00Z",   # 야후가 준 5분봉 마지막 봉
    "2026-09-30T06:20:00Z",   # 종가 단일가가 시작되는 시각
    "2026-09-30T06:30:00Z",   # 정규장이 끝난 시각
    "2026-09-29T23:40:00Z",   # 장 시작 전 — UTC 로는 전날
    "2026-09-29T15:00:00Z",   # 자정 표시 일봉(KST 09-30 00:00)을 UTC 로 적은 모양
]


def offline() -> None:
    print("① UTC → KST")
    for s in SAMPLES:
        k = to_kst(s)
        print(f"  {s}  →  {k:%Y-%m-%d %H:%M} KST  {session(k):<12}  UTC 날짜 {s[:10]} · KST 거래일 {trade_day(k)}")
    print("② 흔한 실수 — 시간대 표시를 잃은 값(naive)에 시간대를 잘못 붙이기")
    naive = datetime(2026, 9, 30, 0, 0)                          # 원래 UTC 00:00 이었던 값
    print(f"  잘못  naive.replace(tzinfo=KST)                         → {naive.replace(tzinfo=KST):%Y-%m-%d %H:%M} KST  (9시간 이른 봉)")
    print(f"  맞음  naive.replace(tzinfo=timezone.utc).astimezone(KST) → "
          f"{naive.replace(tzinfo=timezone.utc).astimezone(KST):%Y-%m-%d %H:%M} KST")


def live() -> None:
    import pandas as pd
    import yfinance as yf
    m5 = yf.download("005930.KS", interval="5m", period="5d", progress=False, auto_adjust=False, multi_level_index=False)
    d1 = yf.download("005930.KS", interval="1d", period="1mo", progress=False, auto_adjust=False, multi_level_index=False)
    print(f"③ 야후 5분봉 · 받은 시각 {datetime.now(KST):%Y-%m-%d %H:%M} KST · 시간대 {m5.index.tz}")
    k = m5.tz_convert(KST)
    today = datetime.now(KST).date()
    for day, g in k.groupby(k.index.date):
        daily = d1[d1.index.date == day]
        if daily.empty or day >= today:             # 오늘은 장이 끝나지 않았을 수 있어 뺀다
            continue
        vol = int(daily["Volume"].iloc[0])
        print(f"  {day}  봉 {len(g):>3}개  {g.index[0]:%H:%M}~{g.index[-1]:%H:%M}  "
              f"분봉 거래량 합 {int(g['Volume'].sum()):>11,} / 일봉 {vol:>11,} = {g['Volume'].sum() / vol:6.1%}  "
              f"마지막 분봉 종가 {g['Close'].iloc[-1]:>9,.0f} · 일봉 종가 {daily['Close'].iloc[0]:>9,.0f}")
    _ = pd  # pandas 는 yfinance 가 돌려주는 표 때문에 필요하다


if __name__ == "__main__":
    offline()
    if "--live" in sys.argv:
        live()
