"""공공데이터포털 — ETF 시세(증권상품시세정보) · 지수 시세(지수시세정보).

주식 시세(`collector/sources/portal.py`)와 같은 방식으로 받는다 — 하루치 전종목을 한 번에,
원문 · 정규화 · 수집 상태를 **한 트랜잭션에** 쓴다. 다른 점만 여기 적는다.

- API 는 따로 활용 신청한다. 승인되면 같은 서비스키로 부른다(2026-10-01 두 API 모두 응답 확인).
- 하루 한도는 **API 마다 따로** 10,000 이다(응답 헤더 ``X-RateLimit-Limit`` — 주식 · ETF ·
  지수가 각각 9999 남음으로 시작). 그래서 유량 기록기도 API 마다 둔다.
- 수집 상태(``ingest_day``)의 source 는 ``portal_etf`` · ``portal_index`` 다. 주식의 ``portal`` 과
  섞으면 「주식은 받았는데 ETF 는 안 받은 날」 을 가릴 수 없다.
- 원문 target 은 ``etf/YYYYMMDD`` · ``index/YYYYMMDD`` (출처 이름은 ``portal`` 그대로 —
  ``raw_store.ALLOWED_SOURCES`` 를 넓히지 않는다).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import requests

from collector import config, raw_store
from collector.ratelimit import RateLimiter
from collector.sources.portal import DayResult, PortalError, _num, is_halted, parse

ETF_URL = "https://apis.data.go.kr/1160100/service/GetSecuritiesProductInfoService/getETFPriceInfo"
INDEX_URL = "https://apis.data.go.kr/1160100/service/GetMarketIndexInfoService/getStockMarketIndex"

#: 하루치가 한 번에 들어오는 크기. 실측 ETF 1,171 · 지수 171(2026-09-29) — 여유를 둔다.
#: 넘으면 조용히 자르지 않고 예외로 막는다(주식 시세와 같은 원칙).
ROWS = {"etf": 3000, "index": 1000}


@dataclass(frozen=True)
class Kind:
    name: str              # etf | index
    url: str
    source: str            # ingest_day.source
    upsert: Callable[[sqlite3.Connection, List[Dict], str], int]


def _upsert_etf(conn: sqlite3.Connection, items: List[Dict], sha: str) -> int:
    rows = [(
        it.get("basDt", ""), it.get("srtnCd", ""), it.get("isinCd", ""), it.get("itmsNm", ""),
        _num(it.get("clpr")), _num(it.get("vs")), _num(it.get("fltRt"), float), _num(it.get("nav"), float),
        _num(it.get("mkp")), _num(it.get("hipr")), _num(it.get("lopr")),
        _num(it.get("trqu")), _num(it.get("trPrc")), _num(it.get("mrktTotAmt")), _num(it.get("stLstgCnt")),
        it.get("bssIdxIdxNm", "") or "", _num(it.get("bssIdxClpr"), float), _num(it.get("nPptTotAmt")),
        1 if is_halted(it) else 0, sha,
    ) for it in items]
    conn.executemany(
        "INSERT OR REPLACE INTO etf_daily (bas_dt,srtn_cd,isin_cd,itms_nm,clpr,vs,flt_rt,nav,mkp,hipr,lopr,"
        " trqu,tr_prc,mrkt_tot_amt,st_lstg_cnt,bss_idx_nm,bss_idx_clpr,npt_tot_amt,halted,raw_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _upsert_index(conn: sqlite3.Connection, items: List[Dict], sha: str) -> int:
    rows = [(
        it.get("basDt", ""), it.get("idxCsf", "") or "", it.get("idxNm", "") or "", _num(it.get("epyItmsCnt")),
        _num(it.get("clpr"), float), _num(it.get("vs"), float), _num(it.get("fltRt"), float),
        _num(it.get("mkp"), float), _num(it.get("hipr"), float), _num(it.get("lopr"), float),
        _num(it.get("trqu")), _num(it.get("trPrc")), _num(it.get("lstgMrktTotAmt")),
        it.get("basPntm", "") or "", _num(it.get("basIdx"), float), sha,
    ) for it in items]
    conn.executemany(
        "INSERT OR REPLACE INTO index_daily (bas_dt,idx_csf,idx_nm,epy_itms_cnt,clpr,vs,flt_rt,mkp,hipr,lopr,"
        " trqu,tr_prc,lstg_mrkt_tot_amt,bas_pntm,bas_idx,raw_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


KINDS: Dict[str, Kind] = {
    "etf": Kind("etf", ETF_URL, "portal_etf", _upsert_etf),
    "index": Kind("index", INDEX_URL, "portal_index", _upsert_index),
}


def _mark(conn: sqlite3.Connection, source: str, bas_dt: str, status: str, rows: int, message: str) -> None:
    conn.execute(
        "INSERT INTO ingest_day (source,bas_dt,status,rows,attempts,updated_at,message) "
        "VALUES (?,?,?,?,1,?,?) "
        "ON CONFLICT(source,bas_dt) DO UPDATE SET status=excluded.status, rows=excluded.rows, "
        "  attempts=ingest_day.attempts+1, updated_at=excluded.updated_at, message=excluded.message",
        (source, bas_dt, status, rows, raw_store.now_kst_iso(), message))


def fetch_day(conn: sqlite3.Connection, limiter: RateLimiter, kind: str, bas_dt: str, *,
              session: Optional[requests.Session] = None) -> DayResult:
    """기준일 하루치를 받아 원문 · 정규화 · 상태를 한 트랜잭션에 쓴다. 실패도 상태로 남긴다."""
    k = KINDS[kind]
    limiter.check_budget()
    limiter.wait()
    params = {"serviceKey": config.portal_key(), "numOfRows": ROWS[kind], "pageNo": 1,
              "resultType": "json", "basDt": bas_dt}
    res: DayResult
    try:
        r = (session or requests).get(k.url, params=params, timeout=90)
    except requests.RequestException as exc:
        res = DayResult(bas_dt, "error", 0, message=f"네트워크 실패: {type(exc).__name__}")
    else:
        limiter.observe(r.headers)
        if r.status_code != 200:
            res = DayResult(bas_dt, "error", 0, message=f"HTTP {r.status_code}")
        else:
            try:
                total, items = parse(r.content)
            except (PortalError, ValueError, UnicodeDecodeError) as exc:
                res = DayResult(bas_dt, "error", 0, message=str(exc).split("\n")[0])
            else:
                if total > ROWS[kind]:
                    raise PortalError(f"{kind} 하루치가 한 번에 안 들어온다: totalCount={total:,} > {ROWS[kind]:,} "
                                      f"({bas_dt}) — ROWS 를 올리거나 페이지를 돈다")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    sha = raw_store.save(conn, "portal", f"{kind}/{bas_dt}", r.content,
                                         http_status=r.status_code, note=f"rows={len(items)}")
                    n = k.upsert(conn, items, sha) if items else 0
                    status = "done" if n else "empty"
                    _mark(conn, k.source, bas_dt, status, n, "")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return DayResult(bas_dt, status, n, sha)
    conn.execute("BEGIN IMMEDIATE")
    try:
        _mark(conn, k.source, bas_dt, "error", 0, res.message[:400])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return res


def trading_days(conn: sqlite3.Connection, start: str, end: str) -> List[str]:
    """주식 시세가 있는 날 = 거래일. ETF · 지수는 주식과 같은 날 열린다고 보고 이 날들만 부른다.

    휴장일을 부르지 않아 호출이 약 3% 준다. 주식 시세를 아직 못 받은 최근 날은 빠지므로,
    매일 갱신은 주식 시세 단계 **뒤에** 돈다(daily_update 의 ohlcv 단계).
    """
    rows = conn.execute("SELECT DISTINCT bas_dt FROM price_daily WHERE bas_dt BETWEEN ? AND ? ORDER BY bas_dt",
                        (start, end)).fetchall()
    return [r[0] for r in rows]


def pending(conn: sqlite3.Connection, kind: str, days: List[str]) -> List[str]:
    """아직 done 이 아닌 날만. 끊겼다 다시 돌려도 받은 날을 또 부르지 않는다."""
    done = {r[0] for r in conn.execute(
        "SELECT bas_dt FROM ingest_day WHERE source=? AND status='done'", (KINDS[kind].source,))}
    return [d for d in days if d not in done]
