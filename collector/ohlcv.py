"""OHLCV 공통 규격 ``ohlcv-v1`` — 어디서 모은 봉이든 같은 모양 · 같은 규칙으로.

이 파일이 답하는 질문: **"봉 한 줄은 어떤 칸을 갖고, 어떤 값이면 믿을 수 있나."**

왜 규격이 따로 있나
-------------------
일봉(주식 · ETF · 지수) · 주봉 · 분봉이 서로 다른 출처(공공데이터포털 · 야후 · 팀원 파일)에서
온다. 칸 이름 · 단위 · 시간대 · 수정 방식이 출처마다 다르다(2026-10-01 실측 — 카카오
2021-04-09 종가가 원자료 558,000 · 기준가 계수 112,000 · 야후 ``Close`` 111,600 ·
``Adj Close`` 110,981.9). 받는 쪽이 출처마다 따로 읽으면 같은 실수를 사람 수만큼 한다.
그래서 내보내는 것 · 받아들이는 것 모두 이 규격 하나로 맞추고, 검사도 이 파일 하나가 한다.

설계 근거: ``docs/설계/지난판/목표기능1-데이터지식-설계_v0.1.md`` 5.1.1 · 부록 C(2026-10-01 추가 칸).

v1 에 더한 칸 (설계서 v0.1 뒤 · 2026-10-01)
-------------------------------------------
``price_basis``  수정 방식. ``adjusted`` 참 · 거짓만으로는 「기준가 계수로 고쳤나 · 분할 비율로
                 고쳤나 · 배당까지 고쳤나」 를 가릴 수 없다 — 셋이 실제로 다른 값을 낸다.
``session``      분봉의 장 구간. 야후 분봉은 09:00~15:00 만 주고(15:00~15:30 없음), 다른 출처는
                 시간외를 줄 수 있다. 지우지 않고 표시해 고르게 둔다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

CONTRACT = "ohlcv-v1"
KST = timezone(timedelta(hours=9))

#: 칸 순서 = 내보내기 · 검사 보고서의 순서.
COLUMNS: Sequence[str] = (
    "symbol", "market", "timeframe", "trade_date", "bar_start",
    "open", "high", "low", "close", "volume", "value",
    "adjusted", "price_basis", "adj_factor", "session",
    "source", "fetched_at", "contract",
)
REQUIRED: Sequence[str] = (
    "symbol", "market", "timeframe", "trade_date",
    "open", "high", "low", "close", "volume",
    "adjusted", "price_basis", "source", "contract",
)
#: 기본 키. 수정 방식이 다르면 같은 날 · 같은 종목이라도 다른 계열이다.
KEY: Sequence[str] = ("symbol", "timeframe", "price_basis", "trade_date", "bar_start")

TIMEFRAMES = ("1d", "1w", "60m", "5m", "1m")
INTRADAY = ("60m", "5m", "1m")
MARKETS = ("KOSPI", "KOSDAQ", "KONEX", "ETF", "ETN", "INDEX")

#: 수정 방식 — 같은 「수정 가격」 도 출처마다 다르다(개념 학습 1.2 장).
#:   raw        거래소가 그날 낸 원 가격
#:   adj_base   기준가 계수((종가 − 전일대비) ÷ 직전 종가)로 고친 값 — 이 수집기의 수정주가
#:   adj_split  분할 비율로만 고친 값(배당 그대로) — 야후 ``Close``
#:   adj_total  분할 · 배당까지 고친 값 — 야후 ``Adj Close`` · ``auto_adjust=True``
PRICE_BASES = ("raw", "adj_base", "adj_split", "adj_total")

#: 장 구간(KST). 시가는 08:30~09:00 주문을 모아 09:00 에, 종가는 15:20~15:30 주문을 모아
#: 15:30 에 한 가격으로 체결한다(유가증권시장 업무규정 · 법제처 생활법령 2026-09-15 기준 글).
REGULAR_OPEN, CLOSE_AUCTION, REGULAR_CLOSE = time(9, 0), time(15, 20), time(15, 30)
SESSIONS = ("regular", "close_auction", "pre_open", "outside")


# ==================================================
# 1. 시간
# ==================================================
def to_kst(ts) -> datetime:
    """UTC(또는 시간대가 붙은) 시각 → KST.

    ⚠️ 시간대 표시가 없는 시각(naive)은 **받지 않는다.** 어느 나라 시각인지 모르는 값에
       KST 를 붙이면 UTC 였던 00:00 이 9시간 이른 봉이 된다(1.3 장 「흔한 실수」).
    """
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if getattr(ts, "tzinfo", None) is None:
        raise ValueError(f"시간대 표시가 없는 시각이다: {ts!r} — UTC 인지 KST 인지 먼저 밝힌다")
    return ts.astimezone(KST)


def session_of(kst: datetime) -> str:
    """봉 시작 시각이 속한 장 구간."""
    t = kst.timetz().replace(tzinfo=None)
    if CLOSE_AUCTION <= t < REGULAR_CLOSE:
        return "close_auction"
    if REGULAR_OPEN <= t < CLOSE_AUCTION:
        return "regular"
    if time(8, 30) <= t < REGULAR_OPEN:
        return "pre_open"
    return "outside"


def iso_week(d: date) -> tuple:
    y, w, _ = d.isocalendar()           # 월요일에 시작하는 ISO 주
    return y, w


# ==================================================
# 2. 값 규칙 검사
# ==================================================
#: 규칙 이름 → 사람이 읽는 설명. 보고서 · 시험이 같은 이름을 쓴다.
RULES: Dict[str, str] = {
    "missing_column": "필수 칸이 없다",
    "bad_timeframe": "주기가 1d · 1w · 60m · 5m · 1m 이 아니다",
    "bad_market": "시장이 KOSPI · KOSDAQ · KONEX · ETF · ETN · INDEX 가 아니다",
    "bad_basis": "수정 방식이 raw · adj_base · adj_split · adj_total 이 아니다",
    "price_nonpositive": "가격이 0 이하이거나 비었다",
    "ohlc_order": "저가 ≤ 시가 · 종가 ≤ 고가 를 어겼다",
    "volume_negative": "거래량이 음수다",
    "duplicate_key": "같은 종목 · 주기 · 수정 방식 · 날짜(· 봉 시각)의 줄이 둘 이상이다",
    "not_trading_day": "날짜가 거래일 달력에 없다",
    "bar_start_missing": "분봉인데 봉 시각이 없다",
    "bar_start_unexpected": "일봉 · 주봉인데 봉 시각이 있다",
    "bar_start_naive": "봉 시각에 시간대 표시가 없다",
    "bar_date_mismatch": "봉 시각(KST)의 날짜가 거래일과 다르다",
}


def check(df, calendar: Optional[Iterable] = None, sample: int = 5) -> Dict:
    """``ohlcv-v1`` 모양의 표(pandas DataFrame)를 검사한다.

    돌려주는 것::

        {"rows": n, "ok": bool,
         "problems": {규칙: 개수}, "examples": {규칙: [줄 몇 개]},
         "sessions": {장 구간: 개수}}                 (분봉이 있을 때)

    ``calendar`` 를 주면(거래일 날짜들) 일봉 · 주봉의 날짜가 그 안에 있는지 본다.
    거래정지일의 평평한 봉(시가 = 고가 = 저가 = 종가 · 거래량 0)은 규칙 위반이 아니다.
    """
    import pandas as pd

    out: Dict = {"rows": int(len(df)), "problems": {}, "examples": {}}

    def hit(rule: str, mask) -> None:
        n = int(mask.sum())
        if n:
            out["problems"][rule] = n
            out["examples"][rule] = df.loc[mask].head(sample).astype(str).to_dict("records")

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        out["problems"]["missing_column"] = len(missing)
        out["examples"]["missing_column"] = [{"column": c} for c in missing]
        out["ok"] = False
        return out

    hit("bad_timeframe", ~df["timeframe"].isin(TIMEFRAMES))
    hit("bad_market", ~df["market"].isin(MARKETS))
    hit("bad_basis", ~df["price_basis"].isin(PRICE_BASES))

    px = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    bad_px = px.isna().any(axis=1) | (px <= 0).any(axis=1)
    hit("price_nonpositive", bad_px)
    order_ok = (px["low"] <= px[["open", "close"]].min(axis=1)) & (px[["open", "close"]].max(axis=1) <= px["high"])
    hit("ohlc_order", ~bad_px & ~order_ok)
    hit("volume_negative", pd.to_numeric(df["volume"], errors="coerce") < 0)

    key = [k for k in KEY if k in df.columns]
    hit("duplicate_key", df.duplicated(subset=key, keep=False))

    intraday = df["timeframe"].isin(INTRADAY)
    has_bar = df["bar_start"].notna() if "bar_start" in df.columns else pd.Series(False, index=df.index)
    hit("bar_start_missing", intraday & ~has_bar)
    hit("bar_start_unexpected", ~intraday & has_bar)

    if calendar is not None:
        days = {str(d) for d in calendar}
        hit("not_trading_day", ~intraday & ~df["trade_date"].astype(str).isin(days))

    if (intraday & has_bar).any():
        sub = df.loc[intraday & has_bar]
        naive, mism, sessions = [], [], {}
        for idx, bs, td in zip(sub.index, sub["bar_start"], sub["trade_date"]):
            try:
                k = to_kst(bs)
            except ValueError:
                naive.append(idx)
                continue
            if k.date().isoformat() != str(td):
                mism.append(idx)
            s = session_of(k)
            sessions[s] = sessions.get(s, 0) + 1
        hit("bar_start_naive", df.index.isin(naive))
        hit("bar_date_mismatch", df.index.isin(mism))
        out["sessions"] = sessions

    out["ok"] = not out["problems"]
    return out


# ==================================================
# 3. 주봉
# ==================================================
def weekly(daily, as_of: Optional[str] = None):
    """일봉(``ohlcv-v1`` · timeframe=1d) → 주봉(timeframe=1w).

    규칙(개념 학습 1.1 장 표 2):
      시가 = 그 주에 거래가 있던(거래량 > 0) 첫날의 시가 · 고가 · 저가 = 거래가 있던 날의 최고 · 최저
      (마지막 날 종가가 그 밖이면 그 종가까지 넓힌다) · 종가 = 그 주 마지막 날의 종가 ·
      거래량 · 거래대금 = 합 · 날짜 = 그 주의 마지막 거래일. 한 주 내내 거래가 없으면 마지막 날의 평평한 봉.

    ⚠️ 수정 주봉은 반드시 **수정 일봉을 넣어** 만든다. 원 주봉에 계수를 곱하면 주 중간의
       분할 · 권리락을 고칠 수 없다(가온전선 2026-06-30 권리락 주: 원 주봉 −15.7% ↔ 수정 +51.8%).
    ⚠️ 거래정지일의 평평한 봉 값(직전 종가)은 그날 체결된 가격이 아니어서 고가 · 저가에 넣지
       않는다 — 넣으면 그 주에 한 번도 거래되지 않은 값이 범위가 된다.

    ``as_of`` 가 그 주 안이면(진행 중인 주) 돌려주는 표의 ``partial`` 칸이 참이다.
    """
    import numpy as np
    import pandas as pd

    if daily.empty:
        return daily.assign(partial=pd.Series(dtype=bool))
    d = daily.copy()
    d["_day"] = pd.to_datetime(d["trade_date"])
    iso = d["_day"].dt.isocalendar()
    d["_wk"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    d = d.sort_values(["symbol", "price_basis", "_day"])
    d["_traded"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0) > 0

    group = ["symbol", "price_basis", "_wk"]
    last = d.groupby(group, sort=False).tail(1).set_index(group)
    traded = d[d["_traded"]]
    first_open = traded.groupby(group, sort=False)["open"].first()
    hi = traded.groupby(group, sort=False)["high"].max()
    lo = traded.groupby(group, sort=False)["low"].min()
    vol = d.groupby(group, sort=False)["volume"].sum()

    w = last.copy()
    w["open"] = first_open.reindex(w.index).fillna(w["close"])
    # 고가 · 저가는 거래가 있던 날의 범위에 **마지막 날 종가까지** 넣는다. 마지막 날에 거래가 없으면 그날
    # 종가는 거래소가 정한 기준가(ETF 는 NAV 를 따라 움직인다)라 범위 밖일 수 있다 — 2020-01-02 ~ 2026-09-30
    # 내보내기에서 ETF 주봉 1,683개가 그래서 「저가 ≤ 종가 ≤ 고가」 를 어겼다(전부 마지막 날 거래량 0).
    close = w["close"].to_numpy(dtype=float)
    w["high"] = np.maximum(hi.reindex(w.index).fillna(w["close"]).to_numpy(dtype=float), close)
    w["low"] = np.minimum(lo.reindex(w.index).fillna(w["close"]).to_numpy(dtype=float), close)
    w["volume"] = vol.reindex(w.index)
    if "value" in d.columns:
        w["value"] = d.groupby(group, sort=False)["value"].sum(min_count=1).reindex(w.index)
    w["timeframe"] = "1w"
    w = w.reset_index()
    w["partial"] = False
    if as_of:
        a = pd.Timestamp(as_of)
        a_wk = int(a.isocalendar()[0]) * 100 + int(a.isocalendar()[1])
        w["partial"] = (w["_wk"] == a_wk) & (a.weekday() < 4)   # 금요일 전이면 아직 진행 중일 수 있다
    cols = [c for c in COLUMNS if c in w.columns] + ["partial"]
    return w[cols].reset_index(drop=True)


# ==================================================
# 4. 기본값 채우기
# ==================================================
def finalize(df, *, source: str, fetched_at: Optional[str] = None):
    """빠진 선택 칸을 채우고 칸 순서를 맞춘다. 원본 표는 바꾸지 않는다."""
    d = df.copy()
    for c in COLUMNS:
        if c not in d.columns:
            d[c] = None
    d["source"] = d["source"].fillna(source)
    if fetched_at:
        d["fetched_at"] = d["fetched_at"].fillna(fetched_at)
    d["contract"] = CONTRACT
    return d[list(COLUMNS)]


def flat_if_no_price(rows: List[Dict]) -> List[Dict]:
    """정규장 가격이 없던 날(시가 0 · 비어 있음)을 평평한 봉으로. 거래량은 그대로 둔다.

    공공데이터포털은 거래정지일에 시가 · 고가 · 저가를 0, 종가를 직전 종가로 준다.
    2020-01-02 ~ 2026-09-29 원자료 4,477,927행 중 203,281행(4.5%)이 이 모양이다.
    """
    out = []
    for r in rows:
        if not r.get("open"):
            c = r["close"]
            r = {**r, "open": c, "high": c, "low": c}
        out.append(r)
    return out
