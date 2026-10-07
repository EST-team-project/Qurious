"""언론사 기사 메타데이터 — GDELT 2.0 번역 GKG 15분 원자료에서 한국어 원문 기사의 제목 · 원문 주소 · 시각 · 언론사만 (목표 기능 ① W7 · 설계서 5.1.5).

    python -m collector.gdelt_news daily [--hours 30] [--quiet]     지난 몇 시간의 15분 파일 가운데 아직 안 읽은 것 — 러너 단계
    python -m collector.gdelt_news backfill --from 20261003 [--to 20261004]   날짜(UTC) 구간의 파일
    python -m collector.gdelt_news status

왜 GDELT 원자료인가 (2026-10-05 조사 · 조사서 `docs/조사/공시-재무-뉴스-이용조건-조사.md` 4.4 · 데이터 파트 결정)
--------------------------------------------------------------------------
- 네이버 검색 API 는 결과 저장 · AI 입력 · 제3자 제공이 금지(약관 2.3) · 언론사 RSS 는 「비상업적 블로그와 개인적인 용도로만」
  (연합뉴스) · 「다수 이용자 대상 … AI학습 이용 금지」(서울경제) · 언론진흥재단 규칙 「재RSS 서비스 금지」 — 앱에서 여러 사람에게
  다시 보이는 용도로는 막힌다.
- GDELT 는 「학술 · 상업 · 정부 용도로 제한 없이」 쓰게 하고 GDELT 인용과 링크를 조건으로 단다. DOC API(api.gdeltproject.org)는
  이 PC 에서 첫 호출부터 429 였지만, 15분 원자료(data.gdeltproject.org)는 막힘 없이 받힌다.

무엇을 두고 무엇을 두지 않나
--------------------------
- 둔다: 제목(PAGE_TITLE · HTML 문자 참조를 푼다) · 원문 주소 · 시각(V2.1DATE · UTC → KST) · 언론사(도메인).
- **두지 않는다: 본문 · 요약.** 언론사 기사 본문은 언론사 저작물이다. 화면은 「제목 + 원문 링크」(단순 링크)만 보이고,
  근거 답(AI)에는 넣지 않는다(설계서 5.1.5 <표 13> · 조사서 <표 9>).
- 거른다: 웹 기사가 아닌 것(수집 경로 1 = WEB 만) · 제목 없는 것 · 커뮤니티 · 블로그 주소(`DENY_HOST` — 처음 목록 · 늘려 간다).

규모(2026-10-05 표본 8창) — 한국어 원문 기사 하루 약 1,500건 · 언론사 16곳 · 제목에 금융 낱말 13% · 15분 파일 하나 약 5.8MB
(번역 GKG 전체) → 하루 96파일 약 550MB 를 내려받아 한국어 줄만 남긴다. 원문 zip 은 두지 않는다(크고 GDELT 가 보관한다) —
읽은 파일 이름은 상태 파일(`state/gdelt_news_files.json`)에 남겨 다시 받지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

from collector import config, db
from collector.console import utf8_stdio
from collector.policy_news import upsert

SOURCE = "gdelt"
URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.translation.gkg.csv.zip"
UA = {"User-Agent": "Qurious-collector/0.1 (student team project; news metadata only)"}
STATE_PATH = config.STATE_DIR / "gdelt_news_files.json"
KST = timezone(timedelta(hours=9))

#: 15분 파일은 그 시각 뒤 약 15분에 올라온다 — 이보다 최근 파일은 아직 없을 수 있어 부르지 않는다.
LAG_MINUTES = 30
#: 이만큼 지나도 404 면 GDELT 에 그 파일이 없다고 보고 「없음」 으로 적는다(다시 부르지 않는다).
MISSING_AFTER_HOURS = 6
#: 상태 파일에 남기는 기간 — 이보다 오래된 파일 이름은 지운다(되받기는 backfill 로).
KEEP_DAYS = 14
SLEEP = 1.0

#: GKG 2.1 칸 번호(탭으로 나눈 27칸) — GDELT GKG 2.1 코드북.
C_DATE, C_COLLECTION, C_DOMAIN, C_URL, C_TRANSLATION, C_EXTRAS = 1, 2, 3, 4, 25, 26

#: 기사가 아닌 커뮤니티 · 블로그 주소 — 2026-10-05 표본에서 네이트판(pann.nate.com)이 섞였다. 처음 목록이다(보이면 늘린다).
DENY_HOST = re.compile(r"(^|\.)(pann\.nate\.com|blog\.|cafe\.|dcinside\.com|theqoo\.net|fmkorea\.com|clien\.net|"
                       r"ppomppu\.co\.kr|instiz\.net|ruliweb\.com|bobaedream\.co\.kr|mlbpark|todayhumor\.co\.kr|"
                       r"tistory\.com|brunch\.co\.kr|velog\.io)", re.I)
_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)

csv.field_size_limit(1 << 30)


class GdeltMissing(RuntimeError):
    """그 15분 파일이 (아직) 없다 — HTTP 404."""


def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ==================================================
# 1. 원자료 읽기 — 네트워크 없이 시험한다(TC-GD)
# ==================================================
def kst_from_gdelt(stamp: str) -> str:
    """V2.1DATE 「YYYYMMDDHHMMSS」(UTC) → 「YYYY-MM-DDTHH:MM:SS+09:00」. 못 읽으면 빈칸."""
    try:
        t = datetime.strptime(stamp.strip(), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return t.astimezone(KST).isoformat(timespec="seconds")


def host_of(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/:?#]+)", url or "", re.I)
    return (m.group(1) if m else "").lower()


def parse_gkg(text: str) -> List[Dict[str, object]]:
    """번역 GKG 15분 파일 글 → 한국어 원문 기사 행들(`news_item` 칸 · 받은 시각 칸은 빼고).

    한국어 원문 = 번역 정보 칸에 `srclc:kor`. 수집 경로가 1(WEB)이 아니거나 · 제목이 없거나 · 커뮤니티 주소면 버린다.
    같은 주소가 한 파일에 두 번 오면 하나만.
    """
    out: Dict[str, Dict[str, object]] = {}
    for r in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if len(r) <= C_EXTRAS or "srclc:kor" not in (r[C_TRANSLATION] or "") or r[C_COLLECTION].strip() != "1":
            continue
        url = r[C_URL].strip()
        host = host_of(url)
        if not host or DENY_HOST.search(host):
            continue
        m = _TITLE.search(r[C_EXTRAS] or "")
        title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
        pub = kst_from_gdelt(r[C_DATE])
        if not title or not pub:
            continue
        nid = "gdelt:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        out.setdefault(nid, {
            "news_id": nid, "source": SOURCE, "title": title[:300], "subtitle": "", "body": "", "url": url,
            "publisher": (r[C_DOMAIN] or host).strip().lower(), "category": "", "kogl_type": "",
            "pub_at": pub, "embargo_at": "", "available_at": pub, "modified_at": "", "revision": 1,
        })
    return list(out.values())


def stamps_between(start: datetime, end: datetime) -> List[str]:
    """[start, end](UTC) 안의 15분 파일 이름 — 「YYYYMMDDHHMMSS」(:00 · :15 · :30 · :45)."""
    t = start.astimezone(timezone.utc).replace(second=0, microsecond=0)
    t -= timedelta(minutes=t.minute % 15)
    if t < start.astimezone(timezone.utc).replace(microsecond=0):
        t += timedelta(minutes=15)
    out = []
    while t <= end:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return out


# ==================================================
# 2. 상태 — 읽은 파일 이름
# ==================================================
def load_state(path: Path = STATE_PATH) -> Dict[str, int]:
    try:
        return {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).get("files", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def save_state(files: Dict[str, int], now: datetime, path: Path = STATE_PATH) -> None:
    """읽은 파일 이름 → 남긴 행 수(−1 = GDELT 에 없음). KEEP_DAYS 보다 오래된 이름은 지운다."""
    cut = (now.astimezone(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d%H%M%S")
    kept = {k: v for k, v in sorted(files.items()) if k >= cut}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated_at": now.astimezone(KST).isoformat(timespec="seconds"), "files": kept},
                              ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(path)


# ==================================================
# 3. 받기
# ==================================================
def http_get(url: str) -> bytes:
    import requests

    r = requests.get(url, headers=UA, timeout=120)
    if r.status_code == 404:
        raise GdeltMissing(url)
    r.raise_for_status()
    return r.content


def read_zip(blob: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(blob))
    return z.read(z.namelist()[0]).decode("utf-8", "replace")


def run_stamps(conn: sqlite3.Connection, stamps: Sequence[str], *, now: datetime, state: Dict[str, int],
               get: Callable[[str], bytes] = http_get, sleep: Callable[[float], None] = time.sleep,
               quiet: bool = True) -> Dict[str, int]:
    """파일마다 받아 한국어 줄만 `news_item` 에 쌓는다(파일 하나 = 트랜잭션 하나 · 상태는 그 뒤에 적는다).

    네트워크 오류는 그 파일을 건너뛰고(상태에 안 적어 다음에 다시) · 404 는 MISSING_AFTER_HOURS 가 지났으면 「없음」 으로 적는다.
    """
    out = {"files": 0, "rows": 0, "new": 0, "changed": 0, "missing": 0, "errors": 0, "later": 0}
    todo = [s for s in stamps if s not in state]
    for i, stamp in enumerate(todo, 1):
        if i > 1:
            sleep(SLEEP)
        try:
            text = read_zip(get(URL.format(stamp=stamp)))
        except GdeltMissing:
            age = now.astimezone(timezone.utc) - datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            if age > timedelta(hours=MISSING_AFTER_HOURS):
                state[stamp] = -1
                out["missing"] += 1
            else:
                out["later"] += 1
            continue
        except Exception as e:                # 조사 · 받기 실패 한 건이 하루치를 멈추지 않게 — 다음 실행이 다시 부른다
            out["errors"] += 1
            if not quiet:
                print(f"  ⚠️ {stamp} 건너뜀 — {type(e).__name__}: {str(e)[:120]}", flush=True)
            continue
        rows = parse_gkg(text)
        conn.execute("BEGIN IMMEDIATE")
        try:
            r = upsert(conn, rows, at=_now_iso())
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        state[stamp] = len(rows)
        out["files"] += 1
        out["rows"] += len(rows)
        out["new"] += r["new"]
        out["changed"] += r["changed"]
        if not quiet and i % 24 == 0:
            print(f"  {datetime.now():%H:%M:%S} 파일 {i}/{len(todo)} · 기사 {out['rows']:,}(새 {out['new']:,})", flush=True)
    return out


def daily(conn: sqlite3.Connection, now: datetime, *, hours: int = 30, get: Callable[[str], bytes] = http_get,
          sleep: Callable[[float], None] = time.sleep, state_path: Path = STATE_PATH, quiet: bool = True) -> Dict[str, int]:
    """지난 `hours` 시간(끝은 지금 − LAG_MINUTES)의 15분 파일 가운데 아직 안 읽은 것."""
    end = now.astimezone(timezone.utc) - timedelta(minutes=LAG_MINUTES)
    stamps = stamps_between(end - timedelta(hours=hours), end)
    state = load_state(state_path)
    out = run_stamps(conn, stamps, now=now, state=state, get=get, sleep=sleep, quiet=quiet)
    save_state(state, now, state_path)
    return out


def backfill(conn: sqlite3.Connection, since: date, until: date, *, now: datetime,
             get: Callable[[str], bytes] = http_get, sleep: Callable[[float], None] = time.sleep,
             state_path: Path = STATE_PATH, quiet: bool = True) -> Dict[str, int]:
    """날짜(UTC) 구간의 15분 파일 — 상태 파일에 있는 것은 건너뛴다."""
    start = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
    end = min(datetime(until.year, until.month, until.day, 23, 45, tzinfo=timezone.utc),
              now.astimezone(timezone.utc) - timedelta(minutes=LAG_MINUTES))
    state = load_state(state_path)
    out = run_stamps(conn, stamps_between(start, end), now=now, state=state, get=get, sleep=sleep, quiet=quiet)
    save_state(state, now, state_path)
    return out


def status_lines(conn: sqlite3.Connection) -> Iterator[str]:
    n, lo, hi = conn.execute("SELECT COUNT(*), MIN(pub_at), MAX(pub_at) FROM news_item WHERE source=?", (SOURCE,)).fetchone()
    yield f"GDELT 언론사 기사 {n:,}건 · {lo or '-'} ~ {hi or '-'}"
    for pub, c in conn.execute("SELECT publisher, COUNT(*) c FROM news_item WHERE source=? GROUP BY publisher "
                               "ORDER BY c DESC LIMIT 15", (SOURCE,)):
        yield f"  {pub} {c:,}"
    st = load_state()
    yield f"  읽은 파일 {sum(1 for v in st.values() if v >= 0):,} · GDELT 에 없음 {sum(1 for v in st.values() if v < 0)}"


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.gdelt_news", description="GDELT 한국어 원문 기사 메타데이터")
    sub = p.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("daily", help="지난 몇 시간의 15분 파일(기본 30시간) — 러너 단계")
    d.add_argument("--hours", type=int, default=30)
    d.add_argument("--quiet", action="store_true")
    b = sub.add_parser("backfill", help="날짜(UTC) 구간의 15분 파일")
    b.add_argument("--from", dest="bgn", required=True, help="YYYYMMDD(UTC)")
    b.add_argument("--to", dest="end", default="", help="YYYYMMDD(UTC · 비우면 시작일 하루)")
    sub.add_parser("status")
    a = p.parse_args(argv)
    conn = db.connect()
    now = datetime.now(KST)
    try:
        if a.mode == "daily":
            r = daily(conn, now, hours=a.hours, quiet=a.quiet)
        elif a.mode == "backfill":
            since = datetime.strptime(a.bgn, "%Y%m%d").date()
            until = datetime.strptime(a.end, "%Y%m%d").date() if a.end else since
            r = backfill(conn, since, until, now=now, quiet=False)
        else:
            for ln in status_lines(conn):
                print(ln)
            return 0
        print(f"  GDELT — 파일 {r['files']} · 기사 {r['rows']:,} · 새 {r['new']:,} · 고침 {r['changed']} · "
              f"없음 {r['missing']} · 다음에 {r['later']} · 실패 {r['errors']}")
        return 0 if not r["errors"] or r["files"] else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
