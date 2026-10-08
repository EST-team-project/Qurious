"""다중 주기 신호 — 거래일마다 계산해 T2 에 기록한다 (목표 기능 ② 설계서 5.3 · 6절 · `P01-②-3`).

이 파일이 답하는 질문: **"그날 종가 기준으로, 이 종목은 매수 · 매도 · 관망 가운데 어느 쪽이고 얼마나 확실한가."**

무엇이 바뀌나 (설계서 <표 10>)
  주기   60분 · 일 · 주 모두 `ohlcv-v1` 읽기(`data_ohlcv.read_ohlcv`) — 일 · 60분 = 수집 DB · 주 = 일봉에서 계산한 주봉
         (그 주 마지막 거래일 · 진행 중인 주는 `partial`). 요청마다 야후로 가던 길을 쓰지 않는다
  대상   분봉 유니버스 `u2-20260930`(401종목 — 모두 60분봉이 쌓인다)
  점수   주기마다 −6 ~ +6 — 화면 탐지기의 `patterns.timeframe_score` 그대로(지표는 5.1 의 정의 한 벌)
  결과   `signal` 매수 · 매도 · 관망 · 「강력」 은 `strength`(보통 · 강)로 · `confidence` 0 ~ 1
  기록   거래일마다 T2 `signal_snapshots` 에 종목당 한 줄 — 기본키 (as_of · symbol · definition)

날 D 의 신호는 **D 까지의 봉만** 쓴다 — 일봉은 D 종가까지, 60분봉은 D 의 봉까지, 주봉은 D 까지의 일봉으로 만든다.

신뢰도 = ½ × 방향이 같은 주기의 가중치 비율 + ½ × min(1, |종합 점수| / 4). 지금 화면(`patterns.combine_timeframes`)의
식을 0 ~ 1 로 옮긴 것이다(화면 값 = round(신뢰도 × 100)). 확률이 아니다 — 보정은 기록이 쌓인 뒤 잰다.
"""
from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import collector_db, data_ohlcv
from app.services.patterns import pattern_summary, timeframe_score
from app.services.ta_utils import DEFINITION

#: (주기, 이름, 가중치, 돌아보는 기간) — 가중치 · 기간은 지금 화면(`patterns.TIMEFRAMES`)과 같다
TIMEFRAMES = (
    ("60m", "분봉(60분)", 0.2, timedelta(days=30)),
    ("1d", "일봉", 0.5, timedelta(days=365)),
    ("1w", "주봉", 0.3, timedelta(days=365 * 5)),
)
UNIVERSE = "u2-20260930"
BUY, SELL, HOLD = "매수", "매도", "관망"
STRONG, NORMAL = "강", "보통"
#: |종합 점수| 가 이만큼이면 매수 · 매도, 이만큼이면 「강」 — 지금 화면의 다섯 단계 경계와 같다
SIGNAL_AT, STRONG_AT = 1.0, 2.5


# ── 신호 · 신뢰도 ─────────────────────────────────────────────────────────

def classify(composite: float) -> tuple[str, str | None]:
    """종합 점수 → (신호, 강도). 관망의 강도는 없다(None)."""
    if composite >= SIGNAL_AT:
        return BUY, STRONG if composite >= STRONG_AT else NORMAL
    if composite <= -SIGNAL_AT:
        return SELL, STRONG if composite <= -STRONG_AT else NORMAL
    return HOLD, None


def combine(results: list[dict]) -> dict:
    """주기별 [{weight, score} 또는 {weight, error}] → 신호 · 강도 · 신뢰도(0 ~ 1) · 종합 점수 · 방향 일치도(0 ~ 1)."""
    valid = [r for r in results if "score" in r]
    if not valid:
        return {"signal": HOLD, "strength": None, "confidence": 0.0, "composite": 0.0, "agreement": 0.0}
    wsum = sum(r["weight"] for r in valid) or 1.0
    composite = sum(r["score"] * r["weight"] for r in valid) / wsum
    direction = 1 if composite > 0 else -1 if composite < 0 else 0
    agree = 0.0 if direction == 0 else sum(r["weight"] for r in valid
                                           if (r["score"] > 0) - (r["score"] < 0) == direction) / wsum
    magnitude = min(1.0, abs(composite) / 4.0)
    signal, strength = classify(composite)
    # 반올림하지 않는다 — 화면 값(round(× 100))과 경계에서 어긋나지 않게
    return {"signal": signal, "strength": strength, "confidence": 0.5 * agree + 0.5 * magnitude,
            "composite": composite, "agreement": agree}


# ── 봉 읽기 ───────────────────────────────────────────────────────────────

@dataclass
class Bars:
    """한 종목의 일봉 · 60분봉(`ohlcv-v1` 줄) — 기간 전체를 한 번 읽어 두고 날마다 잘라 쓴다."""
    symbol: str
    daily: list[dict] = field(default_factory=list)
    intraday: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self._d_days = [r["trade_date"] for r in self.daily]
        self._i_days = [r["trade_date"] for r in self.intraday]

    def daily_until(self, as_of: str, since: str) -> list[dict]:
        return self.daily[bisect.bisect_left(self._d_days, since):bisect.bisect_right(self._d_days, as_of)]

    def intraday_until(self, as_of: str, since: str) -> list[dict]:
        return self.intraday[bisect.bisect_left(self._i_days, since):bisect.bisect_right(self._i_days, as_of)]


def load_bars(symbol: str, start: str, end: str, *, path: Path | None = None) -> Bars:
    """[start − 5년, end] 일봉과 [start − 30일, end] 60분봉을 읽는다. 60분봉이 없으면 빈 목록."""
    d0 = (date.fromisoformat(start) - TIMEFRAMES[2][3] - timedelta(days=7)).isoformat()
    daily = data_ohlcv.read_ohlcv(symbol, "1d", start=d0, end=end, limit=data_ohlcv.MAX_LIMIT, path=path)["rows"]
    i0 = (date.fromisoformat(start) - TIMEFRAMES[0][3]).isoformat()
    try:
        intraday = data_ohlcv.read_ohlcv(symbol, "60m", start=i0, end=end, limit=data_ohlcv.MAX_LIMIT, path=path)["rows"]
    except data_ohlcv.OhlcvError:
        intraday = []
    return Bars(symbol, daily, intraday)


def _epoch(row: dict) -> int:
    if row.get("bar_start") and row["timeframe"] in data_ohlcv.INTRADAY:
        return int(datetime.fromisoformat(row["bar_start"]).timestamp())
    d = date.fromisoformat(row["trade_date"])
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _candles(rows: list[dict]) -> list[dict]:
    return [{"time": _epoch(r), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
             "close": float(r["close"]), "volume": int(r["volume"] or 0)} for r in rows]


# ── 하루 신호 ─────────────────────────────────────────────────────────────

def signal_at(bars: Bars, as_of: str) -> dict | None:
    """날 `as_of`(YYYY-MM-DD) 종가 기준 T2 한 줄. 그날 일봉이 없으면(상장 전 · 그날 시세 없음) None."""
    if not bars.daily_until(as_of, as_of):
        return None
    a = date.fromisoformat(as_of)
    rows = []
    for tf, label, weight, back in TIMEFRAMES:
        since = (a - back).isoformat()
        extra: dict = {}
        if tf == "60m":
            src = bars.intraday_until(as_of, since)
        elif tf == "1d":
            src = bars.daily_until(as_of, since)
        else:
            # 주봉은 그 주 월요일부터 일봉을 모아야 첫 주가 온전하다 — 끝은 as_of (뒤 날은 보지 않는다)
            monday = (a - back) - timedelta(days=(a - back).weekday())
            src, partial = data_ohlcv.weekly(bars.daily_until(as_of, monday.isoformat()), as_of)
            src = [r for r in src if r["trade_date"] >= since]
            extra["partial"] = partial
        if not src:
            r = {"error": "시세 없음"}
        else:
            r = timeframe_score(_candles(src))
            extra["last_bar"] = src[-1].get("bar_start") or src[-1]["trade_date"]
        rows.append({"timeframe": tf, "label": label, "weight": weight, **r, **extra})
    combined = combine(rows)
    # 일봉 패턴 요약(설계서 6절 `pattern_bias` · `patterns`) — 화면 패턴 탐지기를 일봉 1년으로
    daily_1y = bars.daily_until(as_of, (a - timedelta(days=365)).isoformat())
    pat = pattern_summary(_candles(daily_1y)) if daily_1y else {"error": "시세 없음"}
    patterns = None if "error" in pat else (
        [{"key": p["key"], "name": p["name"], "direction": p["direction"], "date": p["date"]} for p in pat["patterns"]]
        + [{"key": e["key"], "name": e["name"], "direction": e["direction"], "date": as_of} for e in pat["breakouts"]])
    timeframes = [{k: v for k, v in r.items() if k not in ("ma5", "ma20", "last", "as_of")} for r in rows]
    reasons = [{"timeframe": r["label"], "text": t} for r in rows for t in r.get("reasons", [])]
    return {"as_of": a, "symbol": bars.symbol, "definition": DEFINITION, **combined,
            "timeframes": timeframes, "pattern_bias": None if "error" in pat else pat["pattern_bias"],
            "patterns": patterns, "reasons": reasons}


# ── 대상 · 거래일 ─────────────────────────────────────────────────────────

def _connect(path: Path | None) -> sqlite3.Connection:
    p = path or collector_db.db_path()
    if p is None:
        raise FileNotFoundError("수집 DB 를 찾지 못했다(data/collector/market.sqlite3)")
    return sqlite3.connect(f"{Path(p).resolve().as_uri()}?mode=ro", uri=True)


def universe(*, version: str = UNIVERSE, path: Path | None = None) -> list[str]:
    """분봉 유니버스 종목 코드(순위 차례)."""
    conn = _connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT symbol FROM intraday_universe WHERE version = ? ORDER BY rank, symbol",
                                           (version,))]
    finally:
        conn.close()


def trading_days(start: str, end: str, *, path: Path | None = None) -> list[str]:
    """[start, end] 안에서 시세가 있는 날(주식 일봉 기준) — YYYY-MM-DD."""
    conn = _connect(path)
    try:
        rows = conn.execute("SELECT DISTINCT bas_dt FROM price_daily WHERE bas_dt >= ? AND bas_dt <= ? AND clpr > 0 "
                            "ORDER BY bas_dt", (start.replace("-", ""), end.replace("-", ""))).fetchall()
    finally:
        conn.close()
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for (d,) in rows]


# ── 기록 ──────────────────────────────────────────────────────────────────

async def write_snapshots(session, records: list[dict]) -> int:
    """T2 에 쓴다 — 같은 (as_of · symbol · definition) 은 다시 계산한 값으로 바꾸고, 다른 판의 줄은 건드리지 않는다."""
    if not records:
        return 0
    from sqlalchemy.dialects.postgresql import insert

    from app.models.signal import SignalSnapshot

    now = datetime.now(timezone.utc)
    rows = [{**r, "computed_at": now} for r in records]
    stmt = insert(SignalSnapshot).values(rows)
    keys = ("as_of", "symbol", "definition")
    stmt = stmt.on_conflict_do_update(index_elements=list(keys),
                                      set_={c: stmt.excluded[c] for c in rows[0] if c not in keys})
    await session.execute(stmt)
    await session.commit()
    return len(rows)
