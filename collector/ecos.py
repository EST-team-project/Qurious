"""한국은행 경제통계시스템(ECOS) 시장금리 · 주가지수 · 기준금리 · 환율 · 소비자물가 — 신용 스프레드 · 시장 계절성 · 거시 재료
(④-2 재무 · 신용 위험 · 2026-10-13 / 주가지수 2026-10-14 · 금융 필수 지식 › 계절성 / G1 셋 · 국고채 10년 2026-10-24 · 할 일 ①-05).

    python -m collector.ecos daily [--quiet]                 계열마다 마지막 시점 앞(일 14일 · 월 3달)부터 오늘까지 — 러너 단계
    python -m collector.ecos backfill [--from 19950101]      지난 값 전부(계열마다 쪽 넘기기 · 이미 있는 줄은 그대로)
    python -m collector.ecos status

G1 셋 · 국고채 10년(2026-10-24 · 사용자 결정 「G1 셋 + 국고채 10년」)
-------------------------------------------------------------------
2026-10-22 일회 수집(HF 비공개 `kr-macro-series` — 날짜 판 보관본으로 그대로 둔다)에서 실측한 세 계열과, 같은 시장금리 표의
국고채(10년)(StatisticItemList 2026-10-24 실측 — 010210000 · 일 · 2000-12-18 ~ · 6,399줄 · 연%)을 매일 받는다:

    722Y001 / 0101000  한국은행 기준금리             일   1999-05-06 ~   원 출처 한국은행
    731Y001 / 0000001  원/미국달러(매매기준율)        일   1964-05-04 ~   원 출처 서울외국환중개
    901Y009 / 0        소비자물가지수 총지수          월   1965-01 ~      원 출처 국가데이터처(KOSIS)
    817Y002 / 010210000 국고채(10년)                일   2000-12-18 ~   원 출처 한국은행(시장금리 표)

· **월 주기가 처음 들어왔다** — 시점 꼴이 다르다(일 YYYYMMDD → `YYYY-MM-DD` · 월 YYYYMM → `YYYY-MM`). 월 값에 가짜 날(1일)을
  붙이지 않는다 — 일회 수집본과 같은 꼴이고, HF 연도 파일 경계(「'2026' 이상 · '2027' 미만」 · `hf_dataset.YEAR_LO`)는 꼴과
  상관없이 맞다. 앱의 일 단위 읽기(신용 스프레드 · 계절성)는 `cycle = 'D'` 로 거르므로 월 줄이 섞이지 않는다.
· 되돌아보기 창 · 빈 창 판정도 주기마다 다르다(`OVERLAP` · `EMPTY_WINDOW`) — 물가는 다음 달 초에 실리므로 마지막 달 앞 3달부터
  다시 받고, 3달 넘는 창이 비면 실패로 센다.
· 이용 조건 셋(2026-10-22 확인 · 근거 원문 지문 `qurious-quant/source-terms-evidence`) — ECOS 「출처를 명시하는 한 상업적
  용도를 포함하여 무료로 자유롭게 사용, 가공 및 재배포」 · KOSIS 이용지침(출처 명시 · 임의 변경 금지 — 소비자물가) ·
  **서울외국환중개 약관은 사전 승낙 없는 영리목적 복제 · 배포를 막는다(환율)** → 이 표는 지금처럼 비공개 백업에만 두고, 화면
  출처는 원 출처까지(`ORIGIN`).

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
    # 장단기 금리차(10년 − 3년) 재료 — 2026-10-24 StatisticItemList 실측(010210000 · 일 · 2000-12-18 ~ · 6,399줄 · 연%).
    ("treasury_10y", "010210000", "국고채(10년)", "20001218"),
)
#: 통계표 「1.5.1.1. 주식시장(일)」 — 시장 계절성 재료(2026-10-14 실측 · 앱 `seasonality.MARKETS` 가 열쇠 · 코드를 맞춘다 — TC-SE-01).
INDEX_STAT = "802Y001"
INDEX_SERIES: Tuple[Tuple[str, str, str, str], ...] = (
    ("kospi", "0001000", "KOSPI지수", "19950103"),
    ("kosdaq", "0089000", "KOSDAQ지수", "20030102"),
)
#: G1 셋(2026-10-22 일회 수집 실측 · 2026-10-24 매일 단계로) — 통계표마다 한 계열. 첫 시점은 그 주기의 꼴(일 8자리 · 월 6자리).
BASE_RATE_STAT = "722Y001"     # 1.3.1. 한국은행 기준금리 및 여수신금리 — 날마다 한 줄(바뀐 날이 아니라 모든 날)
BASE_RATE_SERIES: Tuple[Tuple[str, str, str, str], ...] = (("base_rate", "0101000", "한국은행 기준금리", "19990506"),)
FX_STAT = "731Y001"            # 3.1.1.1. 주요국 통화의 대원화환율 — 거래일만
FX_SERIES: Tuple[Tuple[str, str, str, str], ...] = (("usd_krw", "0000001", "원/미국달러(매매기준율)", "19640504"),)
CPI_STAT = "901Y009"           # 4.2.1. 소비자물가지수 — 월(다음 달 초에 실림)
CPI_SERIES: Tuple[Tuple[str, str, str, str], ...] = (("cpi_total", "0", "소비자물가지수 총지수", "196501"),)
#: 받는 묶음 — (통계표, 주기, 계열들). 시장금리는 재무 · 신용 위험이, 주가지수는 계절성이, G1 셋은 거시 화면(할 일 ①-10)이 읽는다.
GROUPS: Tuple[Tuple[str, str, Tuple[Tuple[str, str, str, str], ...]], ...] = (
    (STAT, "D", SERIES),
    (INDEX_STAT, "D", INDEX_SERIES),
    (BASE_RATE_STAT, "D", BASE_RATE_SERIES),
    (FX_STAT, "D", FX_SERIES),
    (CPI_STAT, "M", CPI_SERIES),
)
#: 원 출처 — ECOS 가 모아 싣지만 작성기관이 다른 표(StatisticTableList 의 ORG_NAME · 2026-10-22 확인). 화면 출처 표시에 함께 쓴다
#: (환율은 서울외국환중개 약관이 영리목적 복제 · 배포를 막는다 — 머리말).
ORIGIN: Dict[str, str] = {
    STAT: "한국은행", INDEX_STAT: "한국은행", BASE_RATE_STAT: "한국은행",
    FX_STAT: "서울외국환중개", CPI_STAT: "국가데이터처",
}
#: 한 번에 받는 줄 수 — 가장 긴 계열(원/달러 1964 ~)이 약 17,500줄이라 처음 한 번은 두 쪽 · 매일은 한 쪽.
PAGE = 10_000
#: 매일 받기는 마지막 시점 앞 이만큼부터 다시 받는다 — ECOS 가 고친 값 · 늦게 들어온 시점을 따라간다(같은 값은 그대로).
#: 일은 날 수 · 월은 달 수.
OVERLAP_DAYS = 14
OVERLAP_MONTHS = 3
#: 이 길이 이상인 창이 비어 오면 실패 — 값이 반드시 들어 있다(없는 항목 코드도 INFO-200 으로 온다). 일은 날 수 · 월은 달 수.
EMPTY_WINDOW_DAYS = 10
EMPTY_WINDOW_MONTHS = 3
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


def _iso_month(yyyymm: str) -> str:
    s = (yyyymm or "").strip()
    if len(s) != 6 or not s.isdigit() or not 1 <= int(s[4:]) <= 12:
        raise EcosError(f"ECOS 시점 꼴이 월별(YYYYMM)이 아니다: {s!r}")
    return f"{s[:4]}-{s[4:]}"


def _iso_time(t: str, cycle: str) -> str:
    """ECOS TIME → 표의 date 칸 — 일 `YYYY-MM-DD` · 월 `YYYY-MM`(가짜 날을 붙이지 않는다). 모르는 주기는 예외(조용히 섞지 않는다)."""
    if cycle == "D":
        return _iso_day(t)
    if cycle == "M":
        return _iso_month(t)
    raise EcosError(f"이 수집기가 읽지 못하는 ECOS 주기다: {cycle!r}(일 D · 월 M 만)")


def _add_months(y: int, m: int, k: int) -> Tuple[int, int]:
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def _window_start(last: str, cycle: str) -> str:
    """매일 받기의 시작 시점(ECOS 꼴) — 마지막 시점(표의 date 칸) 앞 14일 · 3달."""
    if cycle == "D":
        return (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).strftime("%Y%m%d")
    y, m = _add_months(int(last[:4]), int(last[5:7]), -OVERLAP_MONTHS)
    return f"{y:04d}{m:02d}"


def _until(today: date, cycle: str) -> str:
    """창의 끝 시점(ECOS 꼴) — 오늘(일) · 이번 달(월)."""
    return today.strftime("%Y%m%d") if cycle == "D" else today.strftime("%Y%m")


def _span(bgn: str, fin: str, cycle: str) -> int:
    """창 길이 — 일은 날 수 · 월은 달 수(양 끝 포함)."""
    if cycle == "D":
        return (datetime.strptime(fin, "%Y%m%d").date() - datetime.strptime(bgn, "%Y%m%d").date()).days + 1
    return (int(fin[:4]) * 12 + int(fin[4:])) - (int(bgn[:4]) * 12 + int(bgn[4:])) + 1


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
                "date": _iso_time(r.get("TIME") or "", cycle),
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
                session, stat: str = STAT, cycle: str = CYCLE) -> Dict[str, int]:
    """한 항목의 [bgn, fin](일 YYYYMMDD · 월 YYYYMM) — 쪽마다 원문 · 줄을 한 트랜잭션에. 값이 들어 있을 긴 창이 비면 실패."""
    total = {"calls": 0, "rows": 0, "new": 0, "changed": 0, "same": 0}
    start = 1
    while True:
        end = start + PAGE - 1
        url = URL.format(key=key, start=start, end=end, stat=stat, cycle=cycle, bgn=bgn, fin=fin, item=item)
        limiter.wait()
        try:
            r = session.get(url, timeout=30)
        except Exception as ex:  # requests.RequestException 등 — 예외 글에 주소(키)가 들어 있다
            raise EcosError(scrub(f"ECOS 연결 실패 — {type(ex).__name__}: {ex}", key)) from None
        total["calls"] += 1
        if r.status_code != 200:
            raise EcosError(f"ECOS HTTP {r.status_code}")
        n, rows = parse(r.content, cycle=cycle, stat=stat)
        conn.execute("BEGIN IMMEDIATE")
        try:
            sha = raw_store.save(conn, SOURCE, f"{stat}/{item}/{cycle}/{bgn}-{fin}/{start}", r.content,
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
    span = _span(bgn, fin, cycle)
    if total["rows"] == 0 and span >= (EMPTY_WINDOW_DAYS if cycle == "D" else EMPTY_WINDOW_MONTHS):
        unit = "일" if cycle == "D" else "달"
        raise EcosError(f"ECOS 가 {bgn} ~ {fin}({span}{unit}) 창을 비워 보냈다 — 값이 있는 창이다. 항목 코드({item})가 "
                        "바뀌었거나 ECOS 가 값을 아직 싣지 않았다 · StatisticItemList 로 항목을 다시 본다")
    return total


def last_time(conn: sqlite3.Connection, item: str, stat: str = STAT, cycle: str = CYCLE) -> Optional[str]:
    """그 계열의 마지막 시점(표의 date 칸 그대로 — 일 YYYY-MM-DD · 월 YYYY-MM). 통계표 · 주기까지 맞춰 센다(코드가 겹쳐도 안 섞이게)."""
    v = conn.execute("SELECT MAX(date) FROM ecos_series WHERE stat_code=? AND item_code=? AND cycle=?",
                     (stat, item, cycle)).fetchone()[0]
    return v or None


def last_date(conn: sqlite3.Connection, item: str, stat: str = STAT) -> Optional[date]:
    """일 계열의 마지막 날(옛 이름 그대로 — 일 주기만)."""
    v = last_time(conn, item, stat, "D")
    return date.fromisoformat(v) if v else None


def collect(conn: sqlite3.Connection, today: date, *, key: str, since: Optional[date] = None, session=None,
            limiter: Optional[RateLimiter] = None) -> Dict[str, Dict[str, int]]:
    """계열마다 한 범위 — `since` 가 있으면 그 시점부터(지난 값), 없으면 마지막 시점 앞(일 14일 · 월 3달)부터(매일).
    처음(그 계열 줄이 없음)이면 ECOS 첫 시점부터 — 새 계열은 첫 회차가 저절로 지난 값을 다 받는다."""
    sess = session or _session()
    lim = limiter or RateLimiter(SLEEP, name="ECOS")
    out: Dict[str, Dict[str, int]] = {}
    for stat, cycle, series in GROUPS:
        for name, item, _label, first in series:
            if since is not None:
                bgn = max(since.strftime("%Y%m%d") if cycle == "D" else since.strftime("%Y%m"), first)
            else:
                last = last_time(conn, item, stat, cycle)
                bgn = _window_start(last, cycle) if last else first
            out[name] = fetch_range(conn, lim, key, item, bgn, _until(today, cycle), session=sess, stat=stat,
                                    cycle=cycle)
            out[name]["from"] = bgn  # type: ignore[assignment]
    return out


# ==================================================
# 4. 상태 · 명령
# ==================================================
def status_lines(conn: sqlite3.Connection) -> Iterator[str]:
    for stat, cycle, series in GROUPS:
        for name, item, label, _first in series:
            n, lo, hi = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM ecos_series WHERE stat_code=? AND item_code=? "
                                     "AND cycle=?", (stat, item, cycle)).fetchone()
            tag = "" if cycle == "D" else " · 월"
            yield f"  {label:<14} {n:>6,}줄 · {lo or '-'} ~ {hi or '-'}{tag} · 원 출처 {ORIGIN.get(stat, '한국은행')}"
    w = conn.execute("SELECT COUNT(*) FROM raw_response WHERE source=?", (SOURCE,)).fetchone()[0]
    yield f"  원문 {w:,}건 · 출처 표시: {ATTRIBUTION}"


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.ecos",
                                description="한국은행 ECOS 시장금리(신용 스프레드 재료) · 주가지수(시장 계절성 재료) · 기준금리 · 원/달러 · 소비자물가(거시 재료) 받기")
    sub = p.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("daily", help="계열마다 마지막 시점 앞(일 14일 · 월 3달)부터 오늘까지 — 러너 단계")
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
            since = datetime.strptime(a.bgn, "%Y%m%d").date() if a.bgn else date(1900, 1, 1)   # 비우면 계열마다 첫 시점(환율 1964 · 물가 1965)
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
