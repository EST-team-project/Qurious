"""금융 일정 더하기 — 실적 · 정기보고서 법정 기한 · 금통위 · FOMC (목표 기능 ① W7 · 설계서 5.2.4 <표 15>).

`collector/market_calendar.py` 의 `build_events` 가 이 파일의 `extra_events` 를 부른다(달력 파일에는 부르는 몇 줄만 둔다).

일정 종류 넷
------------
==================  ==============================================  =========  ===================
종류(kind)           출처 · 규칙                                       확실도       날짜
==================  ==============================================  =========  ===================
earnings            공시 목록의 「영업(잠정)실적(공정공시)」 · 「매출액또는손익구조…변동」   confirmed   공시 접수일(발표한 날)
report_deadline     자본시장법 제159조①(사업보고서 · 사업연도 경과 후 90일 이내) ·
                    제160조①(반기 · 분기 · 그 기간 경과 후 45일 이내) — 12월 결산 기준    computed    말일이 토요일 · 공휴일이면
                                                                                       다음 날(민법 제161조)
policy_rate         한국은행 「통화정책방향 결정회의 일정」(공식 누리집)                  confirmed ·  회의일(KST)
                                                                     scheduled
fomc                연준 「Meeting calendars and information」(공식 누리집)            confirmed ·  회의 둘째 날(미국 동부)
                                                                     scheduled
==================  ==============================================  =========  ===================

금통위 · FOMC 일정은 「받은 것」 이라 표 `policy_meeting` 에 두고(`refresh_policy_meetings` · 7일에 한 번만 다시 받는다),
`market_event` 는 늘 그 표에서 다시 만든다(계산한 표 — 지워도 `market_calendar build` 가 되살린다).
연준 누리집은 「Each meeting date is tentative until confirmed at the meeting immediately preceding it」 이라 앞날은 예정이다.

주주총회 날짜는 공시 목록에 없다(「주주총회소집결의」 본문의 일시 칸) — 본문 받기는 다음 판에서 한다.
"""

from __future__ import annotations

import argparse
import html
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from collector import db
from collector.console import utf8_stdio

BOK_URL = "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?mtgSe=A&menuNo=200755&pYear={year}"
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Qurious-collector/1.0 (student project)"

#: 금통위 일정을 받기 시작하는 해 — 시세 · 공시와 같은 2020년.
FIRST_YEAR = 2020

#: 공식 일정은 자주 바뀌지 않는다 — 이 날 수가 지나야 다시 받는다(누리집에 부담을 주지 않게).
REFRESH_DAYS = 7


_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"), 1)}
_MON3 = {k[:3]: v for k, v in _MONTHS.items()}


def _now() -> datetime:
    return datetime.now().astimezone()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """표 정의는 수집 DB 스키마 한 곳(`collector/db.py` 16절)에 있다 — 옛 DB 를 열 때도 보장한다."""
    conn.executescript(db.POLICY_MEETING_DDL)


# ==================================================
# 1. 공식 누리집 읽기 — 네트워크 없이 시험한다(TC-EV)
# ==================================================
def _text(page: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</h\d>|</tr>|</td>|</th>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    return "\n".join(x.strip() for x in t.splitlines() if x.strip())


def parse_bok(page: str) -> Tuple[Optional[int], List[date]]:
    """한국은행 「통화정책방향 결정회의 일정」 한 해 → (연도, 회의일들). 그해가 아직 없으면 빈 목록."""
    m = re.search(r'<div class="h-group">\s*<h3>\s*(\d{4})\s*년\s*</h3>', page)
    year = int(m.group(1)) if m else None
    if year is None:
        return None, []
    days = []
    for mm, dd in re.findall(r"(\d{2})월\s*(\d{2})일\s*\([월화수목금토일]\)", _text(page)):
        try:
            d = date(year, int(mm), int(dd))
        except ValueError:
            continue
        if d not in days:
            days.append(d)
    return year, sorted(days)


def parse_fomc(page: str) -> List[Tuple[date, bool]]:
    """연준 「Meeting calendars」 → [(회의 둘째 날, 경제전망 회의인가)]. 달을 넘는 회의(「Apr/May 30-1」)도 읽는다."""
    t = _text(page)
    out: List[Tuple[date, bool]] = []
    blocks = re.split(r"\n(?=(\d{4}) FOMC Meetings\n)", "\n" + t)
    year = None
    for part in blocks:
        if re.fullmatch(r"\d{4}", part.strip() or "x"):
            year = int(part)
            continue
        if year is None:
            continue
        lines = part.splitlines()
        for i, line in enumerate(lines[:-1]):
            mon = line.strip().lower()
            mons = [x.strip()[:3] for x in mon.split("/")]
            if not all(x in _MON3 for x in mons) or not mons:
                continue
            nxt = lines[i + 1].strip()
            dm = re.fullmatch(r"(\d{1,2})-(\d{1,2})(\*?)(?:\s*\(.*\))?", nxt)
            if not dm:
                continue
            end_day, sep = int(dm.group(2)), bool(dm.group(3))
            end_mon = _MON3[mons[-1]]
            try:
                out.append((date(year, end_mon, end_day), sep))
            except ValueError:
                continue
        year = None
    return sorted(set(out))


def _get(url: str, opener: Callable = urllib.request.urlopen, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def refresh_policy_meetings(conn: sqlite3.Connection, today: date, *, force: bool = False,
                            fetch: Callable[[str], str] = _get, quiet: bool = True) -> Dict[str, int]:
    """금통위(올해 · 내년) · FOMC 일정을 받아 `policy_meeting` 에 넣는다. 마지막으로 받은 지 7일 안이면 건너뛴다.

    한 출처가 실패해도 다른 출처는 넣는다 — 실패는 돌려주는 값의 `errors` 로 알린다(달력 단계를 멈추지 않는다).
    그해 일정이 비어 오면(아직 발표 전) 있던 행을 지우지 않는다.
    """
    ensure_schema(conn)
    last = conn.execute("SELECT MAX(fetched_at) FROM policy_meeting").fetchone()[0]
    if not force and last and (_now() - datetime.fromisoformat(last)).days < REFRESH_DAYS:
        return {"skipped": 1}
    at = _now().isoformat(timespec="seconds")
    out: Dict[str, int] = {"bok": 0, "fomc": 0, "errors": 0}
    rows: List[tuple] = []
    # 금통위 — 지난 해는 한 번 받으면 바뀌지 않으므로 아직 없는 해만, 올해 · 내년은 늘 다시(연준 누리집은 2021 년부터 한 쪽에 준다)
    have = {int(r[0][:4]) for r in conn.execute("SELECT meeting_date FROM policy_meeting WHERE org='bok'")}
    years = [y for y in range(FIRST_YEAR, today.year + 2) if y >= today.year or y not in have]
    for i, y in enumerate(years):
        if i:
            time.sleep(1.1)                  # 공식 누리집 — 1초에 한 번보다 느리게
        url = BOK_URL.format(year=y)
        try:
            got_year, days = parse_bok(fetch(url))
        except Exception as e:  # noqa: BLE001 — 한 출처 실패가 달력을 멈추지 않게
            out["errors"] += 1
            if not quiet:
                print(f"  🟡 한국은행 {y} 일정을 받지 못했다: {e}")
            continue
        if got_year != y:
            continue
        for d in days:
            rows.append(("bok", d.isoformat(), "금통위 통화정책방향 결정회의(기준금리 결정)", "한국은행 금융통화위원회",
                         url, at))
    try:
        for d, sep in parse_fomc(fetch(FOMC_URL)):
            rows.append(("fomc", d.isoformat(), "미국 FOMC 회의 결과 발표(연방기금금리)",
                         "미국 동부 오후 2시 발표 — 한국 다음 날 새벽 3~4시" + (" · 경제전망(SEP) 함께" if sep else ""),
                         FOMC_URL, at))
    except Exception as e:  # noqa: BLE001
        out["errors"] += 1
        if not quiet:
            print(f"  🟡 FOMC 일정을 받지 못했다: {e}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany("INSERT INTO policy_meeting (org, meeting_date, title, detail, source_url, fetched_at) "
                         "VALUES (?,?,?,?,?,?) ON CONFLICT(org, meeting_date) DO UPDATE SET title=excluded.title, "
                         "detail=excluded.detail, source_url=excluded.source_url, fetched_at=excluded.fetched_at", rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    for r in rows:
        out[r[0]] += 1
    return out


# ==================================================
# 2. 일정 만들기
# ==================================================
_EARNINGS = re.compile(r"잠정\)?실적|매출액또는손익구조")


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def earnings_events(conn: sqlite3.Connection, at: str) -> List[tuple]:
    """잠정실적 · 손익구조 변동 공시 → 그날의 실적 발표 일정. 같은 종목 · 같은 날은 하나(정정 공시는 원 공시와 함께 한 줄)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='disclosure'").fetchone():
        return []
    seen: Dict[Tuple[str, str], tuple] = {}
    for rcept_no, rcept_dt, code, name, title, revision in conn.execute(
            "SELECT rcept_no, rcept_dt, stock_code, corp_name, title, revision FROM disclosure "
            "WHERE stock_code <> '' AND (title LIKE '%잠정%실적%' OR title LIKE '%매출액또는손익구조%') "
            "ORDER BY rcept_dt, rcept_no"):
        if not _EARNINGS.search(title or ""):
            continue
        if "정정" in (revision or ""):
            continue                      # 정정 공시는 새 발표가 아니다 — 원 공시의 날이 발표일
        key = (code, rcept_dt)
        if key in seen:
            continue
        what = "잠정실적" if "잠정" in title else "손익구조 변동(30% · 대규모법인 15% 이상)"
        detail = f"{title}" + (f" · {revision}" if revision else "")  # 첨부추가 등은 그대로 적는다
        seen[key] = (f"earnings:{_iso(rcept_dt)}:{code}", "earnings", _iso(rcept_dt), "", "", code,
                     f"{name} {what} 발표", detail, "confirmed", "dart", rcept_no, at)
    return list(seen.values())


def legal_deadline(d: date, holidays: Iterable[date]) -> date:
    """기간의 말일이 토요일 · 일요일 · 공휴일이면 다음 날로(민법 제161조)."""
    hol = set(holidays)
    while d.weekday() >= 5 or d in hol:
        d += timedelta(days=1)
    return d


def report_deadlines(years: Sequence[int], holidays: Iterable[date], at: str) -> List[tuple]:
    """12월 결산 법인의 정기보고서 법정 제출 기한(자본시장법 제159조① 90일 · 제160조① 45일)."""
    hol = list(holidays)
    ev = []
    for y in years:
        for label, period_end, days in (("사업보고서", date(y - 1, 12, 31), 90), ("1분기보고서", date(y, 3, 31), 45),
                                        ("반기보고서", date(y, 6, 30), 45), ("3분기보고서", date(y, 9, 30), 45)):
            raw = period_end + timedelta(days=days)
            due = legal_deadline(raw, hol)
            moved = "" if due == raw else f" · {raw.isoformat()} 이 휴일이라 다음 날로(민법 제161조)"
            law = "자본시장법 제159조①" if days == 90 else "자본시장법 제160조①"
            ev.append((f"report_deadline:{due.isoformat()}:{label}", "report_deadline", due.isoformat(), "", "KRX", "",
                       f"{label} 제출 기한(12월 결산)", f"{law} — 기간 경과 후 {days}일 이내{moved}",
                       "computed", "law", law, at))
    return ev


def policy_events(conn: sqlite3.Connection, today: date, at: str) -> List[tuple]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_meeting'").fetchone():
        return []
    ev = []
    for org, d, title, detail, url in conn.execute(
            "SELECT org, meeting_date, title, detail, source_url FROM policy_meeting ORDER BY meeting_date"):
        kind = "policy_rate" if org == "bok" else "fomc"
        conf = "confirmed" if d < today.isoformat() else "scheduled"
        ev.append((f"{kind}:{d}", kind, d, "", "BOK" if org == "bok" else "FOMC", "", title, detail, conf,
                   org, url, at))
    return ev


def extra_events(conn: sqlite3.Connection, holidays: Iterable[date], years: Sequence[int], today: date,
                 at: str) -> List[tuple]:
    """달력이 부르는 한 곳 — 실적 · 법정 기한 · 금통위 · FOMC."""
    return earnings_events(conn, at) + report_deadlines(years, holidays, at) + policy_events(conn, today, at)


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.event_sources",
                                description="금통위 · FOMC 공식 일정 받기(달력 build 가 7일에 한 번 부른다)")
    p.add_argument("mode", choices=["fetch", "show"])
    p.add_argument("--force", action="store_true", help="7일 안이어도 다시 받는다")
    a = p.parse_args(argv)
    conn = db.connect()
    ensure_schema(conn)
    if a.mode == "fetch":
        print(refresh_policy_meetings(conn, date.today(), force=a.force, quiet=False))
    for r in conn.execute("SELECT org, meeting_date, title, detail FROM policy_meeting ORDER BY meeting_date"):
        print(f"  {r[1]} {r[0]:4} {r[2]} · {r[3]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
