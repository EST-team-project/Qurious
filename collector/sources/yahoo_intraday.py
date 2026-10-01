"""야후 파이낸스 분봉 — 유니버스 고르기 · 받기 · 정규화.

왜 야후인가 (설계서 11절 대안)
------------------------------
한국 종목 분봉을 계좌 · 토큰 없이 과거까지 주는 곳이 야후뿐이다. 증권사(KIS) 분봉은 당일 것만
주고 약관이 백필을 막는 쪽이다. 출처 제한은 「비공개 저장이면 가리지 않는다」 로 풀렸다
(2026-10-01 팀 결정 · 공개 저장소 · 발표에는 원자료를 싣지 않는다).

실측으로 정한 것 (2026-10-01 · 삼성전자 005930.KS · yfinance 0.2.66)
--------------------------------------------------------------------
- 시각은 UTC 로 온다. 봉 시각은 **시작 시각**(하루 첫 봉 09:00 KST)이다.
- **09:00~15:00 만** 준다 — 5분봉 하루 72개(14:55 가 마지막) · 1분봉 360개 · 60분봉 6개.
  15:00~15:30(종가 단일가 포함)이 없어 분봉 거래량 합이 일봉의 68~77% 다.
- ``period`` 로 요청하면 **거래일**로 센다 — 60분 ``730d`` 가 2023-09-27 부터, 5분 ``60d`` 가
  07-06 부터. 날짜(``start``)로 요청하면 **달력 날짜**로 세어 60분 730일 · 5분 60일 · 1분 30일
  밖은 오류다(1분은 한 번에 8일까지). 그래서 첫 적재는 ``period`` 로 받는다.
- 분할은 비율로 고친 값이다(카카오 2021-04-09 ``Close`` 111,600 = 558,000 ÷ 5) → ``adj_split``.

유니버스 (설계서 💬 ① 제안안 — 팀 의견 전)
------------------------------------------
코스피 200 · 코스닥 150 · ETF 거래대금 상위 50. **공식 지수 구성종목은 KRX 정보데이터시스템
로그인이 필요해** 시가총액 순위로 근사한다 — 우선주(코드 끝자리가 0 이 아님) · 스팩 · 그날
거래정지 종목을 빼고 고른다. 근사라는 사실을 ``intraday_universe.reason`` 에 남긴다.
"""

from __future__ import annotations

import sqlite3
import time as _time
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from collector import raw_store
from collector.ohlcv import KST, session_of

#: 한 번에 묶어 부르는 종목 수 · 묶음 사이 쉬는 시간(초). 상대 서버를 배려하는 값이다.
BATCH = 40
PAUSE = 2.0

SPEC = {"KOSPI": 200, "KOSDAQ": 150, "ETF": 50}


def _suffix(market: str) -> str:
    return ".KQ" if market == "KOSDAQ" else ".KS"     # ETF 는 유가증권시장 상장


def build_universe(conn: sqlite3.Connection, as_of: Optional[str] = None,
                   spec: Dict[str, int] = SPEC) -> List[Dict]:
    """기준일의 시가총액 · 거래대금 순위로 분봉 대상을 고른다(근사 — 머리말)."""
    as_of = as_of or conn.execute("SELECT MAX(bas_dt) FROM price_daily").fetchone()[0]
    out: List[Dict] = []
    for market in ("KOSPI", "KOSDAQ"):
        rows = conn.execute(
            "SELECT srtn_cd, itms_nm, mrkt_tot_amt FROM price_daily "
            "WHERE bas_dt=? AND mrkt_ctg=? AND halted=0 AND substr(srtn_cd,6,1)='0' "
            "  AND itms_nm NOT LIKE '%스팩%' AND mrkt_tot_amt IS NOT NULL "
            "ORDER BY mrkt_tot_amt DESC LIMIT ?", (as_of, market, spec[market])).fetchall()
        for i, r in enumerate(rows, 1):
            out.append({"symbol": r[0], "itms_nm": r[1], "market": market, "rank": i,
                        "reason": f"{market} 시가총액 {i}위({as_of} · 지수 구성종목 근사)"})
    etf_day = conn.execute("SELECT MAX(bas_dt) FROM etf_daily WHERE bas_dt<=?", (as_of,)).fetchone()[0]
    if etf_day:
        rows = conn.execute(
            "SELECT srtn_cd, itms_nm, tr_prc FROM etf_daily WHERE bas_dt=? AND halted=0 "
            "ORDER BY tr_prc DESC LIMIT ?", (etf_day, spec["ETF"])).fetchall()
        for i, r in enumerate(rows, 1):
            out.append({"symbol": r[0], "itms_nm": r[1], "market": "ETF", "rank": i,
                        "reason": f"ETF 거래대금 {i}위({etf_day})"})
    return out


#: 사람이 KRX 정보데이터시스템 「지수구성종목」 화면에서 내려받아 두는 곳(.gitignore 의 data/collector/ 안).
#: 자동 로그인으로 긁지 않는다 — 정보데이터시스템 약관 제10조②(자동화 수단에 의한 무단 수집 금지).
KRX_MANUAL_DIR = "krx_manual"


def read_krx_constituents(path) -> List[Dict]:
    """KRX 「지수구성종목」 CSV(사람이 내려받은 것) → [{symbol, itms_nm}].

    인코딩은 EUC-KR(cp949)로 오는 경우가 많아 UTF-8 → cp949 순으로 읽어 본다. 칸 이름은
    「종목코드」 · 「종목명」 을 찾는다(화면 개편으로 순서가 바뀌어도 이름으로 고른다).
    """
    import csv
    import io
    from pathlib import Path

    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: UTF-8 · EUC-KR 둘 다 아니다 — 화면에서 CSV 로 다시 받는다")
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.strip() for h in rows[0]]
    try:
        ci = next(i for i, h in enumerate(head) if h in ("종목코드", "단축코드"))
        ni = next(i for i, h in enumerate(head) if h in ("종목명", "종목약명"))
    except StopIteration:
        raise ValueError(f"{path}: 「종목코드」 · 「종목명」 칸을 못 찾았다 — 받은 칸 {head}")
    out = []
    for r in rows[1:]:
        if len(r) > max(ci, ni) and r[ci].strip():
            out.append({"symbol": r[ci].strip().zfill(6), "itms_nm": r[ni].strip()})
    return out


def universe_from_krx(conn: sqlite3.Connection, kospi200, kosdaq150, as_of: str,
                      etf_n: int = SPEC["ETF"]) -> List[Dict]:
    """공식 구성종목 파일 둘 + ETF 거래대금 상위 n → 유니버스. 근거 칸에 파일 이름을 남긴다."""
    from pathlib import Path
    out: List[Dict] = []
    for market, path, label in (("KOSPI", kospi200, "코스피 200"), ("KOSDAQ", kosdaq150, "코스닥 150")):
        for i, m in enumerate(read_krx_constituents(path), 1):
            out.append({**m, "market": market, "rank": i,
                        "reason": f"{label} 구성종목(KRX 지수구성종목 · {Path(path).name})"})
    out.extend(m for m in build_universe(conn, as_of, {"KOSPI": 0, "KOSDAQ": 0, "ETF": etf_n})
               if m["market"] == "ETF")
    return out


def save_universe(conn: sqlite3.Connection, version: str, members: List[Dict]) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM intraday_universe WHERE version=?", (version,))
        conn.executemany(
            "INSERT INTO intraday_universe (version,symbol,itms_nm,market,reason,rank) VALUES (?,?,?,?,?,?)",
            [(version, m["symbol"], m["itms_nm"], m["market"], m["reason"], m["rank"]) for m in members])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(members)


def latest_universe(conn: sqlite3.Connection) -> List[Dict]:
    row = conn.execute("SELECT MAX(version) FROM intraday_universe").fetchone()
    if not row or not row[0]:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT version, symbol, itms_nm, market, reason, rank FROM intraday_universe WHERE version=? "
        "ORDER BY market, rank", (row[0],))]


def normalize(frame, symbol: str, timeframe: str, fetched_at: str) -> List[Dict]:
    """yfinance 한 종목 표 → price_intraday 줄. 값이 빈 봉(거래 없음 · 받다 끊김)은 버린다."""
    import math
    out: List[Dict] = []
    if frame is None or len(frame) == 0:
        return out
    idx = frame.index
    if getattr(idx, "tz", None) is None:
        raise ValueError(f"{symbol}: 야후가 시간대 없는 시각을 줬다 — UTC 로 가정하지 않고 멈춘다")
    for ts, r in zip(idx.tz_convert(KST), frame.itertuples(index=False)):
        o, h, l, c, v = (getattr(r, "Open"), getattr(r, "High"), getattr(r, "Low"), getattr(r, "Close"),
                         getattr(r, "Volume"))
        if any(x is None or (isinstance(x, float) and math.isnan(x)) for x in (o, h, l, c)):
            continue
        k = ts.to_pydatetime()
        out.append({"symbol": symbol, "timeframe": timeframe, "bar_start": k.isoformat(),
                    "trade_date": k.date().isoformat(), "open": float(o), "high": float(h),
                    "low": float(l), "close": float(c),
                    "volume": int(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else 0,
                    "session": session_of(k), "source": "yahoo", "price_basis": "adj_split",
                    "fetched_at": fetched_at})
    return out


def fetch(members: Iterable[Dict], timeframe: str, *, period: Optional[str] = None,
          start: Optional[str] = None, end: Optional[str] = None, batch: int = BATCH,
          pause: float = PAUSE, log=print) -> Iterable[List[Dict]]:
    """묶음마다 정규화한 줄 목록을 돌려준다(생성기) — 받는 대로 바로 저장할 수 있게."""
    import yfinance as yf

    members = list(members)
    interval = {"60m": "60m", "5m": "5m", "1m": "1m"}[timeframe]
    for i in range(0, len(members), batch):
        chunk = members[i:i + batch]
        tickers = {m["symbol"] + _suffix(m["market"]): m["symbol"] for m in chunk}
        fetched_at = raw_store.now_kst_iso()
        df = yf.download(list(tickers), interval=interval, period=period, start=start, end=end,
                         group_by="ticker", auto_adjust=False, threads=False, progress=False,
                         multi_level_index=True)
        rows: List[Dict] = []
        missing = []
        for tk, sym in tickers.items():
            try:
                sub = df[tk]                 # group_by="ticker" · multi_level_index=True → (종목, 칸)
            except KeyError:
                missing.append(sym)
                continue
            got = normalize(sub.dropna(how="all"), sym, timeframe, fetched_at)
            if not got:
                missing.append(sym)
            rows.extend(got)
        log(f"  {timeframe} 묶음 {i // batch + 1}/{(len(members) + batch - 1) // batch} · "
            f"{len(chunk)}종목 · {len(rows):,}봉" + (f" · 빈 종목 {len(missing)}: {', '.join(missing[:5])}" if missing else ""))
        yield rows
        if i + batch < len(members):
            _time.sleep(pause)


def upsert(conn: sqlite3.Connection, rows: List[Dict]) -> int:
    """같은 봉(종목 · 주기 · 시작 시각)은 새로 받은 값으로 바꾼다 — 장 중에 받은 마지막 봉은
    다음 회차에 완성된 값으로 덮인다."""
    if not rows:
        return 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO price_intraday (symbol,timeframe,bar_start,trade_date,open,high,low,close,"
            " volume,session,source,price_basis,fetched_at) VALUES "
            "(:symbol,:timeframe,:bar_start,:trade_date,:open,:high,:low,:close,:volume,:session,:source,"
            " :price_basis,:fetched_at)", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def now_version(as_of: str) -> str:
    return f"u1-{as_of}"


def kst_now() -> datetime:
    return datetime.now(KST)
