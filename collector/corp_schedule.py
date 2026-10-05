"""주주총회 · 배당금 지급 일정 — 공시 본문에서 날짜를 읽는다 (목표 기능 ① W7 · 설계서 5.2.4 <표 15>).

    python -m collector.corp_schedule daily [--days 60] [--max-calls 1500]   최근 소집결의 본문 받기 → 읽기
    python -m collector.corp_schedule build [--rebuild]                     받아 둔 원문만 읽기(호출 없음)
    python -m collector.corp_schedule show [--kind agm] [--from 2026-10-01]

일정 종류 둘
------------
==============  ======================================================  ===========  ==================
종류(kind)       출처 · 규칙                                                확실도         날짜
==============  ======================================================  ===========  ==================
agm             「주주총회소집결의」 본문의 일시 칸 — 정정 공시가 있으면 마지막 정정본       confirmed ·   회의일 · 시각
                                                                        scheduled
dividend_pay    「현금ㆍ현물배당결정」 본문의 「배당금지급 예정일자」 — 배당 표가 고른 판만     confirmed ·   지급 예정일
                                                                        scheduled
==============  ======================================================  ===========  ==================

왜 본문인가 — 공시 목록에는 회의일 · 지급일 칸이 없다. 본문의 표 꼴은 서식마다 달라서(거래소 서식 「1. 일시 / 날짜 /
2026-11-10」 + 다음 줄 「시간 / 오전 10시」 · 리츠 서식 「2. 일시 / 2026-02-24 / 09 : 00」 · 정정본은 앞에 정정 표)
트리 경로가 아니라 **라벨로 찾는다**(`collector/sources/dart.py` 의 `flatten` 과 같은 원칙).

결산배당의 지급일은 대부분 본문에 없다 — 「-」 로 두고 주주총회에서 정한 뒤 「주총일로부터 1개월 이내」 에 준다.
없는 날은 만들지 않는다(추측하지 않는다). 2026-10-05 실측 배당 본문 9,872건 중 날짜 3,307 · 「-」 6,888.

원문은 `raw_response` 에 남는다(`dart` · `agm/<접수번호>` · `dividend/<접수번호>`). 이 파일이 만드는 표
`corp_schedule` 는 계산한 것이라 지워도 `build --rebuild` 가 원문에서 되살린다.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter
from collector.sources import dart

#: 소집결의 공시 제목(머리 [기재정정] · 꼬리 「(임시주주총회)」 를 뗀 `disclosure.title`).
AGM_TITLE = "주주총회소집결의"

#: 매일 받는 창 — 오늘부터 거슬러 이 날 수 안에 접수된 소집결의(설계서 · 처음은 60일부터).
WINDOW_DAYS = 60

#: 한 번 실행의 본문 호출 상한 — DART 개인 하루 20,000회(83종 합계)를 다른 단계와 나눠 쓴다.
MAX_CALLS = 1_500

_DATE = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")
_TIME = re.compile(r"(오전|오후|AM|PM)?\s*(\d{1,2})\s*(?:시|:)\s*(?:(\d{1,2})\s*분?)?", re.I)

#: 칸 끝 라벨 — 「1. 일시」 · 「2. 일시」 처럼 번호가 앞에 붙고, 첫 줄은 머리 글 뒤에 이어 붙어 온다.
_LBL_WHEN = re.compile(r"일\s*시\s*$")
_LBL_PLACE = re.compile(r"장\s*소\s*$")
_LBL_KIND = re.compile(r"구\s*분\s*$")
_LBL_ORIG = re.compile(r"정정관련\s*공시서류\s*제출일")
_LBL_AGENDA_TEXT = re.compile(r"의안\s*주요\s*내용\s*$")
#: 지급일 라벨 — 「7. 배당금지급 예정일자」(본문) · 「배당금지급 예정일자 확정」 「배당금 지급일자 확정」(정정 표) …
_LBL_PAY = re.compile(r"지급\s*(?:예정)?\s*일")
_NUMBERED = re.compile(r"^\s*\d+\s*\.")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dates(text: str) -> List[str]:
    """글 안의 날짜를 모두(있을 수 없는 날은 버린다) — YYYY-MM-DD."""
    out = []
    for m in _DATE.finditer(text):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat())
        except ValueError:
            continue
    return out


def _clock(text: str) -> str:
    """「오전 10시」 · 「10:00」 · 「09 : 00」 · 「오후 2시 30분」 → HH:MM. 못 읽으면 빈칸.

    시간 칸에 숫자만 있으면(「시간 / 09」 · 2026-10-05 비츠로시스) 그 시 정각으로 읽는다 — 칸 전체가 1 ~ 2자리 숫자일 때만.
    """
    bare = (text or "").strip()
    if re.fullmatch(r"\d{1,2}", bare):
        h = int(bare)
        return f"{h:02d}:00" if 0 <= h <= 23 else ""
    m = _TIME.search(text or "")
    if not m:
        return ""
    ampm, h, mi = (m.group(1) or "").lower(), int(m.group(2)), int(m.group(3) or 0)
    if ampm in ("오후", "pm") and h < 12:
        h += 12
    if ampm in ("오전", "am") and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return ""
    return f"{h:02d}:{mi:02d}"


def _after(cells: Sequence[str], label: re.Pattern) -> Optional[List[str]]:
    for k, c in enumerate(cells):
        if label.search(c):
            return list(cells[k + 1:])
    return None


# ==================================================
# 1. 본문 읽기 — 네트워크 없이 시험한다(TC-CS)
# ==================================================
def parse_agm(lines: Sequence[str], report_nm: str = "") -> Dict[str, object]:
    """주주총회소집결의 본문(`dart.flatten` 한 줄들) → 회의일 · 시각 · 구분 · 장소 · 안건 · 정정의 원 공시 제출일.

    일시 칸은 **마지막** 것을 쓴다 — 정정본은 앞에 정정 표(정정전 · 정정후)가 오고 뒤에 고친 본문 전체가 온다.
    한 줄 안에 날짜가 둘이면(정정 표의 정정전 · 정정후) 뒤의 것을 쓴다.
    """
    out: Dict[str, object] = {"date": "", "time": "", "label": "", "place": "", "agenda": [], "orig_filed": "",
                              "when_text": ""}
    rows = [ln.split("\t") for ln in lines]
    for i, cells in enumerate(rows):
        rest = _after(cells, _LBL_WHEN)
        if rest is None:
            continue
        ds = _dates(" ".join(rest))
        if not ds:
            continue
        out["date"] = ds[-1]
        clock_text = " ".join(c for c in rest if not _dates(c) and c.strip() not in ("날짜", "일자"))
        if not clock_text and i + 1 < len(rows) and rows[i + 1] and rows[i + 1][0].strip() in ("시간", "시각"):
            clock_text = " ".join(rows[i + 1][1:])
        if not clock_text:
            # 날짜와 시각이 한 칸에 같이 온 꼴(정정 표의 「2026-03-27 10:00」) — 마지막 날짜가 든 칸에서 날짜를 지우고 읽는다
            last_cell = [c for c in rest if _dates(c) and _dates(c)[-1] == ds[-1]]
            if last_cell:
                clock_text = _DATE.sub(" ", last_cell[-1].split("\t")[-1]).strip()
        out["time"] = _clock(clock_text)
        out["when_text"] = " ".join(rest + ([clock_text] if clock_text and clock_text not in rest else []))[:80]
    for cells in rows:
        rest = _after(cells, _LBL_PLACE)
        if rest:
            out["place"] = " ".join(rest)[:80]
        rest = _after(cells, _LBL_ORIG)
        if rest and _dates(" ".join(rest)):
            out["orig_filed"] = _dates(" ".join(rest))[0]
    # 구분 — 공시 이름 꼬리가 가장 확실하다(「주주총회소집결의 (임시주주총회)」). 없으면 본문의 구분 칸.
    for word in ("임시주주총회", "정기주주총회"):
        if word in report_nm:
            out["label"] = word
            break
    if "철회" in report_nm:                    # 「(임시주주총회-철회)」 — 소집을 거둔 정정. 본문 일시는 「-」 다
        out["label"] = f"{out['label'] or '주주총회'}(철회)"
        out["date"] = out["time"] = ""
        return out
    if not out["label"]:
        for cells in rows:
            rest = _after(cells, _LBL_KIND)
            if rest:
                joined = " ".join(rest)
                for word in ("임시주주총회", "정기주주총회"):
                    if word in joined:
                        out["label"] = word
                if out["label"]:
                    break
    # 안건 — 「안건 세부내역」 표의 번호 줄 · 리츠 서식은 「의안 주요내용」 한 칸
    agenda: List[str] = []
    in_table = False
    for cells in rows:
        joined = " ".join(cells)
        if "안건 세부내역" in joined.replace("  ", " ") or "회의목적사항" in joined:
            in_table = True
            continue
        if in_table:
            if "세부내역" in joined:          # 「사외이사선임 세부내역」 같은 다음 표가 오면 끝
                break
            if len(cells) >= 2 and re.fullmatch(r"(?:제\s*)?\d+(?:-\d+)?\s*(?:호)?", cells[0].strip()):
                agenda.append(cells[1].strip())
        rest = _after(cells, _LBL_AGENDA_TEXT)
        if rest and not agenda:
            agenda = [" ".join(rest)]
    out["agenda"] = agenda[:5]
    return out


def parse_dividend_pay(lines: Sequence[str]) -> Dict[str, str]:
    """현금ㆍ현물배당결정 본문 → 배당금 지급 예정일.

    본문 줄(번호가 붙은 「7. 배당금지급 예정일자」)의 날짜가 먼저다. 본문이 「-」 인데 정정 표(번호 없음 · 정정전 · 정정후)에
    날짜가 있으면 정정후(그 줄의 마지막 날짜)를 쓴다. 날짜가 없으면 빈칸 + 칸의 원문 글(「-」 · 「주총일로부터 1개월 이내」 …).
    """
    main_date = main_text = corr_date = ""
    for ln in lines:
        cells = ln.split("\t")
        for k, c in enumerate(cells):
            if len(c) > 40 or not _LBL_PAY.search(c) or "배당" not in c:
                continue
            rest = cells[k + 1:]
            ds = _dates(" ".join(rest))
            if _NUMBERED.match(c):
                if ds and not main_date:
                    main_date = ds[0]
                elif not ds and not main_text:
                    main_text = " ".join(rest).strip()[:60]
            elif ds:
                corr_date = ds[-1]
            break
    if main_date:
        return {"date": main_date, "text": ""}
    if corr_date:
        return {"date": corr_date, "text": "정정 표의 정정후 날짜"}
    return {"date": "", "text": main_text}


# ==================================================
# 2. 받기 · 읽기
# ==================================================
def ensure_schema(conn: sqlite3.Connection) -> None:
    """표 정의는 수집 DB 스키마 한 곳(`collector/db.py` 17절)에 있다 — 옛 DB 를 열 때도 보장한다."""
    conn.executescript(db.CORP_SCHEDULE_DDL)


def _raw_targets(conn: sqlite3.Connection, prefix: str) -> Set[str]:
    return {r[0].split("/", 1)[1] for r in conn.execute(
        "SELECT DISTINCT target FROM raw_response WHERE source='dart' AND target LIKE ?", (prefix + "/%",))}


def fetch_recent(conn: sqlite3.Connection, today: date, *, days: int = WINDOW_DAYS, max_calls: int = MAX_CALLS,
                 quiet: bool = True) -> Dict[str, int]:
    """최근 `days` 일 안에 접수된 소집결의 가운데 본문을 아직 안 받은 것만 받는다(원문은 `agm/<접수번호>`)."""
    import requests

    since = (today - timedelta(days=days)).strftime("%Y%m%d")
    have = _raw_targets(conn, "agm")
    todo = [r[0] for r in conn.execute(
        "SELECT rcept_no FROM disclosure WHERE title LIKE ? AND stock_code <> '' AND rcept_dt >= ? ORDER BY rcept_no",
        (AGM_TITLE + "%", since)) if r[0] not in have]
    limiter = RateLimiter(config.DART_SLEEP, reserve=config.DART_RESERVE, name="DART")
    session = requests.Session()
    got = missing = 0
    for n, rno in enumerate(todo[:max_calls], 1):
        try:
            dart.fetch_document(conn, limiter, rno, session=session, target_prefix="agm")
            got += 1
        except dart.DartNoDocument:
            missing += 1
        if not quiet and n % 100 == 0:
            print(f"  본문 {n:,}/{min(len(todo), max_calls):,} …", flush=True)
    return {"todo": len(todo), "fetched": got, "no_document": missing, "left": max(0, len(todo) - max_calls)}


def _agm_detail(p: Dict[str, object]) -> str:
    parts = []
    if p.get("time"):
        parts.append(str(p["time"]))
    elif p.get("when_text"):
        parts.append(f"시각 칸: {p['when_text']}")
    if p.get("place"):
        parts.append(f"장소 {p['place']}")
    agenda = p.get("agenda") or []
    if agenda:
        parts.append("안건 " + " · ".join(str(a)[:40] for a in agenda[:3]) + (f" 외 {len(agenda) - 3}건" if len(agenda) > 3 else ""))
    return " · ".join(parts)


def build(conn: sqlite3.Connection, *, rebuild: bool = False, quiet: bool = True) -> Dict[str, int]:
    """받아 둔 원문에서 아직 읽지 않은 것만 읽는다(호출 없음). `rebuild` 면 표를 비우고 다 다시 읽는다."""
    ensure_schema(conn)
    at = _now_iso()
    if rebuild:
        conn.execute("DELETE FROM corp_schedule")
    done = {(r[0], r[1]) for r in conn.execute("SELECT rcept_no, kind FROM corp_schedule")}
    out = {"agm": 0, "agm_dated": 0, "dividend_pay": 0, "dividend_dated": 0}
    rows: List[tuple] = []

    have_agm = _raw_targets(conn, "agm")
    for rno, code, name, rep in conn.execute(
            "SELECT rcept_no, stock_code, corp_name, report_nm FROM disclosure WHERE title LIKE ? AND stock_code <> ''",
            (AGM_TITLE + "%",)).fetchall():
        if (rno, "agm") in done or rno not in have_agm:
            continue
        kept = raw_store.load(conn, "dart", f"agm/{rno}")
        try:
            p = parse_agm(dart.flatten(dart._unzip(kept["body"], rno)), rep or "")
        except Exception:                    # 깨진 원문 한 건이 전체를 멈추지 않게 — 빈 날짜로 남겨 센다
            p = {"date": "", "time": "", "label": "", "orig_filed": ""}
        rows.append((rno, "agm", code, name, p["date"], p["time"], p.get("label") or "", _agm_detail(p),
                     p.get("orig_filed") or "", kept["sha256"], at))
        out["agm"] += 1
        out["agm_dated"] += bool(p["date"])

    has_div = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dividend'").fetchone()
    for rno, code, name, kind, dps, rec in (conn.execute(
            "SELECT rcept_no, srtn_cd, itms_nm, div_kind, dps, record_dt FROM dividend WHERE rcept_no <> ''").fetchall()
            if has_div else []):
        if (rno, "dividend_pay") in done:
            continue
        kept = raw_store.load(conn, "dart", f"dividend/{rno}")
        if not kept:
            continue
        try:
            p = parse_dividend_pay(dart.flatten(dart._unzip(kept["body"], rno)))
        except Exception:
            p = {"date": "", "text": "본문을 읽지 못함"}
        rec_iso = f"{rec[:4]}-{rec[4:6]}-{rec[6:8]}" if rec and len(rec) == 8 else rec
        detail = (f"1주당 {dps:,.0f}원 · " if dps else "") + f"배당기준일 {rec_iso}"
        if p["date"] and rec_iso and p["date"] < rec_iso:
            # 기준일보다 앞선 지급일은 해를 잘못 적은 제출 오기로 보인다(2026-10-05 실측 4건 · 예 기준일 2026-08-31 · 지급 2025-09-11).
            # 해를 고쳐 넣지 않는다(추측하지 않는다) — 날짜는 비우고 원문 값을 칸 글로 남긴다.
            p = {"date": "", "text": f"본문 날짜 {p['date']} 가 배당기준일보다 앞서 쓰지 않음(제출 오기로 보임)"}
        if p["text"]:
            detail += f" · 지급일 칸: {p['text']}"
        rows.append((rno, "dividend_pay", code, name, p["date"], "", kind or "", detail, "", kept["sha256"], at))
        out["dividend_pay"] += 1
        out["dividend_dated"] += bool(p["date"])

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany("INSERT OR REPLACE INTO corp_schedule (rcept_no, kind, stock_code, corp_name, event_date, "
                         "event_time, label, detail, orig_filed, raw_sha256, parsed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    if not quiet:
        print(f"  읽음 — 주주총회 {out['agm']:,}(날짜 {out['agm_dated']:,}) · "
              f"배당 지급 {out['dividend_pay']:,}(날짜 {out['dividend_dated']:,})")
    return out


# ==================================================
# 3. 달력 일정 — `event_sources.extra_events` 가 부른다
# ==================================================
def schedule_events(conn: sqlite3.Connection, today: date, at: str) -> List[tuple]:
    """`corp_schedule` → `market_event` 줄(agm · dividend_pay).

    주주총회: 같은 종목의 원 공시와 정정을 사슬로 묶어(정정의 「정정관련 공시서류제출일」 은 원 공시나 바로 앞 정정을 가리킨다)
    묶음에서 가장 늦은 판 하나만 쓴다 — 회의일을 바꾼 정정이 있으면 옛 날짜가 달력에 남지 않는다. 가장 늦은 판에
    날짜가 없으면(소집 철회 · 「일시 미정」 으로 바꾼 정정) 그 묶음은 달력에 올리지 않는다 — 열리지 않을 회의를
    예정으로 보여 주는 것이 하나 빠뜨리는 것보다 나쁘다(2026-10-05 실측: 휴온스 · 휴온스글로벌 철회 · 디에스케이 미정).
    배당 지급: 배당 표(`dividend`)가 고른 판(정정이면 정정본)의 접수번호만 쓴다.
    같은 종목 · 같은 날은 하나(접수번호가 큰 것).
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='corp_schedule'").fetchone():
        return []
    iso_today = today.isoformat()
    ev: List[tuple] = []

    rows = conn.execute(
        "SELECT c.rcept_no, c.stock_code, c.corp_name, c.event_date, c.event_time, c.label, c.detail, c.orig_filed, "
        "COALESCE(s.rcept_dt, substr(c.rcept_no, 1, 8)) FROM corp_schedule c "
        "LEFT JOIN disclosure s ON s.rcept_no = c.rcept_no "
        "WHERE c.kind='agm' AND c.stock_code <> ''").fetchall()
    # 정정의 「정정관련 공시서류제출일」 은 원 공시가 아니라 바로 앞 정정을 가리키기도 한다(2026-10-05 실측 — 비츠로시스
    # 08-31 정정 → 08-05 · 09-03 정정 → 08-31 · 09-08 → 09-03 · 09-17 → 09-08). 그래서 같은 종목에서 「가리킨 날에 낸
    # 소집결의」 와 잇는 사슬을 합집합으로 묶는다 — 원 공시 하나로만 묶으면 연기된 옛 날짜가 「확정」 으로 남는다.
    # 마디 = 공시 한 건 + 「종목 · 정정이 가리킨 날」 가상 마디. 정정은 가리킨 날 마디와 잇고, 그날 낸 공시도 그 마디와 잇는다.
    # 원 공시가 60일 창 밖이라 표에 없어도 같은 날을 가리키는 정정끼리는 묶이고, 아무 정정도 가리키지 않은 날의 소집결의는
    # 따로 남는다 — 같은 날 낸 정정과 새 소집결의는 다른 회의일 수 있다(프리티 09-17 · TC-CS-08).
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    targets = {(r[1], r[7].replace("-", "")) for r in rows if r[7]}
    for r in rows:
        find(r[0])
        if r[7]:
            union(r[0], f"tgt:{r[1]}:{r[7].replace('-', '')}")
        if (r[1], r[8]) in targets:
            union(r[0], f"tgt:{r[1]}:{r[8]}")
    groups: Dict[str, tuple] = {}
    for rno, code, name, d, t, label, detail, orig, rcept_dt in rows:
        root = find(rno)
        if root not in groups or rno > groups[root][0]:
            groups[root] = (rno, code, name, d, t, label, detail)
    best: Dict[Tuple[str, str], tuple] = {}
    for g in groups.values():
        if not g[3]:                         # 가장 늦은 판에 날짜가 없다 — 철회 · 미정
            continue
        k = (g[1], g[3])
        if k not in best or g[0] > best[k][0]:
            best[k] = g
    for rno, code, name, d, t, label, detail in best.values():
        conf = "confirmed" if d < iso_today else "scheduled"
        ev.append((f"agm:{d}:{code}", "agm", d, t, "", code, f"{name} {label or '주주총회'}", detail, conf,
                   "dart", rno, at))

    has_div = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dividend'").fetchone()
    pay: Dict[Tuple[str, str], tuple] = {}
    for rno, code, name, d, label, detail in (conn.execute(
            "SELECT c.rcept_no, c.stock_code, c.corp_name, c.event_date, c.label, c.detail FROM corp_schedule c "
            "JOIN dividend v ON v.rcept_no = c.rcept_no "
            "WHERE c.kind='dividend_pay' AND c.event_date <> '' AND c.stock_code <> ''") if has_div else []):
        k = (code, d)
        if k not in pay or rno > pay[k][0]:
            pay[k] = (rno, code, name, d, label, detail)
    for rno, code, name, d, label, detail in pay.values():
        conf = "confirmed" if d < iso_today else "scheduled"
        title = f"{name} 배당금 지급" + (f"({label})" if label else "")
        ev.append((f"dividend_pay:{d}:{code}", "dividend_pay", d, "", "", code, title, detail, conf, "dart", rno, at))
    return ev


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.corp_schedule",
                                description="주주총회 · 배당금 지급 일정 — 공시 본문에서 날짜 읽기")
    sub = p.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("daily", help="최근 소집결의 본문 받기 → 읽기(러너 단계)")
    d.add_argument("--days", type=int, default=WINDOW_DAYS)
    d.add_argument("--max-calls", type=int, default=MAX_CALLS)
    d.add_argument("--quiet", action="store_true", help="진행 줄을 찍지 않는다(요약 두 줄만)")
    b = sub.add_parser("build", help="받아 둔 원문만 읽기(호출 없음)")
    b.add_argument("--rebuild", action="store_true", help="표를 비우고 다 다시 읽는다(규칙을 고쳤을 때)")
    s = sub.add_parser("show")
    s.add_argument("--kind", choices=["agm", "dividend_pay"], default="agm")
    s.add_argument("--from", dest="since", default=date.today().isoformat())
    s.add_argument("--limit", type=int, default=30)
    a = p.parse_args(argv)
    conn = db.connect()
    ensure_schema(conn)
    try:
        if a.mode == "daily":
            r = fetch_recent(conn, date.today(), days=a.days, max_calls=a.max_calls, quiet=a.quiet)
            print(f"  소집결의 본문 — 받을 것 {r['todo']:,} · 받음 {r['fetched']:,} · 본문 없음 {r['no_document']:,} · "
                  f"다음으로 {r['left']:,}")
            build(conn, quiet=False)
        elif a.mode == "build":
            build(conn, rebuild=a.rebuild, quiet=False)
        else:
            for r in conn.execute("SELECT event_date, event_time, stock_code, corp_name, label, detail FROM corp_schedule "
                                  "WHERE kind=? AND event_date >= ? ORDER BY event_date, stock_code LIMIT ?",
                                  (a.kind, a.since, a.limit)):
                print(f"  {r[0]} {r[1] or '     '} {r[2]} {r[3]} · {r[4]} · {r[5][:70]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
