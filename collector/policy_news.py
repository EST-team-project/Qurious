"""정책브리핑 정책뉴스 — 공공데이터포털 「문화체육관광부_정책브리핑_정책뉴스_API」(15095335) (목표 기능 ① W7 · 설계서 5.1.5).

    python -m collector.policy_news daily [--days 3] [--quiet]        최근 며칠(기본 3일 · 한 번 부름) — 러너 단계
    python -m collector.policy_news backfill --from 20200101 [--to 20261004] [--max-calls 900]
    python -m collector.policy_news reparse                            받아 둔 원문만으로 다시 읽기(호출 없음)
    python -m collector.policy_news status

주소
----
`apis.data.go.kr/1371000/policyNewsService2/policyNewsList2` — 포털 데이터 페이지의 swagger 원문(2026-10-05). 옛 주소
`policyNewsService/policyNewsList` 는 다른(옛) 서비스여서, 이 데이터셋을 승인받은 키로 부르면 「등록되지 않은 서비스키」
(코드 30)가 온다(2026-10-05 · 승인 뒤 2시간 넘게 그 오류를 키 반영 대기로 오해했다).

이용 조건
---------
데이터셋 이용허락범위는 공공누리 제1유형(출처 표시 — 상업적 이용 · 변경 가능)이고 개발계정 하루 1,000회다. 그런데 기사마다
`KoglType` 칸이 따로 온다 → **본문은 그 칸이 「1」 인 기사만** 둔다. 다른 유형이거나 빈칸이면 제목 · 부제 · 주소만 둔다.
화면 · 답에 보일 때는 「출처: 정책브리핑(www.korea.kr)」 을 붙인다(`ATTRIBUTION`).

날짜 창 · 시각
-------------
`startDate` ~ `endDate`(YYYYMMDD)는 승인일(ApproveDate)로 거른다(2026-10-05 실측 — 창 끝날 다음 날 00:00:00 에 승인된 기사도
함께 온다 · 다시 받아도 같은 행으로 고쳐질 뿐이다). swagger 는 「날짜범위 3일 초과」(98)를 오류로 적어 두었다 — 4일 창(10-01 ~
10-04)도 됐지만 적힌 규칙을 따라 **3일 창**으로 부른다. 응답 시각은 「MM/DD/YYYY HH24:MI:SS」(한국 시각)이다.
`available_at` = 승인 · 엠바고 해제 가운데 늦은 것 — 엠바고 기사는 승인 뒤에도 게시 전이라, 미래 참조 방지는 이 칸으로 한다.

과거 깊이 — 2015-01 기사도 온다(실측). 하루 약 15 ~ 20건 · 3일 창 응답 110 ~ 410KB.
"""

from __future__ import annotations

import argparse
import html
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter

URL = "https://apis.data.go.kr/1371000/policyNewsService2/policyNewsList2"
SOURCE = "policy_news"
ATTRIBUTION = "정책브리핑(www.korea.kr) · 공공누리 제1유형"

#: 한 번 부르는 날짜 창(날 수 · 시작일과 끝날 포함) — swagger 「날짜범위 3일 초과」 오류(98)를 넘지 않게.
WINDOW_DAYS = 3

#: 과거분 창을 늘 같은 자리에 두는 기준일 — 창 k 는 [EPOCH + 3k, EPOCH + 3k + 2]. 실행마다 시작일이 달라도 창 이름이 같아
#: 이미 받은 창(원문 `policy_news/<시작>-<끝>`)을 다시 부르지 않는다.
EPOCH = date(2000, 1, 1)

#: 개발계정 하루 1,000회 — 과거분 한 번 실행의 기본 상한(매일 단계 몫 · 손으로 보는 몫을 남긴다).
DAILY_LIMIT = 1_000
BACKFILL_MAX_CALLS = 900
SLEEP = 0.5

#: 포털 관문(게이트웨이) 오류 코드 — `returnReasonCode`.
GATEWAY_HINTS = {
    "12": "서비스가 없다 — 주소를 확인한다(정책뉴스는 policyNewsService2/policyNewsList2).",
    "20": "서비스 접근이 거부됐다 — 활용신청 상태를 확인한다.",
    "22": "하루 호출 한도(개발계정 1,000회)를 넘었다 — 내일 같은 명령으로 이어 간다.",
    "30": "등록되지 않은 서비스키 — 이 데이터셋(15095335)을 활용신청한 키인지, 주소가 policyNewsService2 인지 본다.",
    "31": "기한이 지난 서비스키 — 포털 마이페이지에서 활용 기간을 늘린다.",
}
API_HINTS = {
    "11": "필수 인자가 빠졌다(serviceKey · startDate · endDate).",
    "97": "날짜 꼴이 틀렸다(YYYYMMDD).",
    "98": "날짜 창이 3일을 넘었다.",
}


class PolicyNewsError(RuntimeError):
    """정책뉴스 API 가 정상 응답을 주지 않았다."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


class PolicyNewsQuota(PolicyNewsError):
    """하루 호출 한도를 넘었다 — 더 부르지 않는다."""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ==================================================
# 1. 응답 읽기 — 네트워크 없이 시험한다(TC-NW)
# ==================================================
def kst_iso(text: Optional[str]) -> str:
    """「MM/DD/YYYY HH24:MI:SS」(한국 시각) → 「YYYY-MM-DDTHH:MM:SS+09:00」. 비었거나 못 읽으면 빈칸."""
    s = (text or "").strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%dT%H:%M:%S") + "+09:00"
        except ValueError:
            continue
    return ""


_BREAKS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr|/table|/blockquote)\b[^>]*>")
_CELLS = re.compile(r"(?i)<\s*/\s*t[dh]\s*>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_DROP = re.compile(r"(?is)<\s*(script|style)\b.*?<\s*/\s*\1\s*>")
#: 모든 기사 끝에 붙는 이용 안내 문단 — 「정책브리핑의 자료는 「공공누리 제1유형:출처표시」의 조건에 따라 … 사진의 경우 제3자에게
#: 저작권이 있으므로 사용할 수 없습니다 … <자료출처=정책브리핑 www.korea.kr>」(2026-10-05 실측). 검색 · 근거 조각을 흐리므로
#: 본문에서 지우고, 출처 표시는 `ATTRIBUTION` 으로 따로 싣는다. 사진은 받지 않는다(글만 둔다).
_FOOTER = re.compile(r"\s*정책브리핑의\s*자료는\s*「\s*공공누리.*?(?:<\s*자료출처\s*=\s*정책브리핑[^>]*>|\Z)", re.S)


def html_to_text(raw: Optional[str]) -> str:
    """기사 HTML → 글. 줄을 끊는 태그(<br> · </p> …)는 줄바꿈, 표 칸 끝은 띄어쓰기, **나머지 태그는 그냥 지운다**.

    한글 문서에서 바꾼 HTML 은 낱말을 `<span>` 여러 개로 잘라 둔다(「<span>TV</span><span>는</span>」) — 태그를 띄어쓰기로
    바꾸면 「TV 는」 처럼 없던 띄어쓰기가 생긴다(2026-10-05 실측). 띄어쓰기가 필요한 곳은 원문이 이미 글자로 갖고 있다.
    """
    s = _DROP.sub(" ", raw or "")
    s = _BREAKS.sub("\n", s)
    s = _CELLS.sub(" ", s)
    s = _TAGS.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = _FOOTER.sub("", s)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out: List[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def _text(el: ET.Element, tag: str) -> str:
    return (el.findtext(tag) or "").strip()


def normalize(el: ET.Element) -> Optional[Dict[str, object]]:
    """`NewsItem` 한 건 → `news_item` 한 행(받은 시각 칸은 빼고). 기사 ID 나 제목이 없으면 None."""
    nid, title = _text(el, "NewsItemId"), html_to_text(_text(el, "Title"))
    if not nid or not title:
        return None
    kogl = _text(el, "KoglType")
    subs = [html_to_text(_text(el, f"SubTitle{i}")) for i in (1, 2, 3)]
    pub, emb = kst_iso(_text(el, "ApproveDate")), kst_iso(_text(el, "EmbargoDate"))
    try:
        rev = int(_text(el, "ModifyId") or 1)
    except ValueError:
        rev = 1
    body_raw = _text(el, "DataContents")
    body = ""
    if kogl == "1":                       # 공공누리 제1유형만 본문을 둔다 — 기사마다 유형이 따로 온다
        body = html_to_text(body_raw) if _text(el, "ContentsType").upper() != "T" else body_raw
    return {
        "news_id": f"policy:{nid}",
        "source": SOURCE,
        "title": title,
        "subtitle": "\n".join(s for s in subs if s),
        "body": body,
        "url": _text(el, "OriginalUrl"),
        "publisher": _text(el, "MinisterCode"),
        "category": _text(el, "GroupingCode"),
        "kogl_type": kogl,
        "pub_at": pub,
        "embargo_at": emb,
        "available_at": max(pub, emb),
        "modified_at": kst_iso(_text(el, "ModifyDate")),
        "revision": rev,
    }


def parse(body: bytes) -> Tuple[int, List[Dict[str, object]]]:
    """응답 바이트 → (totalCount, 행들). 오류 응답이면 예외 — 관문 오류(코드 22 = 하루 한도)는 `PolicyNewsQuota`.

    ⚠️ 포털은 실패해도 HTTP 200 으로 주는 일이 있어 결과 코드를 먼저 본다(`collector/sources/portal.py` 와 같은 원칙).
    """
    text = body.decode("utf-8", "replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise PolicyNewsError(f"정책뉴스 응답이 XML 이 아니다: {e} · 앞부분 {text[:120]!r}") from None
    gate = (root.findtext(".//returnReasonCode") or "").strip()
    if gate:
        msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip()
        cls = PolicyNewsQuota if gate == "22" else PolicyNewsError
        raise cls(f"정책뉴스 관문 오류 {gate} {msg!r}\n  할 일: {GATEWAY_HINTS.get(gate, '포털 오류 코드표를 본다.')}",
                  gate)
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("0", "00"):
        msg = (root.findtext(".//resultMsg") or "").strip()
        raise PolicyNewsError(f"정책뉴스 결과 코드 {code!r} {msg!r}\n  할 일: {API_HINTS.get(code, 'swagger 원문의 응답 코드를 본다.')}",
                              code)
    rows = [r for r in (normalize(el) for el in root.iter("NewsItem")) if r]
    try:
        total = int((root.findtext(".//totalCount") or "0").strip() or 0)
    except ValueError:
        total = len(rows)
    return total, rows


# ==================================================
# 2. 쌓기
# ==================================================
_COLS = ("news_id", "source", "title", "subtitle", "body", "url", "publisher", "category", "kogl_type", "pub_at",
         "embargo_at", "available_at", "modified_at", "revision")
_CONTENT = ("title", "subtitle", "body", "url", "publisher", "category", "kogl_type", "embargo_at", "available_at")


def upsert(conn: sqlite3.Connection, rows: Sequence[Dict[str, object]], *, at: str, raw_sha256: str = "") -> Dict[str, int]:
    """새 기사는 넣고, 고친 판(revision 이 오르거나 내용이 바뀜)이 오면 내용 · updated_at 만 고친다(fetched_at 그대로).

    같은 판을 다시 받으면 아무것도 바꾸지 않는다 — 겹치는 창(매일 3일)으로 받아도 행 · 색인이 흔들리지 않게.
    호출하는 쪽이 트랜잭션을 연다.
    """
    out = {"new": 0, "changed": 0, "same": 0}
    for r in rows:
        old = conn.execute(f"SELECT revision, {', '.join(_CONTENT)} FROM news_item WHERE news_id=?",
                           (r["news_id"],)).fetchone()
        if old is None:
            conn.execute(f"INSERT INTO news_item ({', '.join(_COLS)}, fetched_at, updated_at, raw_sha256) "
                         f"VALUES ({', '.join('?' * (len(_COLS) + 3))})",
                         tuple(r[c] for c in _COLS) + (at, at, raw_sha256))
            out["new"] += 1
            continue
        older_rev = int(r["revision"]) < int(old["revision"])
        same = all((old[c] or "") == (r[c] or "") for c in _CONTENT) and int(r["revision"]) == int(old["revision"])
        if same or older_rev:             # 옛 판이 늦게 와도(겹치는 창) 새 판을 되돌리지 않는다
            out["same"] += 1
            continue
        conn.execute(f"UPDATE news_item SET {', '.join(f'{c}=?' for c in _COLS[2:])}, updated_at=?, raw_sha256=? "
                     "WHERE news_id=?", tuple(r[c] for c in _COLS[2:]) + (at, raw_sha256, r["news_id"]))
        out["changed"] += 1
    return out


# ==================================================
# 3. 받기
# ==================================================
def window_target(start: date, end: date) -> str:
    return f"window/{start:%Y%m%d}-{end:%Y%m%d}"


def grid_windows(since: date, until: date) -> List[Tuple[date, date]]:
    """[since, until] 과 겹치는 고정 창(EPOCH 에서 3일씩) — 창이 until 을 넘으면 until 에서 자른다."""
    k = (since - EPOCH).days // WINDOW_DAYS
    out = []
    while True:
        s = EPOCH + timedelta(days=k * WINDOW_DAYS)
        if s > until:
            break
        e = min(s + timedelta(days=WINDOW_DAYS - 1), until)
        out.append((s, e))
        k += 1
    return out


def _kept_windows(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT DISTINCT target FROM raw_response WHERE source=? AND target LIKE 'window/%'",
                                       (SOURCE,))}


def fetch_window(conn: sqlite3.Connection, limiter: RateLimiter, start: date, end: date, *,
                 session=None, target: Optional[str] = None) -> Dict[str, int]:
    """창 하나를 불러 원문 · 행을 **한 트랜잭션에** 쓴다(원문만 남거나 행만 남으면 재개가 거짓말을 한다)."""
    import requests

    limiter.wait()
    sess = session or requests
    r = sess.get(URL, params={"serviceKey": config.portal_key(), "startDate": f"{start:%Y%m%d}",
                              "endDate": f"{end:%Y%m%d}"}, timeout=90)
    if not r.content.lstrip().startswith(b"<"):
        # 관문 오류도 XML 로 온다(키 오류는 HTTP 403 + XML) — XML 이 아니면 HTTP 상태만 알린다
        raise PolicyNewsError(f"정책뉴스 응답이 XML 이 아니다 — HTTP {r.status_code} ({start} ~ {end})")
    total, rows = parse(r.content)
    at = _now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        sha = raw_store.save(conn, SOURCE, target or window_target(start, end), r.content,
                             http_status=r.status_code, note=f"items={len(rows)} total={total}")
        out = upsert(conn, rows, at=at, raw_sha256=sha)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    out["items"] = len(rows)
    return out


def daily(conn: sqlite3.Connection, today: date, *, days: int = WINDOW_DAYS, session=None) -> Dict[str, int]:
    """오늘까지 최근 `days` 일 — 3일 창으로 나눠 부른다(기본 3일 = 한 번). 원문 이름은 `daily/<시작>-<끝>`."""
    limiter = RateLimiter(SLEEP, name="정책뉴스")
    total = {"calls": 0, "items": 0, "new": 0, "changed": 0, "same": 0}
    end = today
    first = today - timedelta(days=max(1, days) - 1)
    while end >= first:
        start = max(first, end - timedelta(days=WINDOW_DAYS - 1))
        r = fetch_window(conn, limiter, start, end, session=session, target=f"daily/{start:%Y%m%d}-{end:%Y%m%d}")
        total["calls"] += 1
        for k in ("items", "new", "changed", "same"):
            total[k] += r[k]
        end = start - timedelta(days=1)
    return total


def backfill(conn: sqlite3.Connection, since: date, until: date, *, max_calls: int = BACKFILL_MAX_CALLS,
             newest_first: bool = True, quiet: bool = True, session=None,
             sleep: Callable[[float], None] = time.sleep) -> Dict[str, object]:
    """지난 기사 — 고정 창마다 한 번, 이미 받은 창(원문이 있는 창)은 건너뛴다. 하루 한도면 멈추고 같은 명령으로 이어 간다.

    네트워크 오류는 그 창을 10 · 30초 쉬었다 두 번 더 부르고, 그래도 안 되면 건너뛰고 센다(다음 실행이 다시 부른다).
    """
    import requests

    limiter = RateLimiter(SLEEP, name="정책뉴스")
    sess = session or requests.Session()
    kept = _kept_windows(conn)
    todo = [w for w in grid_windows(since, until) if window_target(*w) not in kept]
    if newest_first:
        todo.reverse()
    out: Dict[str, object] = {"todo": len(todo), "calls": 0, "windows": 0, "items": 0, "new": 0, "changed": 0,
                              "errors": 0, "quota": False}
    for i, (s, e) in enumerate(todo, 1):
        if out["calls"] >= max_calls:
            break
        for attempt in range(3):
            if out["calls"] >= max_calls:
                break
            out["calls"] += 1
            try:
                r = fetch_window(conn, limiter, s, e, session=sess)
                out["windows"] += 1
                for k in ("items", "new", "changed"):
                    out[k] += r[k]
                break
            except PolicyNewsQuota:
                out["quota"] = True
                break
            except (PolicyNewsError, requests.RequestException) as ex:
                if attempt == 2:
                    out["errors"] += 1
                    print(f"  ⚠️ {s} ~ {e} 건너뜀 — {type(ex).__name__}: {str(ex)[:120]}", flush=True)
                    break
                sleep((10, 30)[attempt])
        if out["quota"]:
            break
        if not quiet and i % 50 == 0:
            print(f"  {datetime.now():%H:%M:%S} 창 {i:,}/{len(todo):,} · 기사 {out['items']:,}(새 {out['new']:,}) · "
                  f"건너뜀 {out['errors']}", flush=True)
    out["left"] = len(todo) - out["windows"] - out["errors"]
    return out


def reparse(conn: sqlite3.Connection) -> Dict[str, int]:
    """받아 둔 원문(raw_response 의 policy_news)만으로 다시 읽는다 — 호출 없음. 글 바꾸기 규칙을 고쳤을 때 쓴다.

    창마다 가장 최근 원문을 읽는다. 같은 기사가 여러 창에 있어도 `upsert` 가 옛 판으로 되돌리지 않고, 내용이 달라진
    행만 updated_at 이 바뀐다(검색 색인이 그 행만 다시 넣는다).
    """
    out = {"raws": 0, "new": 0, "changed": 0, "same": 0}
    at = _now_iso()
    targets = [t for (t,) in conn.execute("SELECT DISTINCT target FROM raw_response WHERE source=? ORDER BY target",
                                          (SOURCE,))]
    conn.execute("BEGIN IMMEDIATE")
    try:
        for t in targets:
            kept = raw_store.load(conn, SOURCE, t)
            if not kept:
                continue
            _, rows = parse(kept["body"])
            r = upsert(conn, rows, at=at, raw_sha256=kept["sha256"])
            out["raws"] += 1
            for k in ("new", "changed", "same"):
                out[k] += r[k]
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return out


# ==================================================
# 4. 상태
# ==================================================
def status_lines(conn: sqlite3.Connection) -> Iterator[str]:
    n, lo, hi = conn.execute("SELECT COUNT(*), MIN(pub_at), MAX(pub_at) FROM news_item WHERE source=?", (SOURCE,)).fetchone()
    yield f"정책뉴스 {n:,}건 · 승인 {lo or '-'} ~ {hi or '-'}"
    for y, c, b in conn.execute("SELECT substr(pub_at,1,4) y, COUNT(*), SUM(body <> '') FROM news_item WHERE source=? "
                                "GROUP BY y ORDER BY y", (SOURCE,)):
        yield f"  {y} {c:,}건 · 본문 있음 {b:,}"
    kinds = conn.execute("SELECT kogl_type, COUNT(*) FROM news_item WHERE source=? GROUP BY kogl_type", (SOURCE,)).fetchall()
    yield "  공공누리 " + " · ".join(f"{k or '빈칸'} {c:,}" for k, c in kinds)
    w = conn.execute("SELECT COUNT(DISTINCT target) FROM raw_response WHERE source=?", (SOURCE,)).fetchone()[0]
    yield f"  원문 {w:,}창"


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.policy_news", description="정책브리핑 정책뉴스 받기")
    sub = p.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("daily", help="최근 며칠(기본 3일 · 한 번 부름) — 러너 단계")
    d.add_argument("--days", type=int, default=WINDOW_DAYS)
    d.add_argument("--quiet", action="store_true")
    b = sub.add_parser("backfill", help="지난 기사 — 고정 3일 창 · 이미 받은 창은 건너뜀 · 최근 것부터")
    b.add_argument("--from", dest="bgn", required=True, help="시작 YYYYMMDD")
    b.add_argument("--to", dest="end", default="", help="끝 YYYYMMDD(비우면 어제)")
    b.add_argument("--max-calls", type=int, default=BACKFILL_MAX_CALLS)
    b.add_argument("--oldest-first", action="store_true")
    sub.add_parser("reparse", help="받아 둔 원문만으로 다시 읽기(호출 없음 · 글 바꾸기 규칙을 고쳤을 때)")
    sub.add_parser("status")
    a = p.parse_args(argv)
    conn = db.connect()
    try:
        if a.mode == "daily":
            r = daily(conn, date.today(), days=a.days)
            print(f"  정책뉴스 — 부름 {r['calls']} · 기사 {r['items']} · 새 {r['new']} · 고침 {r['changed']} · 그대로 {r['same']}")
        elif a.mode == "backfill":
            since = datetime.strptime(a.bgn, "%Y%m%d").date()
            until = datetime.strptime(a.end, "%Y%m%d").date() if a.end else date.today() - timedelta(days=1)
            print(f"  {datetime.now():%Y-%m-%d %H:%M:%S} 정책뉴스 과거분 — {since} ~ {until} · 상한 {a.max_calls:,}회", flush=True)
            r = backfill(conn, since, until, max_calls=a.max_calls, newest_first=not a.oldest_first, quiet=False)
            print(f"  {datetime.now():%Y-%m-%d %H:%M:%S} 끝 — 창 {r['windows']:,}/{r['todo']:,} · 기사 {r['items']:,}"
                  f"(새 {r['new']:,} · 고침 {r['changed']:,}) · 건너뜀 {r['errors']} · 부름 {r['calls']:,} · 남음 {r['left']:,}"
                  + (" · ⛔ 하루 한도 — 내일 같은 명령으로 이어 간다" if r["quota"] else ""), flush=True)
        elif a.mode == "reparse":
            r = reparse(conn)
            print(f"  정책뉴스 다시 읽기 — 원문 {r['raws']:,}창 · 새 {r['new']:,} · 고침 {r['changed']:,} · 그대로 {r['same']:,}")
        else:
            for ln in status_lines(conn):
                print(ln)
    except PolicyNewsError as e:
        print(f"🔴 {e}")
        return 3 if isinstance(e, PolicyNewsQuota) else 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
