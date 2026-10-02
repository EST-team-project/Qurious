"""거래일 달력 · 금융 일정 — 지난날과 **아직 오지 않은 날**의 거래일 (목표 기능 ① W4 · 설계서 5.2.4).

    python -m collector.market_calendar build [--quiet] [--no-fetch]   공휴일 받기 → 달력 → 배당락일 다시 계산 → 일정
    python -m collector.market_calendar status                          표 셋의 범위 · 다가오는 휴장 · 만기
    python -m collector.market_calendar show --from 2026-10-01 --to 2026-10-31

왜 필요한가
-----------
지금까지 거래일 달력은 ``price_daily`` 에 시세가 쌓인 날이었다(``sources/dart.trading_days``).
틀린 달력보다 없는 달력이 낫다는 판단이었는데(``sources/portal.weekdays``), 그 달력에는 **내일이 없다.**
2026-10-02 에 그 때문에 틀린 값을 실제로 찾았다.

  ① 배당락일 — 아직 시세가 없는 기준일을 달력 끝에서 세어 버렸다. 블랙야크아이앤씨(478560) 중간배당
     기준일 10-13 의 배당락일이 09-29 로 들어가 있었다(맞는 값 10-12 — 10-09 는 한글날). 기준일 09-30 인
     8행 중 2행은 09-30 시세가 들어오기 **전에** 계산돼 09-28 이었다(맞는 값 09-29). 배당락일은 TR 이
     배당을 더하는 날이라 TR 도 함께 틀렸다.
  ② 포털이 0건을 준 날이 휴장인지 「아직 안 올라온 거래일」 인지 모른다(README §7) — 데이터 상태
     화면이 「늦었다」 를 판정하려면 「그날이 거래일이었나」 를 알아야 한다.

리밸런싱 날짜(③ 자산배분)와 체결일(④ 모의투자)도 앞날의 거래일을 쓴다(설계서 9절).

어떻게 만드나 — 규칙 세 겹 + 지난날은 시세로 확인
--------------------------------------------------
1. 주말(토 · 일)
2. 공휴일 — 한국천문연구원 특일 정보(공공데이터포털 ``getRestDeInfo``)에서 ``isHoliday=Y`` 인 날.
   대체공휴일 · 선거일 · 임시공휴일까지 실린다(2026: 노동절 · 전국동시지방선거 · 제헌절).
3. 거래소 휴장 — 근로자의 날(5-1) · 연말 휴장일(12-31. 그날이 주말 · 공휴일이면 그 앞 마지막 평일).

지난날(시세 마지막 날까지)은 **시세로 확인**한다(``basis='observed'``) — 시세가 있으면 거래일, 없으면 휴장.
규칙과 시세가 어긋난 날은 시세를 따르고 ``note`` 에 남기며 ``build`` 가 센다.

실측 2026-10-02: 이 규칙이 2020-01-02 ~ 2026-09-30 의 거래일 1,655일과 **한 날도 어긋나지 않았다**
(규칙으로 설명되지 않는 평일 휴장 0 · 공휴일인데 거래한 날 0). 공휴일만으로 설명되지 않던 평일 휴장 10일은
5-1 네 번(2020 · 2023 · 2024 · 2025)과 연말 여섯 번(2020-12-31 · 2021-12-31 · **2022-12-30** · **2023-12-29** ·
2024-12-31 · 2025-12-31 — 굵은 둘은 12-31 이 주말이라 앞당긴 날)이었다. 2026 년부터 5-1 은 「노동절」 로
특일 정보에 공휴일로 실린다.

달력은 특일 정보가 **이어서 있는 해**의 12-31 까지만 만든다 — 공휴일을 모르는 해를 주말 규칙만으로 채우면
설 · 추석이 거래일로 들어간다(「틀린 달력은 없는 것보다 나쁘다」 는 원래 판단은 이 경계에서 지킨다).

표 셋 (수집 DB)
---------------
    holiday_kasi     받은 것 — 특일 정보 응답 행(날짜 · 이름 · 공휴일 여부). 지난해는 한 번, 올해 · 내년은
                     build 때마다 다시 받는다(임시공휴일은 며칠 전에야 정해진다).
    market_calendar  계산한 것 — 하루 한 행. 매번 통째로 다시 만든다.
    market_event     계산한 것 — 평일 휴장 · 파생 만기 · 배당 기준일 · 배당락일. 매번 통째로 다시 만든다.

파생 만기 규칙 — 코스피200 선물(3 · 6 · 9 · 12월) · 옵션(매월)의 최종거래일은 「각 결제월의 두 번째 목요일
(공휴일인 경우 순차적으로 앞당김)」(증권사 상품 안내 — 다올투자증권 KOSPI200선물 · 유진투자증권 옵션 안내.
2차 출처이고 거래소 규정 원문은 아직 못 읽었다 🟡).

하지 않는 것
------------
- 개장 시각이 바뀌는 날(새해 첫 거래일 · 수능일 10:00 개장) — 다음에 일정 종류로 더한다.
- 거래소의 갑작스러운 임시 휴장 — 미리 알 수 없다. 지난날이 되면 시세가 바로잡는다.
- 포털 수집(``backfill``)의 「0건 → 10일 뒤 휴장 확정」 규칙은 바꾸지 않는다. 이 달력은 그 판정을 **읽는** 쪽이다.

⚠️ 매일 12:30 러너(`scripts/daily_update.py`)의 ``calendar`` 단계가 이 명령을 부른다. 러너가 도는 동안
   따로 돌리지 않는다(쓰는 쪽이 둘이면 한쪽이 60초 기다리다 실패한다).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from collector import config, db
from collector.console import utf8_stdio
from collector.sources import dart

KST = zoneinfo.ZoneInfo("Asia/Seoul")

KASI_URL = "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"

#: 시세가 2020-01-02 부터다 — 그 앞 달력은 쓸 곳이 없다. 앞으로 당기면 배당 표에서 지금은 지워지는
#: 2019년 기준일 행(``dividend.process_month`` 의 prune)이 살아나 TR · HF 내보내기가 달라진다.
FIRST_YEAR = 2020

#: 특일 정보 호출 사이 쉼(초). 하루 2~8번이라 한도(일 10,000)와는 거리가 멀다 — 예의상 둔다.
KASI_SLEEP = 0.3


WEEKEND = {5: "토요일", 6: "일요일"}
QUARTER_MONTHS = (3, 6, 9, 12)

#: 배당락일을 아직 정할 수 없는 행에 붙이는 표시 — 정의는 sources/dart.py(배당 단계와 같은 문구). 달력이 늘어 정해지면 이 문구만 지운다.
EX_HOLD = dart.EX_HOLD


class CalendarError(RuntimeError):
    """달력을 만들 수 없다 — 공휴일 표가 없거나 비었다."""


class KasiError(RuntimeError):
    """특일 정보를 받지 못했다. 메시지에 키 · 주소를 담지 않는다."""


def now_kst() -> datetime:
    return datetime.now(KST)


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _from_ymd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def ensure_schema(conn: sqlite3.Connection) -> None:
    """표 셋(holiday_kasi · market_calendar · market_event)은 `collector/db.py` 의 SCHEMA 에 있다 — 한 곳에서 정의한다."""
    conn.executescript(db.SCHEMA)


# ==================================================
# 1. 공휴일 받기 — 한국천문연구원 특일 정보
# ==================================================
def fetch_kasi_year(year: int, *, opener: Callable = urllib.request.urlopen,
                    timeout: int = 20) -> List[Dict[str, object]]:
    """특일 정보 한 해치 — ``[{locdate, date_name, is_holiday, date_kind, seq}]``.

    서비스키는 포털 키 그대로다(증권상품 · 지수시세와 같은 계정 · 이용 신청은 따로 — 설계서 14.2).
    ``config.portal_key()`` 가 인코딩을 벗긴 값을 주므로 주소에 넣을 때 다시 인코딩한다.
    오류 메시지에는 주소를 넣지 않는다 — 주소에 키가 들어 있다.
    """
    key = config.portal_key()
    q = urllib.parse.urlencode({"solYear": str(year), "numOfRows": "100", "_type": "json"})
    url = f"{KASI_URL}?serviceKey={urllib.parse.quote(key, safe='')}&{q}"
    try:
        with opener(url, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise KasiError(f"{year}년 특일 정보 HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KasiError(f"{year}년 특일 정보 연결 실패({type(e).__name__})") from None
    except ValueError:
        # 키가 틀리거나 이용 신청 전이면 JSON 이 아니라 XML 오류 문서가 온다.
        raise KasiError(f"{year}년 특일 정보 응답이 JSON 이 아니다 — 키 · 이용 신청을 확인한다") from None
    head = (body.get("response") or {}).get("header") or {}
    if head.get("resultCode") != "00":
        raise KasiError(f"{year}년 특일 정보 오류 {head.get('resultCode')} {head.get('resultMsg')}")
    items = ((body["response"].get("body") or {}).get("items")) or {}
    item = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(item, dict):           # 한 건이면 목록이 아니라 객체 하나로 온다
        item = [item]
    out = []
    for it in item:
        s = str(it.get("locdate", ""))
        if len(s) != 8 or not s.isdigit():
            continue
        out.append({
            "locdate": _from_ymd(s).isoformat(),
            "date_name": str(it.get("dateName", "")).strip(),
            "is_holiday": str(it.get("isHoliday", "")).strip(),
            "date_kind": str(it.get("dateKind", "")).strip(),
            "seq": it.get("seq"),
        })
    return out


def years_to_fetch(conn: sqlite3.Connection, today: date) -> List[int]:
    """받을 해 — 아직 없는 지난해 + 올해 · 내년(이 둘은 매번)."""
    have = {int(r[0]) for r in conn.execute("SELECT DISTINCT substr(locdate, 1, 4) FROM holiday_kasi")}
    past = [y for y in range(FIRST_YEAR, today.year) if y not in have]
    return past + [today.year, today.year + 1]


def refresh_holidays(conn: sqlite3.Connection, years: Sequence[int], *,
                     fetch: Callable[[int], List[Dict[str, object]]] = fetch_kasi_year,
                     sleep: float = KASI_SLEEP) -> Dict[int, int]:
    """해마다 넣은 행 수. 응답이 0건인 해(아직 발표 전)는 **지우지 않는다** — 어제 받은 것을 둔다."""
    at = now_kst().isoformat(timespec="seconds")
    out: Dict[int, int] = {}
    for i, y in enumerate(years):
        if i and sleep:
            time.sleep(sleep)
        items = fetch(y)
        out[y] = len(items)
        if not items:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM holiday_kasi WHERE substr(locdate, 1, 4) = ?", (str(y),))
            conn.executemany(
                "INSERT OR REPLACE INTO holiday_kasi (locdate, date_name, is_holiday, date_kind, seq, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(it["locdate"], it["date_name"], it["is_holiday"], it["date_kind"], it["seq"], at) for it in items])
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return out


def public_holidays(conn: sqlite3.Connection) -> Dict[date, str]:
    """공휴일(``is_holiday='Y'``) → 이름. 같은 날 이름이 둘이면 「 · 」 로 잇는다."""
    out: Dict[date, str] = {}
    for loc, name in conn.execute(
            "SELECT locdate, date_name FROM holiday_kasi WHERE is_holiday = 'Y' ORDER BY locdate, seq, date_name"):
        d = date.fromisoformat(loc)
        out[d] = f"{out[d]} · {name}" if d in out and name not in out[d] else (out.get(d) or name)
    return out


def holiday_years(conn: sqlite3.Connection) -> List[int]:
    return sorted(int(r[0]) for r in conn.execute("SELECT DISTINCT substr(locdate, 1, 4) FROM holiday_kasi"))


# ==================================================
# 2. 규칙
# ==================================================
def year_end_closure(year: int, holidays: Dict[date, str]) -> date:
    """연말 휴장일 — 12-31. 그날이 주말 · 공휴일이면 그 앞 마지막 평일(2022-12-30 · 2023-12-29 실측)."""
    d = date(year, 12, 31)
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


def rule_reason(d: date, holidays: Dict[date, str], year_end: Optional[date] = None) -> Optional[str]:
    """규칙으로 휴장이면 그 까닭, 거래일이면 None.

    공휴일 이름을 주말보다 먼저 쓴다 — 토요일인 개천절은 「개천절」 로 읽히는 쪽이 낫다(요일은 화면이 따로 보인다).
    """
    if d in holidays:
        return holidays[d]
    if d.weekday() in WEEKEND:
        return WEEKEND[d.weekday()]
    if d.month == 5 and d.day == 1:
        # 2025 년까지는 특일 정보에 없었다(근로자의 날은 관공서 공휴일이 아니었다). 거래소는 매해 쉬었다.
        return "근로자의 날"
    if d == (year_end or year_end_closure(d.year, holidays)):
        return "연말 휴장일"
    return None


@dataclass
class Day:
    cal_date: date
    is_trading_day: int
    reason: str
    basis: str            # observed | rule
    note: str = ""


def calendar_end(years: Sequence[int]) -> Optional[date]:
    """특일 정보가 FIRST_YEAR 부터 **이어서** 있는 마지막 해의 12-31. 빈 해가 있으면 그 앞에서 멈춘다."""
    have = set(years)
    end_year = None
    y = FIRST_YEAR
    while y in have:
        end_year = y
        y += 1
    return date(end_year, 12, 31) if end_year else None


def observed_days(conn: sqlite3.Connection) -> List[date]:
    """시세가 있는 날(거래일로 확인된 날) — ``price_daily`` 의 날짜."""
    return [_from_ymd(r[0]) for r in conn.execute("SELECT DISTINCT bas_dt FROM price_daily ORDER BY bas_dt")]


def portal_states(conn: sqlite3.Connection) -> Dict[str, str]:
    """포털 수집 상태(YYYYMMDD → done · empty · holiday · error)."""
    return {r[0]: r[1] for r in conn.execute("SELECT bas_dt, status FROM ingest_day WHERE source = 'portal'")}


def build_days(holidays: Dict[date, str], end: date, observed: Sequence[date],
               states: Optional[Dict[str, str]] = None) -> Tuple[List[Day], Dict[str, int]]:
    """FIRST_YEAR-01-01 ~ ``end`` 하루 한 행과 센 것.

    시세 마지막 날까지는 시세를 따르고(observed), 그 뒤는 규칙을 따른다(rule).
    시세 구간 안에서 규칙은 거래일인데 시세가 없는 날은 포털 수집 상태로 가린다 —
    ``holiday``(0건이 10일 넘게 이어져 확정)면 휴장(까닭 모름), 그 밖은 아직 못 받은 거래일로 본다.
    """
    states = states or {}
    seen = set(observed)
    last_obs = max(observed) if observed else None
    year_end: Dict[int, date] = {}
    stats = {"observed": 0, "rule": 0, "trading": 0, "closed": 0,
             "rule_closed_but_traded": 0, "rule_open_but_closed": 0, "missing_price": 0}
    days: List[Day] = []
    d = date(FIRST_YEAR, 1, 1)
    one = timedelta(days=1)
    while d <= end:
        ye = year_end.setdefault(d.year, year_end_closure(d.year, holidays))
        reason = rule_reason(d, holidays, ye)
        if last_obs and d <= last_obs:
            if d in seen:
                note = "" if reason is None else f"규칙은 휴장({reason})인데 시세가 있다 — 시세를 따른다"
                if reason is not None:
                    stats["rule_closed_but_traded"] += 1
                day = Day(d, 1, "", "observed", note)
            elif reason is not None:
                day = Day(d, 0, reason, "observed")
            elif states.get(_ymd(d)) == "holiday":
                stats["rule_open_but_closed"] += 1
                day = Day(d, 0, "휴장(까닭 모름)", "observed",
                          "규칙은 거래일인데 포털이 10일 넘게 0건 — 거래소 임시 휴장인지 확인한다")
            else:
                stats["missing_price"] += 1
                day = Day(d, 1, "", "rule", f"시세가 아직 없다(포털 {states.get(_ymd(d)) or '기록 없음'})")
        else:
            day = Day(d, 0 if reason else 1, reason or "", "rule")
        stats[day.basis] += 1
        stats["trading" if day.is_trading_day else "closed"] += 1
        days.append(day)
        d += one
    return days, stats


def write_calendar(conn: sqlite3.Connection, days: Sequence[Day]) -> None:
    at = now_kst().isoformat(timespec="seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM market_calendar")
        conn.executemany(
            "INSERT INTO market_calendar (cal_date, is_trading_day, reason, basis, note, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(x.cal_date.isoformat(), x.is_trading_day, x.reason, x.basis, x.note, at) for x in days])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def trading_days_ymd(conn: sqlite3.Connection) -> List[str]:
    """거래일(YYYYMMDD 오름차순 · 앞날 포함) — ``sources/dart.ex_dividend_date`` 가 읽는 꼴."""
    return [r[0].replace("-", "") for r in conn.execute(
        "SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 ORDER BY cal_date")]


# ==================================================
# 3. 배당락일 다시 계산 — 달력이 바뀌면 배당락일도 바뀐다
# ==================================================
def _note_without_hold(note: str) -> str:
    parts = [p for p in (note or "").split(" / ") if p and not p.startswith(EX_HOLD)]
    return " / ".join(parts)


def rederive_ex_dates(conn: sqlite3.Connection, cal: Sequence[str]) -> List[Tuple[str, str, str, str]]:
    """``dividend.ex_div_dt`` 를 지금 달력으로 다시 계산해 **바뀐 행만** 고친다 → [(종목, 기준일, 옛 값, 새 값)].

    배당락일은 공시에 적힌 값이 아니라 우리가 기준일에서 거래일로 센 값이다(db.py 의 dividend 주석).
    달력이 늘거나(내년 공휴일 발표) 바뀌면(임시공휴일) 같은 기준일의 답이 달라지므로 build 마다 맞춘다.
    TR 이 이 날 배당을 더한다 — 러너는 배당 표의 지문에 배당락일을 넣어 바뀌면 TR 을 다시 만든다.
    """
    changes: List[Tuple[str, str, str, str]] = []
    updates = []
    for code, rec, old, note in conn.execute(
            "SELECT srtn_cd, record_dt, ex_div_dt, note FROM dividend ORDER BY srtn_cd, record_dt"):
        new = dart.ex_dividend_date(cal, rec) or ""
        held = bool(cal) and bool(rec) and rec > cal[-1]
        new_note = _note_without_hold(note)
        if held:   # 배당 단계와 같은 문구(dart.ex_dividend_note) — 두 쪽이 서로의 표시를 알아본다
            new_note = (new_note + " / " if new_note else "") + dart.ex_dividend_note(cal, rec)
        if new != (old or "") or new_note != (note or ""):
            updates.append((new, new_note, code, rec))
            if new != (old or ""):
                changes.append((code, rec, old or "", new))
    if updates:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany("UPDATE dividend SET ex_div_dt = ?, note = ? WHERE srtn_cd = ? AND record_dt = ?",
                             updates)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return changes


# ==================================================
# 4. 일정 — 평일 휴장 · 파생 만기 · 배당
# ==================================================
def second_thursday(year: int, month: int) -> date:
    d = date(year, month, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=7)


def expiry_day(year: int, month: int, trading: Sequence[date]) -> Optional[date]:
    """결제월의 최종거래일 — 두 번째 목요일, 휴장이면 그 앞 거래일(순차적으로 앞당김). 달력 밖이면 None."""
    import bisect

    target = second_thursday(year, month)
    i = bisect.bisect_right(trading, target) - 1
    if i < 0 or trading[i].year != year or trading[i].month != month:
        return None
    return trading[i]


def build_events(conn: sqlite3.Connection, days: Sequence[Day]) -> List[tuple]:
    at = now_kst().isoformat(timespec="seconds")
    ev: List[tuple] = []

    # ① 평일 휴장 — 주말은 일정으로 싣지 않는다(매주 둘이라 목록을 덮는다).
    hol_names = set(public_holidays(conn).values())
    for x in days:
        if x.is_trading_day or x.cal_date.weekday() >= 5:
            continue
        iso = x.cal_date.isoformat()
        src = "kasi" if x.reason in hol_names else "krx_rule"
        conf = "confirmed" if x.basis == "observed" else "scheduled"
        ev.append((f"market_closure:{iso}", "market_closure", iso, "", "KRX", "",
                   f"휴장 — {x.reason}", "", conf, src, "", at))

    # ② 코스피200 선물 · 옵션 만기
    trading = [x.cal_date for x in days if x.is_trading_day]
    if trading:
        y, m = trading[0].year, trading[0].month
        last = trading[-1]
        while (y, m) <= (last.year, last.month):
            exp = expiry_day(y, m, trading)
            if exp:
                iso = exp.isoformat()
                both = m in QUARTER_MONTHS
                thu = second_thursday(y, m)
                moved = "" if exp == thu else f" · 두 번째 목요일 {thu.isoformat()} 이 휴장이라 앞당김"
                ev.append((f"deriv_expiry:{iso}", "deriv_expiry", iso, "15:20", "KRX", "",
                           "코스피200 선물 · 옵션 동시 만기" if both else "코스피200 옵션 만기",
                           "최종거래일 — 각 결제월의 두 번째 목요일(휴장이면 앞당김)" + moved,
                           "computed", "krx_rule", "", at))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    # ③ 배당 기준일 · 배당락일 — 배당 표(DART 공시) 한 행이 일정 둘
    for code, nm, rec, ex, dps, kind, rcept, review in conn.execute(
            "SELECT srtn_cd, itms_nm, record_dt, ex_div_dt, dps, div_kind, rcept_no, needs_review "
            "FROM dividend ORDER BY record_dt, srtn_cd"):
        name = nm or code
        amount = f"1주당 {dps:,.0f}원" if dps else "금액 확인 필요"
        kind_txt = f"{kind} · " if kind else ""
        flag = " · 공시 본문 확인 필요" if review else ""
        rec_iso = _from_ymd(rec).isoformat()
        ev.append((f"dividend_record:{rec_iso}:{code}", "dividend_record", rec_iso, "", "", code,
                   f"{name} 배당 기준일", f"{kind_txt}{amount}{flag}", "confirmed", "dividend", rcept, at))
        if ex:
            ex_iso = _from_ymd(ex).isoformat()
            ev.append((f"dividend_ex:{rec_iso}:{code}", "dividend_ex", ex_iso, "", "", code,
                       f"{name} 배당락일", f"이날부터 사면 이번 배당({amount})을 받지 못한다 · 기준일 {rec_iso}",
                       "computed", "dividend", rcept, at))
    return ev


def write_events(conn: sqlite3.Connection, events: Sequence[tuple]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM market_event")
        conn.executemany(
            "INSERT OR REPLACE INTO market_event (event_id, kind, event_date, event_time, market, symbol, "
            "title, detail, confidence, source, source_ref, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            events)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ==================================================
# 5. 명령
# ==================================================
def build(conn: sqlite3.Connection, *, fetch: bool = True, today: Optional[date] = None,
          fetcher: Callable[[int], List[Dict[str, object]]] = fetch_kasi_year,
          quiet: bool = False) -> Dict[str, object]:
    """공휴일 받기 → 달력 → 배당락일 다시 계산 → 일정. 결과 요약을 돌려준다(``fetch_error`` 가 있으면 옛 공휴일로 만든 것)."""
    ensure_schema(conn)
    today = today or now_kst().date()
    say = (lambda *a: None) if quiet else print
    out: Dict[str, object] = {"fetched": {}, "fetch_error": ""}
    if fetch:
        try:
            out["fetched"] = refresh_holidays(conn, years_to_fetch(conn, today), fetch=fetcher)
        except KasiError as e:
            out["fetch_error"] = str(e)
            print(f"  ⚠️ {e} — 어제까지 받은 공휴일로 만든다")
    years = holiday_years(conn)
    end = calendar_end(years)
    if end is None:
        raise CalendarError(f"{FIRST_YEAR}년 공휴일이 없다 — 특일 정보를 먼저 받는다(--no-fetch 를 뺀다)")
    hol = public_holidays(conn)
    days, stats = build_days(hol, end, observed_days(conn), portal_states(conn))
    write_calendar(conn, days)
    changes = rederive_ex_dates(conn, trading_days_ymd(conn))
    events = build_events(conn, days)
    write_events(conn, events)
    out.update(stats=stats, end=end.isoformat(), days=len(days), ex_changes=changes, events=len(events),
               holiday_years=years)
    say(f"― 거래일 달력 {FIRST_YEAR}-01-01 ~ {end.isoformat()} · {len(days):,}일 "
        f"(거래일 {stats['trading']:,} · 휴장 {stats['closed']:,}) ―")
    say(f"  시세로 확인 {stats['observed']:,}일 · 규칙으로 예정 {stats['rule']:,}일 · "
        f"공휴일 받은 해 {', '.join(map(str, years))}")
    if out["fetched"]:
        say("  특일 정보 " + " · ".join(f"{y} {n}건" for y, n in out["fetched"].items()))
    bad = stats["rule_closed_but_traded"] + stats["rule_open_but_closed"]
    if bad:
        print(f"  ⚠️ 규칙과 시세가 어긋난 날 {bad}일 — `status` 의 어긋난 날을 본다")
    if stats["missing_price"]:
        say(f"  · 시세 구간 안에 아직 시세가 없는 거래일 {stats['missing_price']}일")
    if changes:
        print(f"  배당락일 바뀜 {len(changes)}행 — TR 을 다시 만든다")
        for code, rec, old, new in changes[:10]:
            print(f"    {code} 기준일 {rec}: {old or '(없음)'} → {new or '(보류)'}")
    say(f"  일정 {len(events):,}건")
    return out


def cmd_status(conn: sqlite3.Connection, today: Optional[date] = None) -> int:
    ensure_schema(conn)
    today = today or now_kst().date()
    r = conn.execute("SELECT MIN(cal_date), MAX(cal_date), COUNT(*), SUM(is_trading_day), MAX(updated_at) "
                     "FROM market_calendar").fetchone()
    if not r or not r[2]:
        print("― 거래일 달력 ― 아직 없다. `python -m collector.market_calendar build`")
        return 1
    print(f"― 거래일 달력 {r[0]} ~ {r[1]} · {r[2]:,}일 · 거래일 {r[3]:,} · 만든 시각 {r[4]} ―")
    fetched = conn.execute("SELECT substr(locdate,1,4), COUNT(*), MAX(fetched_at) FROM holiday_kasi "
                           "GROUP BY 1 ORDER BY 1").fetchall()
    print("  공휴일(특일 정보) " + " · ".join(f"{y} {n}건" for y, n, _ in fetched)
          + (f" · 마지막으로 받은 시각 {max(f for _, _, f in fetched)}" if fetched else ""))
    odd = conn.execute("SELECT cal_date, is_trading_day, note FROM market_calendar WHERE note <> '' "
                       "ORDER BY cal_date").fetchall()
    print(f"  어긋나거나 시세가 아직 없는 날 {len(odd)}일" + (":" if odd else ""))
    for d, t, note in odd[-10:]:
        print(f"    {d} {'거래일' if t else '휴장'} — {note}")
    iso = today.isoformat()
    print("\n― 다가오는 평일 휴장 · 만기 (60일) ―")
    for d, kind, title, conf in conn.execute(
            "SELECT event_date, kind, title, confidence FROM market_event "
            "WHERE kind IN ('market_closure', 'deriv_expiry') AND event_date >= ? AND event_date <= ? "
            "ORDER BY event_date", (iso, (today + timedelta(days=60)).isoformat())):
        print(f"  {d}  {title}  ({conf})")
    n = conn.execute("SELECT COUNT(*) FROM market_event WHERE kind LIKE 'dividend%' AND event_date >= ?",
                     (iso,)).fetchone()[0]
    print(f"\n  앞으로의 배당 일정 {n}건 · 일정 전체 "
          f"{conn.execute('SELECT COUNT(*) FROM market_event').fetchone()[0]:,}건")
    return 0


def cmd_show(conn: sqlite3.Connection, start: str, end: str) -> int:
    rows = conn.execute("SELECT cal_date, is_trading_day, reason, basis, note FROM market_calendar "
                        "WHERE cal_date BETWEEN ? AND ? ORDER BY cal_date", (start, end)).fetchall()
    if not rows:
        print("그 구간의 달력이 없다 — build 를 먼저 돌린다")
        return 1
    names = "월화수목금토일"
    for d, t, reason, basis, note in rows:
        wd = names[date.fromisoformat(d).weekday()]
        mark = "거래일" if t else f"휴장 · {reason}"
        print(f"  {d}({wd})  {mark:<22} {'시세로 확인' if basis == 'observed' else '예정'}"
              + (f"  — {note}" if note else ""))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="python -m collector.market_calendar",
                                 description="거래일 달력 · 금융 일정 (특일 정보 + 거래소 규칙 + 시세로 확인)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="공휴일 받기 → 달력 → 배당락일 다시 계산 → 일정")
    p.add_argument("--no-fetch", action="store_true", help="특일 정보를 받지 않고 이미 받은 공휴일로만")
    p.add_argument("--quiet", action="store_true")
    sub.add_parser("status", help="달력 범위 · 어긋난 날 · 다가오는 휴장 · 만기")
    p = sub.add_parser("show", help="구간의 하루하루")
    p.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    a = ap.parse_args(argv)

    conn = db.connect()
    try:
        if a.cmd == "build":
            try:
                res = build(conn, fetch=not a.no_fetch, quiet=a.quiet)
            except (CalendarError, config.MissingKey) as e:
                print(f"🔴 {e}")
                return 1
            # 공휴일을 못 받았어도 달력은 어제 것으로 만들었다 — 러너에 🟡 로 보이게 3 을 돌려준다.
            return 3 if res["fetch_error"] else 0
        if a.cmd == "status":
            return cmd_status(conn)
        return cmd_show(conn, a.start, a.end)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
