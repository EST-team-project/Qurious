"""경제지표 발표 일정 — 국가데이터처 보도계획 · 미국 BLS · BEA 공식 일정 (할 일 ①-23 E · 2026-11-03 S195).

`collector/market_calendar.py` 의 `build` 가 `refresh_econ_releases` 를 부르고(7일에 한 번 · 출처마다 따로),
`collector/event_sources.py` 의 `extra_events` 가 `econ_events` 로 `market_event` 줄을 만든다(금통위 · FOMC 와 같은 꼴).

출처 셋 (사용자 결정 2026-11-03 — 한국은행 공표일정은 넣지 않는다 · 한국은행 저작권보호방침 ③)
---------------------------------------------------------------------------------------------
=======  ==================================================  =====================  ==================
source   받는 곳                                              형식                   날짜 · 시각
=======  ==================================================  =====================  ==================
kostat   국가데이터처 「보도계획」(oa_mm=ALL — 그해 전체)            HTML 표(POST)           KST 그대로
bls      미국 노동통계국 「Economic News Release Schedule」         ICS(TZID=US-Eastern)   미국 동부 벽시계 그대로
bea      미국 경제분석국 「Release Schedule」 구독 달력              ICS(UTC · …Z)          미국 동부로 바꿔 씀
=======  ==================================================  =====================  ==================

지키는 것
--------
- **미국 발표는 미국 날짜 · 동부 시각(ET) 그대로 둔다** — 한국 날짜로 바꾸지 않는다(FOMC 선례 · 잠정 결정). 그래서 달력의
  `event_time` 은 비우고(그날 목록이 시각을 한국 시각으로 읽히게 보이지 않게) 「미국 동부 시각 08:30 발표」 를 설명에 쓴다.
- 날짜를 못 읽으면 그 행을 만들지 않는다 — 규칙으로 계산해 채우지 않는다. 국가데이터처 표는 칸에 연도가 없어 머리(h3)의
  「2026년」 을 쓰고, 칸의 요일과 계산한 요일이 다르면 그 행을 버린다(연도 오판을 잡는다).
- 국가데이터처 보도계획에는 통계 발표가 아닌 행(포상 전수식 · 협력회의 「개최」 · 기관 보도)도 섞여 있다 — **제목이 기준 연도
  (「2026년 …」 · 「2025 …」)로 시작하고 행사 · 포상 · 홍보 · 조사 「실시」 낱말(`_KOSTAT_DROP`)이 없는 행만** 경제지표로 남긴다
  (뺀 행 수는 돌려주는 값의 `dropped`). 「장래인구추계」 처럼 연도로 시작하지 않는 통계 보고서도 빠진다 — 놓치는 쪽을 고른다.
- 한 출처가 실패해도 다른 출처는 넣고, 달력 단계를 멈추지 않는다(돌려주는 값의 `errors`).
- 한 출처가 **성공했고 비어 있지 않으면** 그 출처의 「받은 날 이후」 행을 이번 결과로 바꾼다 — 옮겨진 발표의 옛 날짜가
  앞날에 남지 않게. 지난 행은 그대로 둔다(이미 지난 발표). 빈 응답이면 아무것도 지우지 않는다.
- 같은 (출처 · 날짜 · 이름)은 한 행 — 다시 받아도 늘지 않는다(멱등).

이용 조건(2026-11-03 확인)
-------------------------
- BLS · BEA — 공공 도메인(출처 표시 요청). 화면 설명에 기관 이름을 적는다.
- 국가데이터처 — 저작권정책은 공공누리 표시 자료를 자유 이용으로 두는데, **보도계획 쪽 HTML 에는 공공누리 표시가 없었다**
  (2026-11-03 HTML 글자 검색 0건). 날짜 · 이름만 다시 적고 원문 HTML 은 남기지 않는다(raw_response 에 넣지 않음 —
  크롤링 원문 보관 금지 규칙 · `collector/raw_store.py`).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from collector import db
from collector.console import utf8_stdio

KOSTAT_URL = "https://mods.go.kr/newsPln.es?mid=a10305000000&bid="
#: 그해 전체 보도계획 — 누리집의 월 고르기 「전체」(oa_mm=ALL) 를 그대로 보낸다(2026-11-03 실측 277행).
KOSTAT_FORM = {"oa_mm": "ALL", "mid": "a10305000000", "bid": "", "act": "list"}
BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
#: BLS 는 브라우저 흉내 UA(Mozilla…)에 403 을 준다 — 자기를 밝히는 UA + Accept 머리가 있어야 200(2026-11-03 실측: 같은 UA 라도
#: Accept 없이 부르면 403 · 있으면 200). 세 곳 모두 이 UA 로 부르고, Accept 는 달력(.ics)이면 text/calendar 를 앞에 둔다.
UA = "Qurious-collector/1.0 (student project; schedule reader; one request per week)"
ACCEPT_ICS = "text/calendar,*/*"
ACCEPT_HTML = "text/html,*/*"

SOURCES = ("kostat", "bls", "bea")
#: 출처 → (달력 종류, 시장 칸, 이름표)
SOURCE_INFO = {
    "kostat": ("econ_kr", "KOSTAT", "국가데이터처"),
    "bls": ("econ_us", "BLS", "미국 노동통계국(BLS)"),
    "bea": ("econ_us", "BEA", "미국 경제분석국(BEA)"),
}

#: 공식 일정은 자주 바뀌지 않는다 — 이 날 수가 지나야 그 출처를 다시 받는다(금통위 · FOMC 와 같다).
REFRESH_DAYS = 7

#: 앞날 일정이 이만큼 이상 있는데 새 응답의 앞날 행이 그 절반 아래면 일부만 온 응답으로 보고 바꾸지 않는다(코드 검수 · 2026-11-03).
PARTIAL_GUARD_MIN = 10

_KOSTAT_KEEP = re.compile(r"^\s*20\d{2}(?:년|\s)")
#: 기준 연도로 시작해도 통계 발표가 아닌 행 — 행사 · 포상 · 홍보 · 조사 「실시」 안내(2026 보도계획 277행을 눈으로 보고 정함)
_KOSTAT_DROP = re.compile(r"개최|포상|위촉|모집|시구|현판|연수|활용대회|업무협약|MOU|실시\s*$")
_WEEKDAY = "월화수목금토일"


def _now() -> datetime:
    return datetime.now().astimezone()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """표 정의는 수집 DB 스키마 한 곳(`collector/db.py` 24절)에 있다 — 옛 DB 를 열 때도 보장한다."""
    conn.executescript(db.ECON_RELEASE_DDL)


# ==================================================
# 1. 읽기 — 네트워크 없이 시험한다(TC-EV)
# ==================================================
def _cell(s: str) -> str:
    t = re.sub(r"<[^>]+>", " ", s)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def parse_kostat(page: str) -> Tuple[Optional[int], List[Tuple[date, str, str, str]], List[str]]:
    """국가데이터처 보도계획 → (연도, [(날짜, 시각 HH:MM, 보도자료명, 담당과)], 뺀 제목들).

    연도는 머리 「<h3>2026년 전체 보도계획</h3>」(월을 고르면 「2026년 11월 보도계획」)에서만 읽는다 — 없으면 (None, [], []).
    칸의 날짜는 「11.03.( 화 )」 꼴이다. 괄호 안 요일이 계산한 요일과 다르면 그 행은 버린다(뺀 제목에 「요일 다름」 으로).
    """
    m = re.search(r"<h3>\s*(\d{4})\s*년[^<]*보도계획\s*</h3>", page)
    if not m:
        return None, [], []
    year = int(m.group(1))
    rows: List[Tuple[date, str, str, str]] = []
    dropped: List[str] = []
    seen = set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        tds = [_cell(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(tds) < 3:
            continue
        dm = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?\s*\(\s*([월화수목금토일])\s*\)", tds[0])
        if not dm:
            continue
        title = tds[2]
        try:
            d = date(year, int(dm.group(1)), int(dm.group(2)))
        except ValueError:
            dropped.append(f"날짜 못 읽음: {tds[0]} {title}")
            continue
        if _WEEKDAY[d.weekday()] != dm.group(3):
            dropped.append(f"요일 다름: {tds[0]} {title}")
            continue
        if not _KOSTAT_KEEP.match(title) or _KOSTAT_DROP.search(title):
            dropped.append(title)
            continue
        tm = re.fullmatch(r"(\d{1,2}):(\d{2})", tds[1] or "")
        clock = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm and int(tm.group(1)) < 24 else ""
        key = (d, title)
        if key in seen:
            continue
        seen.add(key)
        rows.append((d, clock, title, tds[3] if len(tds) > 3 else ""))
    return year, sorted(rows), dropped


def _unfold(text: str) -> List[str]:
    """ICS 줄 접기 풀기(RFC 5545 3.1 — 공백 · 탭으로 시작하는 줄은 앞 줄에 이어 붙인다)."""
    out: List[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _ics_text(v: str) -> str:
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def parse_ics(text: str) -> List[Tuple[date, str, str]]:
    """ICS 달력 → [(미국 동부 날짜, 동부 시각 HH:MM 또는 빈칸, 이름)].

    DTSTART 셋 꼴만 읽는다 —
      `DTSTART;TZID=…:20261218T100000` → 그 벽시계 그대로(BLS 는 TZID=US-Eastern — IANA 이름이 아니라 시간대를 찾지 않는다)
      `DTSTART…:20270101T013000Z`      → UTC 를 America/New_York 으로 바꾼다(BEA — 이 예는 2026-12-31 20:30)
      `DTSTART;VALUE=DATE:20261218`    → 날짜만(시각 빈칸)
    VTIMEZONE 안의 DTSTART(시간대 규칙의 시작)는 읽지 않는다. 날짜를 못 읽은 VEVENT 는 버린다.
    """
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    out = set()
    ev: Optional[Dict[str, str]] = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            ev = {}
            continue
        if line == "END:VEVENT":
            if ev is not None:
                got = _ics_event(ev, eastern)
                if got:
                    out.add(got)
            ev = None
            continue
        if ev is None or ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.split(";", 1)[0].upper()
        if key in ("DTSTART", "SUMMARY") and key not in ev:
            ev[key] = value
            if key == "DTSTART":
                ev["DTSTART_PARAMS"] = name
    return sorted(out)


def _ics_event(ev: Dict[str, str], eastern) -> Optional[Tuple[date, str, str]]:
    raw = (ev.get("DTSTART") or "").strip()
    title = _ics_text(ev.get("SUMMARY") or "")
    if not raw or not title:
        return None
    try:
        if re.fullmatch(r"\d{8}T\d{6}Z", raw):
            utc = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            local = utc.astimezone(eastern)
            return local.date(), local.strftime("%H:%M"), title
        if re.fullmatch(r"\d{8}T\d{6}", raw):
            local = datetime.strptime(raw, "%Y%m%dT%H%M%S")
            return local.date(), local.strftime("%H:%M"), title
        if re.fullmatch(r"\d{8}", raw):
            return datetime.strptime(raw, "%Y%m%d").date(), "", title
    except ValueError:
        return None
    return None


# ==================================================
# 2. 받기 — 7일에 한 번 · 출처마다 따로
# ==================================================
def _get(url: str, data: Optional[bytes] = None, opener: Callable = urllib.request.urlopen, timeout: int = 30) -> str:
    accept = ACCEPT_ICS if url.split("?", 1)[0].endswith(".ics") else ACCEPT_HTML
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": accept})
    with opener(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _fetch_source(source: str, fetch: Callable[..., str]) -> Tuple[str, List[Tuple[str, str, str, str]], Dict[str, object]]:
    """한 출처 → (받은 주소, [(날짜, 시각, 이름, 담당)], 덧붙일 정보). 실패는 예외로 올린다."""
    if source == "kostat":
        page = fetch(KOSTAT_URL, urllib.parse.urlencode(KOSTAT_FORM).encode())
        year, rows, dropped = parse_kostat(page)
        if year is None:
            raise ValueError("국가데이터처 보도계획의 연도 머리를 찾지 못했다 — 누리집 모양이 바뀌었는지 본다")
        return KOSTAT_URL, [(d.isoformat(), t, title, dept) for d, t, title, dept in rows], \
            {"year": year, "dropped": len(dropped), "dropped_titles": dropped}
    url = BLS_URL if source == "bls" else BEA_URL
    return url, [(d.isoformat(), t, title, "") for d, t, title in parse_ics(fetch(url))], {}


def refresh_econ_releases(conn: sqlite3.Connection, today: date, *, force: bool = False,
                          fetch: Callable[..., str] = _get, quiet: bool = True,
                          sources: Sequence[str] = SOURCES,
                          sleep: Callable[[float], None] = time.sleep) -> Dict[str, object]:
    """세 출처의 발표 일정을 받아 `econ_release` 에 넣는다 — 출처마다 마지막으로 받은 지 7일 안이면 그 출처는 건너뛴다.

    돌려주는 값: 출처마다 넣은 행 수(건너뛰면 `skipped`) · `errors`(실패한 출처 수) · `dropped`(국가데이터처에서 뺀 행 수).
    한 출처의 실패가 다른 출처나 달력 단계를 멈추지 않는다.
    """
    ensure_schema(conn)
    out: Dict[str, object] = {"errors": 0}
    first = True
    for source in sources:
        last = conn.execute("SELECT MAX(fetched_at) FROM econ_release WHERE source=?", (source,)).fetchone()[0]
        if not force and last and (_now() - datetime.fromisoformat(last)).days < REFRESH_DAYS:
            out[source] = "skipped"
            continue
        if not first:
            sleep(1.1)                       # 공식 누리집 — 1초에 한 번보다 느리게
        first = False
        try:
            url, rows, extra = _fetch_source(source, fetch)
        except Exception as e:  # noqa: BLE001 — 한 출처 실패가 달력을 멈추지 않게
            out["errors"] = int(out["errors"]) + 1
            out[source] = "error"
            if not quiet:
                print(f"  🟡 {SOURCE_INFO[source][2]} 일정을 받지 못했다: {type(e).__name__}: {str(e)[:160]}")
            continue
        if "dropped" in extra:
            out["dropped"] = extra["dropped"]
        if not rows:
            out[source] = 0                  # 빈 응답 — 있던 행을 지우지 않는다
            continue
        old_future = conn.execute("SELECT COUNT(*) FROM econ_release WHERE source=? AND release_date >= ?",
                                  (source, today.isoformat())).fetchone()[0]
        new_future = sum(1 for d, _t, _title, _dept in rows if d >= today.isoformat())
        if old_future >= PARTIAL_GUARD_MIN and new_future * 2 < old_future:
            out[source] = "partial"          # 일부만 온 응답(월 한 쪽 · 잘린 달력)이 앞날 일정을 지우지 않게 — 다음 회차에 다시 받는다
            out["errors"] = int(out["errors"]) + 1
            if not quiet:
                print(f"  🟡 {SOURCE_INFO[source][2]} 일정이 앞날 {old_future}건에서 {new_future}건으로 줄어 바꾸지 않았다")
            continue
        out[source] = _replace_future(conn, source, rows, url, today)
    return out


def _replace_future(conn: sqlite3.Connection, source: str, rows: Sequence[Tuple[str, str, str, str]], url: str,
                    today: date) -> int:
    """그 출처의 받은 날 이후 행을 이번 결과로 바꾸고(옮겨진 발표의 옛 날짜를 지운다) · 이번 결과를 넣는다(같은 키는 고친다)."""
    at = _now().isoformat(timespec="seconds")
    tz = "KST" if source == "kostat" else "ET"
    uniq = {(d, title): (d, t, dept) for d, t, title, dept in rows}
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM econ_release WHERE source=? AND release_date >= ?", (source, today.isoformat()))
        conn.executemany(
            "INSERT INTO econ_release (source, release_date, title, release_time, tz, detail, source_url, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source, release_date, title) DO UPDATE SET "
            "release_time=excluded.release_time, tz=excluded.tz, detail=excluded.detail, "
            "source_url=excluded.source_url, fetched_at=excluded.fetched_at",
            [(source, d, title, t, tz, dept, url, at) for (d, title), (_d, t, dept) in uniq.items()])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(uniq)


# ==================================================
# 3. 달력 일정 — `event_sources.extra_events` 가 부른다
# ==================================================
def _short(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]


def econ_events(conn: sqlite3.Connection, today: date, at: str) -> List[tuple]:
    """`econ_release` → `market_event` 줄(econ_kr · econ_us).

    확실도는 금통위 · FOMC 와 같은 규칙 — 지난 날 confirmed · 오늘부터 scheduled(공표 일정이 계획대로 열렸는지는 확인하지 않는다).
    같은 날 발표가 여럿이라 일정 번호에 이름 지문을 붙인다(날짜만 쓰면 같은 날 일정끼리 서로 덮는다).
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='econ_release'").fetchone():
        return []
    ev = []
    iso_today = today.isoformat()
    for source, d, title, t, tz, detail, url in conn.execute(
            "SELECT source, release_date, title, release_time, tz, detail, source_url FROM econ_release "
            "ORDER BY release_date, source, title"):
        if source not in SOURCE_INFO:
            continue
        kind, market, org = SOURCE_INFO[source]
        conf = "confirmed" if d < iso_today else "scheduled"
        if source == "kostat":
            event_time = t
            what = f"{org} 발표" + (f" · {detail}" if detail else "")
            name = title
        else:
            event_time = ""                  # 미국 동부 시각 — 그날 목록에서 한국 시각으로 읽히지 않게 설명에만
            what = (f"미국 동부 시각(ET) {t} 발표" if t else "미국 동부 날짜 기준 · 시각 미정") + f" · {org}"
            name = f"미국 {title}"
        ev.append((f"{kind}:{d}:{source}:{_short(title)}", kind, d, event_time, market, "", name, what, conf,
                   source, url, at))
    return ev


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.econ_calendar",
                                description="경제지표 발표 일정 받기 — 국가데이터처 보도계획 · 미국 BLS · BEA(달력 build 가 7일에 한 번 부른다)")
    p.add_argument("mode", choices=["fetch", "show"])
    p.add_argument("--force", action="store_true", help="7일 안이어도 다시 받는다")
    p.add_argument("--from", dest="since", default=date.today().isoformat())
    p.add_argument("--limit", type=int, default=40)
    a = p.parse_args(argv)
    conn = db.connect()
    ensure_schema(conn)
    try:
        if a.mode == "fetch":
            print(refresh_econ_releases(conn, date.today(), force=a.force, quiet=False))
        for r in conn.execute("SELECT release_date, release_time, tz, source, title FROM econ_release "
                              "WHERE release_date >= ? ORDER BY release_date, source LIMIT ?", (a.since, a.limit)):
            print(f"  {r[0]} {r[1] or '     '} {r[2] or '   '} {r[3]:6} {r[4]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
