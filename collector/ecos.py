"""한국은행 경제통계시스템(ECOS) 시장금리 · 주가지수 — 신용 스프레드 · 시장 계절성 재료 (④-2 재무 · 신용 위험 · 2026-10-13 /
주가지수 2026-10-14 · 금융 필수 지식 › 계절성).

    python -m collector.ecos daily [--quiet]                 계열마다 마지막 날 앞 14일부터 오늘까지 — 러너 단계
    python -m collector.ecos backfill [--from 19950101]      지난 값 전부(계열마다 쪽 넘기기 · 이미 있는 줄은 그대로)
    python -m collector.ecos status

무엇을 받나
-----------
통계표 817Y002 「1.3.2.1. 시장금리(일별)」 의 다섯 항목(아래 `SERIES`). 2026-10-13 공식 샘플 키(`sample`)로
StatisticItemList · StatisticSearch 를 불러 항목 코드 · 이름(영어판으로 확인) · 단위(연%) · 첫 날을 실측했다.
값은 거래일만 온다(10-09 한글날 · 주말 줄 없음). 신용 스프레드 = 회사채(3년) − 국고채(3년) — 계산은 앱이 읽을 때 한다
(`app/services/macro_credit.py`). 이 표에는 ECOS 가 준 값만 둔다.

통계표 802Y001 「1.5.1.1. 주식시장(일)」 의 두 항목(아래 `INDEX_SERIES` — 코스피 1995-01-03 ~ · 코스닥 2003-01-02 ~ ·
가격 지수(배당 없음) · 단위 「1980.01.04=100」 · 「1996.07.01=1000」). 2026-10-14 공식 샘플 키로 StatisticItemList 를
불러 아홉 항목 가운데 지수 둘의 코드 · 첫 날 · 줄 수(8,032 · 5,867)를 실측했다. 우리 수집 시세는 2020-01 부터라 달마다 관측이
6 ~ 7개뿐이어서, 시장 계절성(`app/services/seasonality.py`)은 이 긴 지수로 센다(사용자 결정 2026-10-14). 같은 표 · 같은 키 ·
같은 약관(제5조① 상업 이용 · 제7조② 출처 표시)이다.

이용 조건 — 「한국은행 경제통계 Open API 이용약관」(2020-11-05 시행 — 원문 끝 부칙 · 2026-10-13 원문을 받아 조항을 옮김)
  제5조①  통계정보를 상업적으로 이용할 수 있다(상업적 이용을 제한하는 통계는 작성기관 승인 뒤).
  제6조②5 인증키의 양도 · 증여 · 담보 사용 금지 → 키는 사람마다 · `.env` 의 `ECOS_API_KEY` 에만.
  제7조②  「ECOS 에서 제공된 정보임을 표시」 → 화면 · 응답에 `ATTRIBUTION`.
  저장을 막는 조항은 없다(인증키 신청서의 용도 선택지에 「DB 수집」 이 있다).

키를 지키는 법
--------------
ECOS 는 키를 **주소 경로**에 넣는다(`…/StatisticSearch/{키}/json/kr/…`). 요청 라이브러리의 예외 글(「Max retries exceeded
with url: /api/StatisticSearch/<키>/…」)에 주소가 그대로 들어가 로그로 샐 수 있다 → 밖으로 내보내는 글은 모두 `scrub` 를
거치고, 예외는 원래 예외를 잇지 않고(`from None`) 다시 던진다. 원문 이름(`raw_response.target`)에는 키를 넣지 않는다.

ECOS 응답의 함정 (2026-10-13 실측)
---------------------------------
· 오류도 HTTP 200 이다 — 본문 `RESULT.CODE` 로 가른다(INFO-100 키가 틀림 · ERROR-101 날짜 꼴 · ERROR-301 조회 건수).
· **없는 항목 코드도 「해당하는 데이터가 없습니다」(INFO-200)** 로 온다 — 주말 창과 같은 답이다. 그래서 거래일이 들어 있을
  긴 창(`EMPTY_WINDOW_DAYS` 일 이상)이 비어 오면 실패로 센다(말없이 0줄로 끝나지 않게).

종료코드 — 0 끝 · 1 ECOS 오류 · 네트워크 · 빈 창 · 78 키 없음(설정 결함 — 숨기지 않는다 · 러너는 경고로 센다)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter

SOURCE = "ecos"
ATTRIBUTION = "한국은행 경제통계시스템(ECOS)"
URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/{start}/{end}/{stat}/{cycle}/{bgn}/{fin}/{item}"
STAT = "817Y002"
CYCLE = "D"

#: (열쇠, 항목 코드, 이름, ECOS 첫 날) — 2026-10-13 실측(StatisticItemList · 이름은 영어판 「Treasury Bonds (3-year)」 ·
#: 「Corporate Bonds (3-year, AA-)」 · 「Corporate Bonds (3-year, BBB-)」 · 「CD (91-day)」 · 「CP (91-day)」 로 확인).
SERIES: Tuple[Tuple[str, str, str, str], ...] = (
    ("treasury_3y", "010200000", "국고채(3년)", "19981113"),
    ("corp_aa_3y", "010300000", "회사채(3년, AA-)", "19950103"),
    ("corp_bbb_3y", "010320000", "회사채(3년, BBB-)", "20000930"),
    ("cd_91d", "010502000", "CD(91일)", "19950103"),
    ("cp_91d", "010503000", "CP(91일)", "19950103"),
)
#: 통계표 「1.5.1.1. 주식시장(일)」 — 시장 계절성 재료(2026-10-14 실측 · 앱 `seasonality.MARKETS` 가 열쇠 · 코드를 맞춘다 — TC-SE-01).
INDEX_STAT = "802Y001"
INDEX_SERIES: Tuple[Tuple[str, str, str, str], ...] = (
    ("kospi", "0001000", "KOSPI지수", "19950103"),
    ("kosdaq", "0089000", "KOSDAQ지수", "20030102"),
)
#: 받는 묶음 — (통계표, 계열들). 시장금리는 재무 · 신용 위험이, 주가지수는 계절성이 읽는다.
GROUPS: Tuple[Tuple[str, Tuple[Tuple[str, str, str, str], ...]], ...] = ((STAT, SERIES), (INDEX_STAT, INDEX_SERIES))
#: 한 번에 받는 줄 수 — 가장 긴 계열(1995 ~)이 약 8,000줄이라 보통 한 번에 끝난다.
PAGE = 10_000
#: 매일 받기는 마지막 날 앞 이만큼부터 다시 받는다 — ECOS 가 고친 값 · 늦게 들어온 날을 따라간다(같은 값은 그대로).
OVERLAP_DAYS = 14
#: 이 날 수 이상인 창이 비어 오면 실패 — 거래일이 반드시 들어 있다(없는 항목 코드도 INFO-200 으로 온다).
EMPTY_WINDOW_DAYS = 10
SLEEP = 0.3
EX_CONFIG = 78

#: ECOS 결과 코드 → 할 일(2026-10-13 실측한 것 · 개발 명세의 이름).
HINTS = {
    "INFO-100": "인증키가 유효하지 않다 — ECOS 마이페이지에서 키와 이용기간(발급일부터 2년)을 확인하고 .env 의 ECOS_API_KEY 를 고친다.",
    "ERROR-101": "날짜 꼴이 주기와 맞지 않는다(일별은 YYYYMMDD).",
    "ERROR-301": "조회 건수 값이 틀렸다.",
    "ERROR-602": "호출이 너무 잦아 막혔다 — 잠시 뒤 같은 명령으로 이어 간다.",
}


class EcosError(RuntimeError):
    """ECOS 가 정상 응답을 주지 않았다(또는 비어서는 안 될 창이 비었다)."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def scrub(text: str, key: Optional[str]) -> str:
    """밖으로 내보내는 글에서 인증키를 가린다 — 키가 짧거나 비면 그대로(가릴 것이 없다)."""
    if key and len(key) >= 4:
        return text.replace(key, "***")
    return text


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _iso_day(yyyymmdd: str) -> str:
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        raise EcosError(f"ECOS 날짜 꼴이 일별(YYYYMMDD)이 아니다: {s!r}")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


# ==================================================
# 1. 표 — 정의는 collector/db.py 한 곳(SCHEMA — 연결할 때마다 만든다). 이름은 시험이 쓰도록 여기서도 보인다.
# ==================================================
ECOS_SERIES_DDL = db.ECOS_SERIES_DDL


def ensure_table(conn: sqlite3.Connection) -> None:
    """`db.connect()` 로 연 연결에는 이미 표가 있다 — 그 밖의 연결(시험의 임시 DB)에서 표를 만든다."""
    conn.executescript(ECOS_SERIES_DDL)


# ==================================================
# 2. 응답 읽기 — 네트워크 없이 시험한다(TC-ECS)
# ==================================================
def parse(body: bytes, cycle: str = CYCLE, stat: str = STAT) -> Tuple[int, List[Dict]]:
    """StatisticSearch 응답 → (전체 줄 수, 줄들). 「자료 없음」(INFO-200)은 (0, []) · 다른 결과 코드는 `EcosError`.

    줄의 통계표 코드는 응답의 STAT_CODE 가 정본이고, 비어 오면 부른 통계표(`stat`)로 둔다."""
    try:
        d = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise EcosError(f"ECOS 응답이 JSON 이 아니다 — {type(ex).__name__}") from None
    if "StatisticSearch" in d:
        s = d["StatisticSearch"] or {}
        rows = []
        for r in s.get("row") or []:
            v = (r.get("DATA_VALUE") or "").strip()
            try:
                value = float(v) if v else None
            except ValueError:
                raise EcosError(f"ECOS 값이 숫자가 아니다: {v!r}({r.get('TIME')})") from None
            rows.append({
                "stat_code": r.get("STAT_CODE") or stat,
                "item_code": r.get("ITEM_CODE1") or "",
                "cycle": cycle,
                "date": _iso_day(r.get("TIME") or ""),
                "value": value,
                "unit": r.get("UNIT_NAME") or "",
                "item_name": r.get("ITEM_NAME1") or "",
            })
        return int(s.get("list_total_count") or 0), rows
    res = d.get("RESULT") or {}
    code, msg = str(res.get("CODE") or ""), str(res.get("MESSAGE") or "")
    if code == "INFO-200":
        return 0, []
    hint = HINTS.get(code, "")
    raise EcosError(f"ECOS {code or '알 수 없는 응답'} — {msg}" + (f" · {hint}" if hint else ""), code)


def upsert(conn: sqlite3.Connection, rows: List[Dict], *, at: str, raw_sha256: str = "") -> Dict[str, int]:
    """같은 (표 · 항목 · 주기 · 날짜)는 한 줄. 값이 같으면 그대로 · 바뀌면 값과 updated_at 만(처음 받은 시각은 그대로)."""
    out = {"new": 0, "changed": 0, "same": 0}
    for r in rows:
        key = (r["stat_code"], r["item_code"], r["cycle"], r["date"])
        old = conn.execute("SELECT value FROM ecos_series WHERE stat_code=? AND item_code=? AND cycle=? AND date=?",
                           key).fetchone()
        if old is None:
            conn.execute(
                "INSERT INTO ecos_series (stat_code, item_code, cycle, date, value, unit, item_name, fetched_at, "
                "updated_at, raw_sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (*key, r["value"], r["unit"], r["item_name"], at, at, raw_sha256))
            out["new"] += 1
        elif old[0] != r["value"]:
            conn.execute("UPDATE ecos_series SET value=?, unit=?, item_name=?, updated_at=?, raw_sha256=? "
                         "WHERE stat_code=? AND item_code=? AND cycle=? AND date=?",
                         (r["value"], r["unit"], r["item_name"], at, raw_sha256, *key))
            out["changed"] += 1
        else:
            out["same"] += 1
    return out


# ==================================================
# 3. 받기
# ==================================================
def _session():
    import requests

    return requests.Session()


def fetch_range(conn: sqlite3.Connection, limiter: RateLimiter, key: str, item: str, bgn: str, fin: str, *,
                session, stat: str = STAT) -> Dict[str, int]:
    """한 항목의 [bgn, fin](YYYYMMDD) — 쪽마다 원문 · 줄을 한 트랜잭션에. 거래일이 들어 있을 긴 창이 비면 실패."""
    total = {"calls": 0, "rows": 0, "new": 0, "changed": 0, "same": 0}
    start = 1
    while True:
        end = start + PAGE - 1
        url = URL.format(key=key, start=start, end=end, stat=stat, cycle=CYCLE, bgn=bgn, fin=fin, item=item)
        limiter.wait()
        try:
            r = session.get(url, timeout=30)
        except Exception as ex:  # requests.RequestException 등 — 예외 글에 주소(키)가 들어 있다
            raise EcosError(scrub(f"ECOS 연결 실패 — {type(ex).__name__}: {ex}", key)) from None
        total["calls"] += 1
        if r.status_code != 200:
            raise EcosError(f"ECOS HTTP {r.status_code}")
        n, rows = parse(r.content, stat=stat)
        conn.execute("BEGIN IMMEDIATE")
        try:
            sha = raw_store.save(conn, SOURCE, f"{stat}/{item}/{CYCLE}/{bgn}-{fin}/{start}", r.content,
                                 http_status=r.status_code, note=f"rows={len(rows)} total={n}")
            u = upsert(conn, rows, at=_now_iso(), raw_sha256=sha)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        total["rows"] += len(rows)
        for k in ("new", "changed", "same"):
            total[k] += u[k]
        if end >= n or not rows:
            break
        start = end + 1
    span = (datetime.strptime(fin, "%Y%m%d").date() - datetime.strptime(bgn, "%Y%m%d").date()).days + 1
    if total["rows"] == 0 and span >= EMPTY_WINDOW_DAYS:
        raise EcosError(f"ECOS 가 {bgn} ~ {fin}({span}일) 창을 비워 보냈다 — 거래일이 있는 창이다. 항목 코드({item})가 "
                        "바뀌었거나 ECOS 가 값을 아직 싣지 않았다 · StatisticItemList 로 항목을 다시 본다")
    return total


def last_date(conn: sqlite3.Connection, item: str, stat: str = STAT) -> Optional[date]:
    v = conn.execute("SELECT MAX(date) FROM ecos_series WHERE stat_code=? AND item_code=? AND cycle=?",
                     (stat, item, CYCLE)).fetchone()[0]
    return date.fromisoformat(v) if v else None


def collect(conn: sqlite3.Connection, today: date, *, key: str, since: Optional[date] = None, session=None,
            limiter: Optional[RateLimiter] = None) -> Dict[str, Dict[str, int]]:
    """계열마다 한 범위 — `since` 가 있으면 그날부터(지난 값), 없으면 마지막 날 앞 14일부터(매일). 처음이면 ECOS 첫 날부터."""
    sess = session or _session()
    lim = limiter or RateLimiter(SLEEP, name="ECOS")
    out: Dict[str, Dict[str, int]] = {}
    for stat, series in GROUPS:
        for name, item, _label, first in series:
            if since is not None:
                bgn = max(since.strftime("%Y%m%d"), first)
            else:
                last = last_date(conn, item, stat)
                bgn = (last - timedelta(days=OVERLAP_DAYS)).strftime("%Y%m%d") if last else first
            out[name] = fetch_range(conn, lim, key, item, bgn, today.strftime("%Y%m%d"), session=sess, stat=stat)
            out[name]["from"] = bgn  # type: ignore[assignment]
    return out


# ==================================================
# 4. 상태 · 명령
# ==================================================
def status_lines(conn: sqlite3.Connection) -> Iterator[str]:
    for stat, series in GROUPS:
        for name, item, label, _first in series:
            n, lo, hi = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM ecos_series WHERE stat_code=? AND item_code=? "
                                     "AND cycle=?", (stat, item, CYCLE)).fetchone()
            yield f"  {label:<14} {n:>6,}줄 · {lo or '-'} ~ {hi or '-'}"
    w = conn.execute("SELECT COUNT(*) FROM raw_response WHERE source=?", (SOURCE,)).fetchone()[0]
    yield f"  원문 {w:,}건 · 출처 표시: {ATTRIBUTION}"


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.ecos",
                                description="한국은행 ECOS 시장금리(신용 스프레드 재료) · 주가지수(시장 계절성 재료) 받기")
    sub = p.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("daily", help="계열마다 마지막 날 앞 14일부터 오늘까지 — 러너 단계")
    d.add_argument("--quiet", action="store_true")
    b = sub.add_parser("backfill", help="지난 값 전부(이미 있는 줄은 그대로)")
    b.add_argument("--from", dest="bgn", default="", help="시작 YYYYMMDD(비우면 계열마다 ECOS 첫 날)")
    st = sub.add_parser("status")
    for x in (d, b, st):
        x.add_argument("--db", default="", help="(시험용) 수집 DB 대신 쓸 SQLite 파일")
    a = p.parse_args(argv)

    key = None
    if a.mode in ("daily", "backfill"):
        try:
            key = config.require("ECOS_API_KEY", "한국은행 경제통계시스템(ECOS) 인증키")
        except config.MissingKey as e:
            print(f"🔴 ECOS 인증키가 없어 받지 않는다 — {e}")
            return EX_CONFIG
    conn = db.connect(Path(a.db) if a.db else None)
    try:
        ensure_table(conn)
        if a.mode == "status":
            for ln in status_lines(conn):
                print(ln)
            return 0
        since = None
        if a.mode == "backfill":
            since = datetime.strptime(a.bgn, "%Y%m%d").date() if a.bgn else date(1995, 1, 1)
        r = collect(conn, date.today(), key=key or "", since=since)
        for name, x in r.items():
            print(f"  ECOS {name} — {x['from']} 부터 · 부름 {x['calls']} · 줄 {x['rows']:,} · 새 {x['new']:,} · "
                  f"고침 {x['changed']} · 그대로 {x['same']:,}")
    except EcosError as e:
        print(f"🔴 {scrub(str(e), key)}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
