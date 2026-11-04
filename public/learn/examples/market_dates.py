"""여러 시장의 「하루」 — 봉 시각을 시장의 거래일로 바꾸고, 미국 마감의 한국 시각 · 통화 자릿수 · 서머타임 경계를 계산하는 예제.

실행    python market_dates.py        (표준 라이브러리만 · 네트워크 없음)
주의    zoneinfo 는 시간대 데이터를 갖고 있지 않다 — 시스템에 IANA 데이터가 없으면(윈도우가 보통 그렇다) `pip install tzdata` 가 있어야 돈다.
자료    합성 — 시장 두세 줄을 딕셔너리로 만든 것이며 실제 수집기(collector/markets.py)를 줄여 옮긴 것이다. 날짜 계산은 규칙에서 나온 값이다.
흐름    ① 시간대가 없는 시각은 거부하고, 있으면 시장의 기준(거래소 현지 날짜 / UTC 00:00)으로 거래일을 센다
        ② 뉴욕 16:00 마감의 한국 시각 — 서머타임 전환 앞뒤로 한 시간 밀린다
        ③ 통화마다 소수 자릿수가 다르다(KRW 0 · USD 2)
        ④ 서머타임이 끝나는 날 새벽에는 같은 시각이 두 번 나온다(fold)
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("Asia/Seoul")
except Exception as exc:                                    # tzdata 가 없을 때 — 막다른 길로 만들지 않고 할 일을 알려 준다
    raise SystemExit(f"시간대 데이터가 없습니다({type(exc).__name__}). 할 일: pip install tzdata") from None

MARKETS = {
    "XKRX": {"tz": "Asia/Seoul", "day_boundary": "exchange_local_date", "currency": "KRW"},
    "XNYS": {"tz": "America/New_York", "day_boundary": "exchange_local_date", "currency": "USD"},
    "BINANCE_SPOT_USDT": {"tz": "UTC", "day_boundary": "utc_00", "currency": "USDT"},
}


def local_trade_date(venue: str, ts: str) -> dt.date:
    m = MARKETS[venue]
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"시간대 표시가 없는 시각이다: {ts!r} — 어느 시간대인지 먼저 밝힌다")
    zone = ZoneInfo("UTC") if m["day_boundary"] == "utc_00" else ZoneInfo(m["tz"])
    return t.astimezone(zone).date()


def ny_close_in_kst(d: dt.date) -> str:
    close = dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=ZoneInfo("America/New_York"))
    return close.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    ts = "2026-11-03T05:30:00+09:00"
    print("① 같은 순간", ts)
    for v in MARKETS:
        print(f"   {v:18} → 거래일 {local_trade_date(v, ts)}")
    try:
        local_trade_date("XKRX", "2026-11-03T05:30:00")
    except ValueError as e:
        print("   시간대 없는 시각 →", e)

    print("② 뉴욕 16:00 마감의 한국 시각")
    for d in [dt.date(2026, 10, 30), dt.date(2026, 11, 2), dt.date(2026, 3, 6), dt.date(2026, 3, 9)]:
        print(f"   뉴욕 {d} 마감 → KST {ny_close_in_kst(d)}")

    print("③ 통화 자릿수(KRW 0 · USD 2)")
    krw = Decimal("70123.5").quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    usd = Decimal("189.4567").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    print(f"   KRW {krw} | USD {usd}")

    print("④ 2026-11-01 01:30 뉴욕은 두 번 나온다")
    ny = ZoneInfo("America/New_York")
    for fold in (0, 1):
        t = dt.datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=fold)
        print(f"   fold={fold} → UTC{t.strftime('%z')} ({t.tzname()})")


if __name__ == "__main__":
    main()
