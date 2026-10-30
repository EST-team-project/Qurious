"""코인 봉 → `ohlcv-v2` 줄 — HF `crypto-ohlcv`(Binance Vision 월 묶음) 한 줄을 규격 줄로 (할 일 ①-13 · 2026-10-30).

이 파일은 **네트워크를 쓰지 않는다**(받기 · 올리기는 따로). 이미 올라간 일회 수집본(2026-10-22 · 태그 `crypto-2026-10-22`)의
칸 이름을 읽어 `collector.markets` 의 `ohlcv-v2` 줄로 바꾸고, 값 규칙을 줄마다 검사한다.

원본 칸(카드 「꼴」 절): `symbol` · `open_time_ms` · `open_time_utc` · `open` · `high` · `low` · `close` · `volume`(기준 코인) ·
`close_time_ms` · `quote_volume`(USDT) · `trades` · `taker_buy_base` · `taker_buy_quote` · `source_file`.

규칙
  · 시장 = `BINANCE_SPOT_USDT` · 통화 USDT · 시간대 UTC · 게시판(`market`) = `SPOT`
  · 주기 이름 — 원본 `1d` · `1h` → v1 의 `1d` · `60m` (v1 에 `1h` 가 없다)
  · 하루 경계는 **UTC 00:00**(= KST 09:00)이라 `trade_date` 는 봉 시작의 UTC 날짜
  · 일봉의 `bar_start` 는 비운다(v1 규칙 — 일봉 · 주봉은 봉 시각이 없다). 60분봉은 시간대가 붙은 시각
  · 시각 단위 — 2025-01 부터 원본이 마이크로초인데 올린 자료는 밀리초로 맞췄다. 그래도 마이크로초가 섞여 오면 밀리초로 맞춘다(10^14 넘는 값)
  · 값 = 원본 그대로(거래소 원 가격 · 수정 없음 → `price_basis = raw` · `adjusted = False`) — 환산 · 수정을 하지 않는다
  · `value` = `quote_volume`(USDT 거래대금)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import bars_v2, markets

VENUE = "BINANCE_SPOT_USDT"
BOARD = "SPOT"
SOURCE = "binance_vision"
#: 원본 주기 이름 → v2 주기 이름(바이낸스가 직접 주는 것 — 10분봉 같은 나머지는 `bars_v2.resample` 로 합친다)
TIMEFRAME = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "2h": "120m", "4h": "240m",
             "6h": "360m", "8h": "480m", "12h": "720m", "1d": "1d", "3d": "3d", "1w": "1w", "1mo": "1mo"}

#: 코인 확장 칸 — `ohlcv-v2` 핵심 칸 **뒤**에 붙는다(핵심 칸 · 차례는 안 바뀐다). 개인 프로젝트에서 쓸 체결 수 · 능동 매수량을 버리지 않는다.
EXT_COLUMNS = ("trades", "taker_buy_base", "taker_buy_quote")

#: 값 규칙 이름 → 설명(v1 의 같은 이름과 뜻이 같다 — 줄 하나씩 보는 꼴이라 따로 둔다)
RULES: Dict[str, str] = {
    "bad_timeframe": "주기가 바이낸스 원본 주기(1m ~ 1mo)가 아니다",
    "price_nonpositive": "가격이 0 이하이거나 비었다",
    "ohlc_order": "저가 ≤ 시가 · 종가 ≤ 고가 를 어겼다",
    "volume_negative": "거래량이 음수다",
}


def _to_ms(v) -> int:
    """시각 → 밀리초. 마이크로초(10^14 넘는 값)는 밀리초로 맞춘다(2025-01 이후 원본 · 올린 자료는 이미 맞춤)."""
    n = int(v)
    return n // 1000 if n > 10 ** 14 else n


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None        # NaN 은 비운 값으로


def _int(v) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def to_v2(raw: dict, timeframe: str, fetched_at: Optional[str] = None) -> dict:
    """원본 한 줄 → `ohlcv-v2` 줄. 주기가 모르는 것이면 `ValueError`(조용히 일봉으로 보지 않는다)."""
    if timeframe not in TIMEFRAME:
        raise ValueError(f"모르는 주기: {timeframe!r} — {', '.join(TIMEFRAME)} 중 하나")
    tf = TIMEFRAME[timeframe]
    start = datetime.fromtimestamp(_to_ms(raw["open_time_ms"]) / 1000, tz=timezone.utc)
    row = {
        "symbol": str(raw["symbol"]), "market": BOARD, "timeframe": tf,
        "trade_date": markets.local_trade_date(VENUE, start).isoformat(),
        "bar_start": None if tf in bars_v2.DAILY_PLUS else start.isoformat(),
        "open": _num(raw.get("open")), "high": _num(raw.get("high")), "low": _num(raw.get("low")), "close": _num(raw.get("close")),
        "volume": _num(raw.get("volume")), "value": _num(raw.get("quote_volume")),
        "adjusted": False, "price_basis": "raw", "adj_factor": None, "session": None,
        "source": SOURCE, "fetched_at": fetched_at,
    }
    out = markets.to_v2(row, VENUE)
    out.update({c: (_num(raw.get(c)) if c != "trades" else _int(raw.get(c))) for c in EXT_COLUMNS})
    return out


def check_values(row: dict) -> List[str]:
    """줄 하나의 값 규칙 위반 이름(빈 목록이면 통과) — `markets.check_v2` 가 따로 보는 시장 규칙과 합쳐 쓴다."""
    bad: List[str] = []
    if row.get("timeframe") not in bars_v2.TIMEFRAMES:
        bad.append("bad_timeframe")
    px = [row.get(k) for k in ("open", "high", "low", "close")]
    if any(p is None or p <= 0 for p in px):
        bad.append("price_nonpositive")
    else:
        o, h, l, c = px
        if not (l <= min(o, c) and max(o, c) <= h):
            bad.append("ohlc_order")
    vol = row.get("volume")
    if vol is None or vol < 0:
        bad.append("volume_negative")
    return bad


def convert(raws: List[dict], timeframe: str, fetched_at: Optional[str] = None) -> dict:
    """원본 줄들 → `{"rows": [...v2 줄], "problems": {규칙: 개수}, "bad_rows": n}`.
    위반 줄도 **지우지 않고** 돌려준다(걸러내는 일은 호출하는 쪽이 정한다 — 조용히 버리면 빠진 날이 안 보인다)."""
    rows, problems = [], {}
    bad_rows = 0
    for raw in raws:
        r = to_v2(raw, timeframe, fetched_at)
        hit = check_values(r) + markets.check_v2(r)
        for name in hit:
            problems[name] = problems.get(name, 0) + 1
        bad_rows += bool(hit)
        rows.append(r)
    dup = len(rows) - len({(r["venue"], r["symbol"], r["timeframe"], r["price_basis"], r["trade_date"], r["bar_start"]) for r in rows})
    if dup:
        problems["duplicate_key"] = dup
    return {"rows": rows, "problems": problems, "bad_rows": bad_rows}
