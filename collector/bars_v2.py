"""분봉 합성 — 잘게 받은 봉(1분 · 5분 …)을 같은 규칙으로 10분 · 30분 · 60분봉으로 (할 일 ①-13 · 2026-10-30).

사용자 피드백(10-30): 시간봉을 다양하게 모아야 신호 · 대사 · 백테스트가 정교해진다. 주기마다 따로 받으면 용량도 약관 부담도 커지고
주기끼리 값이 어긋날 수 있다 — 그래서 **가장 잘게 받는 원천은 그 주기로 받고, 나머지는 이 함수로 합쳐 만든다.**
원천이 바로 주는 주기(예: 바이낸스 5m · 15m · 30m · 1h)는 받은 것이 정본이고, 합친 값과 대조하는 데 쓴다.

규칙
  · 합치는 값 — 시가 = 첫 봉 · 고가 = 최대 · 저가 = 최소 · 종가 = 끝 봉 · 거래량 · 거래대금 = 합(하나라도 비면 그 칸은 비움)
  · **거래소 현지 시계로 맞춘다** — 시작점(anchor)은 정규장이 있으면 정규장 시작(국내 09:00 · 미국 09:30 ET), 24시간 시장이면 현지 00:00.
    미국 30분봉이 09:30 · 10:00 … 이어야지 09:00 · 09:30 이면 첫 칸이 반쯤 빈다. 서머타임은 현지 시각으로 세므로 바뀌지 않는다.
  · 장 시작 앞 봉(프리마켓)은 시작점 앞 칸으로 가고 「덜 찼다」 판정을 하지 않는다(몇 개여야 하는지 모른다).
  · 칸이 덜 찬 봉(원본 봉이 빠졌다)은 `incomplete` 에 봉 시각을 적는다 — 조용히 채우거나 버리지 않는다.
  · 같은 (시장 · 종목 · 수정 방식)의 같은 주기 봉만 받는다. 목표가 원본의 배수가 아니거나 더 잘으면 `ValueError`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import markets

#: 분봉 주기 → 분. v1 은 1m · 5m · 60m 이고 v2 는 10m · 15m · 30m 을 더한다(바이낸스가 1m · 5m · 15m · 30m · 1h 를 직접 준다)
#: 사용자 결정(10-30 「다양하게 전부」): 바이낸스가 직접 주는 분 · 시간 주기를 모두 담는다 — 이름은 분 단위로 통일(1시간 = `60m` · v1 과 같다).
MINUTES: Dict[str, int] = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "60m": 60,
                           "120m": 120, "240m": 240, "360m": 360, "480m": 480, "720m": 720}
#: 하루 이상 주기 — 봉 시각이 없다(`bar_start` 비움). `3d` · `1mo` 는 합성하지 않고 원천이 주는 것만 받는다
DAILY_PLUS = ("1d", "3d", "1w", "1mo")
TIMEFRAMES = tuple(MINUTES) + DAILY_PLUS
INTRADAY = tuple(MINUTES)


def minutes_of(timeframe: str) -> int:
    try:
        return MINUTES[timeframe]
    except KeyError:
        raise ValueError(f"분봉 주기가 아니다: {timeframe!r} — {', '.join(MINUTES)} 중 하나") from None


def _anchor_and_close(m: markets.Market):
    """현지 시계로 센 정규장 시작 · 끝(분). 24시간 시장은 (0, None)."""
    if m.regular_session is None:
        return 0, None
    (oh, om), (ch, cm) = ((t.hour, t.minute) for t in m.regular_session)
    return oh * 60 + om, ch * 60 + cm


def resample(rows: List[dict], target: str) -> dict:
    """같은 종목의 잘게 받은 봉들 → `target` 주기 봉들. `{"rows": [...], "incomplete": [봉 시각, ...]}`."""
    tmin = minutes_of(target)
    if not rows:
        return {"rows": [], "incomplete": []}
    first = rows[0]
    group = (first["venue"], first["symbol"], first["price_basis"], first["timeframe"])
    smin = minutes_of(first["timeframe"])
    if tmin <= smin or tmin % smin:
        raise ValueError(f"{first['timeframe']} 봉으로 {target} 봉을 만들 수 없다(목표가 원본보다 굵고 배수여야 한다)")
    m = markets.get(first["venue"])
    zone = ZoneInfo(m.tz)
    anchor, close = _anchor_and_close(m)

    buckets: Dict[datetime, List[dict]] = {}
    seen = set()
    for r in sorted(rows, key=lambda r: r["bar_start"]):
        if (r["venue"], r["symbol"], r["price_basis"], r["timeframe"]) != group:
            raise ValueError("시장 · 종목 · 수정 방식 · 주기가 섞여 있다 — 하나씩 넣는다")
        if r["bar_start"] in seen:
            raise ValueError(f"같은 봉 시각이 둘이다: {r['bar_start']}")
        seen.add(r["bar_start"])
        local = datetime.fromisoformat(r["bar_start"]).astimezone(zone)        # 시간대 없는 시각은 여기서 ValueError 가 아니라 astimezone 이 현지로 짐작하므로 아래에서 막는다
        if datetime.fromisoformat(r["bar_start"]).tzinfo is None:
            raise ValueError(f"시간대 표시가 없는 시각이다: {r['bar_start']!r}")
        mins = local.hour * 60 + local.minute - anchor
        start_min = anchor + (mins // tmin) * tmin                              # 음수(장 시작 앞)도 아래로 내림
        day0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets.setdefault(day0 + timedelta(minutes=start_min), []).append(r)    # 현지 시계 덧셈 — 서머타임에 안 흔들린다

    out, incomplete = [], []
    for start, group_rows in sorted(buckets.items()):
        rel = start.hour * 60 + start.minute
        expected: Optional[int] = None
        if rel >= anchor:
            span = tmin if close is None else min(tmin, close - rel)
            expected = max(span // smin, 1)
        vol = [g["volume"] for g in group_rows]
        val = [g["value"] for g in group_rows]
        bar_start = start.isoformat()
        out.append({**group_rows[0],
                    "timeframe": target, "bar_start": bar_start,
                    "trade_date": markets.local_trade_date(first["venue"], start).isoformat(),
                    "open": group_rows[0]["open"], "close": group_rows[-1]["close"],
                    "high": max(g["high"] for g in group_rows), "low": min(g["low"] for g in group_rows),
                    "volume": None if any(v is None for v in vol) else sum(vol),
                    "value": None if any(v is None for v in val) else sum(val),
                    "fetched_at": max((g.get("fetched_at") or "" for g in group_rows), default="") or None,
                    "contract": markets.CONTRACT})
        if expected is not None and len(group_rows) < expected:
            incomplete.append(bar_start)
    return {"rows": out, "incomplete": incomplete}
