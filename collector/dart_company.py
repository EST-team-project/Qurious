"""DART 기업개황 업종코드 · 한국표준산업분류(KSIC) — 분봉 유니버스 351곳의 업종 칸 (할 일 ①-05 · G2 · 2026-10-24).

    python -m collector.dart_company weekly [--quiet] [--max-calls 500]   러너 단계 — 7일에 한 번 전체 · 그 밖의 날은 새로 든 회사만
    python -m collector.dart_company refresh [--max-calls N]               7일 판정 없이 지금 전체 다시
    python -m collector.dart_company seed --raw-dir <폴더> [--ksic-dir <폴더>]   10-22 일회 수집 원문(gz) · KSIC 엑셀로 채움 — 네트워크 0회
    python -m collector.dart_company ksic-load [--ksic-dir <폴더>]          KSIC 분류체계 엑셀 → ksic_code 표(네트워크 0회)
    python -m collector.dart_company status

무엇을 받나
-----------
**업종코드** — 기업개황(company.json · 회사 하나에 한 번)의 `induty_code`. 업종코드는 KSIC 코드이고 자릿수가 회사마다 다르다
(2026-10-22 일회 수집 351곳: 5자리 191 · 3자리 110 · 4자리 50 — 세세 · 소 · 세분류). 회사가 업종을 바꿀 때만 바뀌므로 **7일에 한 번
전체**를 다시 받고(사용자 결정 2026-10-24 「7일에 한 번 전체」 · 약 351회 · 90초), 그 밖의 날은 유니버스에 새로 든 회사만 받는다.
칸 값이 바뀌면 **새 판 한 줄**(같으면 `last_seen_at` 만 고친다) — 지금 판 = 회사마다 `last_seen_at` 이 가장 늦은 줄(`current`).

**KSIC** — 통계분류포털 고시 첨부 엑셀 「분류체계(대-중-소-세-세세 구분)」(11차 · 10차 시트)를 읽은 코드표. 고시 개정 때만 바뀐다
(10차 2017-07-01 · 11차 2024-07-01 시행 — 7년). 그래서 매주 받지 않고 **원본 두 파일의 지문만 대조**한다 — 7일 전체 회차에
받아 보고, 지문이 바뀌었으면 표를 다시 읽고 경고(종료코드 10 · 관제 🟡)로 사람에게 알린다. 받지 못해도 경고(조용한 0건 금지).

유니버스
--------
수집 DB `intraday_universe` 의 마지막 판(판 이름 끝 날짜가 가장 늦은 판 · 같은 날이면 이름이 큰 판)에서 ETF 를 뺀 종목 → DART
고유번호(`dart_corp_code.json`). 2026-10-24 지금은 u2-20260930 → 351곳(코스피 201 · 코스닥 150) — 일회 수집과 같다.
전체 재무제표 단계(`collector/financials_full.py`)도 이 함수를 쓴다(두 단계가 같은 351곳을 본다).

개인 칸을 남기지 않는다
-----------------------
응답에는 대표자 이름 · 법인/사업자 등록번호 · 주소 · 전화 · 팩스가 들어 있다. 표에는 그 칸을 넣지 않고(`KEEP` 밖), 응답 원문도
`raw_response`(HF 백업 대상)에 남기지 않는다 — 지문(`raw_sha256`)만 둔다. 2026-10-22 일회 수집과 같은 규칙이다.

DART 호출
---------
`collector.sources.dart._get`(키를 붙이고 오류 글에서 가림 · 간격 0.25초) · 상태 020(하루 한도)이면 그 자리에서 멈춘다(종료코드 3 —
다음 회차가 이어서). 호출 상한은 러너가 준다(`--max-calls` · 회차 DART 단계 몫 하루 3,000 안 — 사용자 결정 2026-10-24).

종료코드 — 0 끝 · 1 회사 몇 곳 실패(받은 것은 저장) · 3 한도 · 상한에서 멈춤 · 10 KSIC 원본이 바뀌었거나 확인 못 함(경고) · 78 키 없음
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from collector import config, db, raw_store
from collector.console import utf8_stdio
from collector.ratelimit import RateLimiter
from collector.sources import dart

COMPANY_URL = "https://opendart.fss.or.kr/api/company.json"

#: 표에 남기는 칸 — 대표자(ceo_nm) · 법인 등록번호(jurir_no) · 사업자 등록번호(bizr_no) · 주소(adres) · 전화(phn_no) · 팩스(fax_no)는 뺀다.
KEEP: Tuple[str, ...] = ("stock_code", "corp_name", "corp_name_eng", "stock_name", "corp_cls", "induty_code", "est_dt",
                         "acc_mt", "hm_url", "ir_url")
DROPPED: Tuple[str, ...] = ("ceo_nm", "jurir_no", "bizr_no", "adres", "phn_no", "fax_no")

#: 전체를 다시 받는 간격(일) — 사용자 결정 2026-10-24.
FULL_EVERY_DAYS = 7

#: KSIC 원본 — 통계분류포털 첨부(고시 제2024-2호). 파일 이름이 두 꼴로 올라와 있다(가운데 띄어쓰기 · 2026-10-22 실측) — 차례로 떠 본다.
KSIC_DIR = config.DATA_DIR / "ksic"
KSIC_BASE = "http://kssc.kostat.go.kr/ksscNew_web/upload/"
KSIC_FILES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("ksic11_체계.xlsx", ("7.한국표준산업분류 제11차 개정 분류체계(대-중-소-세-세세 구분) _20240626043559.xlsx",
                          "7.한국표준산업분류 제11차 개정 분류체계(대-중-소-세-세세 구분)_20240626043559.xlsx")),
    ("ksic11_10_연계표.xlsx", ("4.한국표준산업분류 제11차-제10차 연계표_20240626043559.xlsx",
                             "4.한국표준산업분류 제11차-제10차 연계표 _20240626043559.xlsx")),
)
#: 코드표를 읽는 파일(연계표는 원본 지문 대조만 — 표로 읽지 않는다).
KSIC_TABLE_FILE = "ksic11_체계.xlsx"
KSIC_LEVELS = ("대분류", "중분류", "소분류", "세분류", "세세분류")

EX_STOPPED = 3
EX_KSIC_WARN = 10
EX_CONFIG = 78

#: ingest_day 에 남기는 상태 열쇠 — 전체 회차 시각 · KSIC 원본 지문.
STATE_SOURCE = "dart_company"
STATE_FULL = "full"
KSIC_SOURCE = "ksic_file"


def _now() -> str:
    return raw_store.now_kst_iso()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ==================================================
# 1. 유니버스 — 분봉 유니버스 마지막 판 · ETF 뺌 → 고유번호
# ==================================================
def latest_universe_version(conn: sqlite3.Connection) -> str:
    """판 이름 끝의 날짜(YYYYMMDD)가 가장 늦은 판 · 같은 날이면 이름이 큰 판(u2 > u1). 표가 비면 빈 글."""
    names = [r[0] for r in conn.execute("SELECT DISTINCT version FROM intraday_universe")]
    if not names:
        return ""
    return max(names, key=lambda v: (v.rsplit("-", 1)[-1], v))


def universe(conn: sqlite3.Connection, corp_map: Optional[Dict] = None) -> Tuple[str, List[Tuple[str, str]], List[str]]:
    """(판, [(종목코드, 고유번호)], 고유번호를 모르는 종목). 차례는 고유번호."""
    ver = latest_universe_version(conn)
    if not ver:
        return "", [], []
    syms = sorted({r[0] for r in conn.execute(
        "SELECT symbol FROM intraday_universe WHERE version=? AND market <> 'ETF'", (ver,))})
    m = corp_map if corp_map is not None else json.loads(config.DART_CORP_CODE_PATH.read_text(encoding="utf-8"))
    pairs = sorted(((s, m[s][0]) for s in syms if s in m and m[s] and m[s][0]), key=lambda x: x[1])
    missing = [s for s in syms if not (s in m and m[s] and m[s][0])]
    return ver, pairs, missing


# ==================================================
# 2. 기업개황 — 네트워크 없이 시험한다(TC-CI)
# ==================================================
def keep_fields(doc: Dict) -> Dict[str, str]:
    """응답 → 남기는 칸만(빈칸은 빈 글 · 앞뒤 공백 정리). 개인 칸은 여기서 떨어진다."""
    return {k: " ".join(str(doc.get(k) or "").split()) for k in KEEP}


def fields_sha(fields: Dict[str, str]) -> str:
    """남기는 칸의 지문 — 칸 차례에 상관없이 같은 값이면 같은 지문(판을 가르는 열쇠)."""
    return _sha(json.dumps({k: fields.get(k, "") for k in KEEP}, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def upsert_company(conn: sqlite3.Connection, corp_code: str, fields: Dict[str, str], *, at: str, raw_sha256: str,
                   universe_version: str) -> str:
    """'new'(그 회사 첫 줄) · 'changed'(칸 값이 바뀜 — 새 판 한 줄) · 'same'(지금 판 그대로 — last_seen_at 만). 트랜잭션은 부르는 쪽."""
    fsha = fields_sha(fields)
    cur = current(conn, corp_code)
    if cur is not None and cur["fields_sha256"] == fsha:
        conn.execute("UPDATE dart_company SET last_seen_at=?, universe=? WHERE corp_code=? AND fields_sha256=?",
                     (at, universe_version, corp_code, fsha))
        return "same"
    old = conn.execute("SELECT 1 FROM dart_company WHERE corp_code=? AND fields_sha256=?", (corp_code, fsha)).fetchone()
    if old:   # 예전 판으로 되돌아옴(A → B → A) — 그 판의 마지막 본 시각만 고친다(처음 본 시각은 그대로)
        conn.execute("UPDATE dart_company SET last_seen_at=?, universe=? WHERE corp_code=? AND fields_sha256=?",
                     (at, universe_version, corp_code, fsha))
    else:
        conn.execute(
            f"INSERT INTO dart_company (corp_code, fields_sha256, {', '.join(KEEP)}, universe, first_seen_at, last_seen_at, "
            f"raw_sha256) VALUES ({', '.join('?' * (len(KEEP) + 6))})",
            (corp_code, fsha, *[fields[k] for k in KEEP], universe_version, at, at, raw_sha256))
    return "new" if cur is None else "changed"


def current(conn: sqlite3.Connection, corp_code: str) -> Optional[sqlite3.Row]:
    """그 회사의 지금 판 — last_seen_at 이 가장 늦은 줄(같으면 처음 본 시각이 늦은 줄)."""
    return conn.execute("SELECT * FROM dart_company WHERE corp_code=? ORDER BY last_seen_at DESC, first_seen_at DESC LIMIT 1",
                        (corp_code,)).fetchone()


@dataclass
class Tally:
    mode: str = ""
    calls: int = 0
    new: int = 0
    changed: int = 0
    same: int = 0
    failed: List[str] = field(default_factory=list)
    stopped: str = ""
    ksic: str = ""            # 같음 · 바뀜 · 확인 못 함 · (안 봄)
    ksic_warn: bool = False
    next_full: str = ""       # 다음 전체 회차 날(YYYY-MM-DD)


def fetch_company(limiter: RateLimiter, session, corp_code: str) -> Tuple[Dict, bytes]:
    """한 회사 — (응답 문서, 원문 바이트). 020 은 DartQuotaExceeded · 그 밖의 오류 상태는 DartError."""
    r = dart._get(limiter, COMPANY_URL, {"corp_code": corp_code}, session=session)  # noqa: SLF001 — 같은 키 · 간격 규칙
    if r.status_code != 200:
        raise dart.DartError(f"기업개황 HTTP {r.status_code} ({corp_code})")
    body = r.content
    doc = json.loads(body.decode("utf-8"))
    st = str(doc.get("status", ""))
    dart._check_status(st, str(doc.get("message", "")), f"기업개황 {corp_code}")  # noqa: SLF001
    if st != dart.DART_OK:
        raise dart.DartError(f"기업개황 자료 없음 ({corp_code} · status {st})")
    return doc, body


def last_full(conn: sqlite3.Connection) -> Optional[datetime]:
    r = conn.execute("SELECT updated_at FROM ingest_day WHERE source=? AND bas_dt=? AND status='done'",
                     (STATE_SOURCE, STATE_FULL)).fetchone()
    return datetime.fromisoformat(r[0]) if r and r[0] else None


def _mark(conn: sqlite3.Connection, source: str, key: str, status: str, rows: int, message: str = "",
          at: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO ingest_day (source, bas_dt, status, rows, attempts, updated_at, message) VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT(source, bas_dt) DO UPDATE SET status=excluded.status, rows=excluded.rows, "
        "attempts=ingest_day.attempts+1, updated_at=excluded.updated_at, message=excluded.message",
        (source, key, status, rows, at or _now(), message[:500]))


def run(conn: sqlite3.Connection, *, full: Optional[bool] = None, max_calls: Optional[int] = None, now: Optional[datetime] = None,
        session=None, limiter: Optional[RateLimiter] = None, corp_map: Optional[Dict] = None,
        fetch_ksic=None) -> Tally:
    """weekly(full=None — 7일 판정) · refresh(full=True). 받은 것은 회사마다 커밋한다(멈춰도 받은 만큼 남는다)."""
    now = now or datetime.now().astimezone()
    lim = limiter or RateLimiter(config.DART_SLEEP, reserve=config.DART_RESERVE, name="DART")
    sess = session or requests.Session()
    ver, pairs, missing = universe(conn, corp_map)
    t = Tally()
    if full is None:
        lf = last_full(conn)
        full = lf is None or now - lf >= timedelta(days=FULL_EVERY_DAYS)
    lf_done = last_full(conn)
    have = {r[0] for r in conn.execute("SELECT DISTINCT corp_code FROM dart_company")}
    targets = pairs if full else [(s, c) for s, c in pairs if c not in have]
    t.mode = "전체" if full else "새 회사만"
    for stock, corp in targets:
        if max_calls is not None and t.calls >= max_calls:
            t.stopped = f"이번 실행의 호출 상한 {max_calls:,}회 — 다음 회차가 이어서 받는다"
            break
        try:
            t.calls += 1
            doc, body = fetch_company(lim, sess, corp)
        except dart.DartQuotaExceeded as e:
            t.stopped = str(e).splitlines()[0]
            break
        except (dart.DartError, requests.RequestException, ValueError) as e:
            t.failed.append(f"{stock}({corp}): {str(e).splitlines()[0][:160]}")
            continue
        fields = keep_fields(doc)
        conn.execute("BEGIN IMMEDIATE")
        try:
            got = upsert_company(conn, corp, fields, at=_now(), raw_sha256=_sha(body), universe_version=ver)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        setattr(t, got, getattr(t, got) + 1)
    if full and not t.stopped:
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, STATE_SOURCE, STATE_FULL, "done", len(targets) - len(t.failed),
              f"universe={ver} corps={len(pairs)} no_corp_code={len(missing)} failed={len(t.failed)}",
              at=now.isoformat(timespec="seconds"))
        conn.execute("COMMIT")
        t.ksic, t.ksic_warn = check_ksic(conn, fetch=fetch_ksic)
        t.next_full = (now + timedelta(days=FULL_EVERY_DAYS)).date().isoformat()
    else:
        t.ksic = "(안 봄 — 7일 전체 회차에만)"
        t.next_full = (lf_done + timedelta(days=FULL_EVERY_DAYS)).date().isoformat() if lf_done else "다음 회차"
    if missing:
        t.failed.extend(f"{s}: 고유번호 매핑에 없음" for s in missing)
    return t


# ==================================================
# 3. KSIC — 엑셀 읽기 · 원본 지문 대조
# ==================================================
def parse_ksic_xlsx(path: Path) -> List[Dict[str, str]]:
    """분류체계 엑셀 → 코드표 줄. 시트마다 개정 차수(이름에 11차 · 10차) · 앞 세 줄은 머리(제목 · 단계 · 코드/항목명).

    열은 (코드, 항목명) 다섯 쌍 — 대 · 중 · 소 · 세 · 세세. 위 단계 칸은 새 값이 나올 때만 차 있으므로 지나온 값을 들고 간다.
    2026-10-22 일회 수집의 읽기와 같다(11차: 21 · 77 · 234 · 501 · 1,205 — 공식 수와 같음).
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out: List[Dict[str, str]] = []
    try:
        for ws in wb.worksheets:
            rev = "11" if "11차" in ws.title else ("10" if "10차" in ws.title else ws.title)
            cur = [""] * 5
            seen = set()
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                if i < 3:
                    continue
                cells = [("" if c is None else str(c).strip()) for c in list(r)[:10]] + [""] * 10
                for li in range(5):
                    code, name = cells[li * 2], cells[li * 2 + 1]
                    if not code:
                        continue
                    cur[li] = code
                    for lj in range(li + 1, 5):
                        cur[lj] = ""
                    if (rev, li, code) in seen:
                        continue
                    seen.add((rev, li, code))
                    out.append({"revision": rev, "level": KSIC_LEVELS[li], "code": code, "name": name,
                                "parent_code": cur[li - 1] if li > 0 else "", "section": cur[0]})
    finally:
        wb.close()
    return out


def load_ksic(conn: sqlite3.Connection, ksic_dir: Path = KSIC_DIR) -> Dict[str, int]:
    """코드표를 통째로 다시 읽는다(개정은 통째로 바뀐다 — 고친 줄만 맞추지 않는다). 차수 · 단계별 줄 수를 돌려준다."""
    p = Path(ksic_dir) / KSIC_TABLE_FILE
    rows = parse_ksic_xlsx(p)
    if not rows:
        raise ValueError(f"KSIC 엑셀에서 코드를 한 줄도 읽지 못했다 — {p.name} 의 꼴이 바뀌었는지 본다")
    sha = _sha(p.read_bytes())
    at = _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM ksic_code")
        conn.executemany(
            "INSERT INTO ksic_code (revision, level, code, name, parent_code, section, loaded_at, source_sha256) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(r["revision"], r["level"], r["code"], r["name"], r["parent_code"], r["section"], at, sha) for r in rows])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    cnt: Dict[str, int] = {}
    for r in rows:
        k = f"{r['revision']}차 {r['level']}"
        cnt[k] = cnt.get(k, 0) + 1
    return cnt


def _download_ksic(names: Sequence[str]) -> Optional[Tuple[str, bytes]]:
    """두 꼴의 이름을 차례로 떠 본다 — xlsx(zip) 머리(PK)가 오면 그 주소와 바이트."""
    for nm in names:
        url = KSIC_BASE + urllib.parse.quote(nm)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Qurious collector)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if body[:2] == b"PK":
                return url, body
        except Exception:  # noqa: BLE001 — 다음 꼴로
            continue
    return None


def check_ksic(conn: sqlite3.Connection, *, fetch=None, ksic_dir: Path = KSIC_DIR) -> Tuple[str, bool]:
    """원본 두 파일을 받아 지문 대조 — ('같음' | '바뀜 …' | '확인 못 함 …', 경고인가). 바뀌었으면 파일을 바꿔 두고 표를 다시 읽는다."""
    fetch = fetch or _download_ksic
    notes, warn = [], False
    for local, names in KSIC_FILES:
        got = fetch(names)
        old = conn.execute("SELECT message FROM ingest_day WHERE source=? AND bas_dt=?", (KSIC_SOURCE, local)).fetchone()
        old_sha = (old[0].split("sha256=", 1)[1].split()[0] if old and "sha256=" in (old[0] or "") else "")
        if not got:
            notes.append(f"{local} 확인 못 함(받지 못함)")
            warn = True
            continue
        url, body = got
        sha = _sha(body)
        if old_sha and sha != old_sha:
            notes.append(f"{local} 바뀜({old_sha[:12]} → {sha[:12]})")
            warn = True
            Path(ksic_dir).mkdir(parents=True, exist_ok=True)
            (Path(ksic_dir) / local).write_bytes(body)
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, KSIC_SOURCE, local, "done", len(body), f"sha256={sha} bytes={len(body)} url={url}")
        conn.execute("COMMIT")
    if any("바뀜" in n and KSIC_TABLE_FILE in n for n in notes):
        load_ksic(conn, ksic_dir)
    return ("같음" if not notes else " · ".join(notes)), warn


# ==================================================
# 4. 일회 수집본으로 채우기(네트워크 0회)
# ==================================================
def seed(conn: sqlite3.Connection, raw_dir: Path, *, ksic_dir: Optional[Path] = None,
         corp_map: Optional[Dict] = None) -> Dict[str, int]:
    """10-22 일회 수집의 기업개황 원문(`raw_company/<고유번호>.json.gz`)을 표로 — 받은 시각은 파일 시각. 개인 칸은 떨어지고 원문은
    남기지 않는다. KSIC 엑셀이 있으면 수집 폴더(`KSIC_DIR`)로 복사해 표를 읽고 원본 지문을 상태로 남긴다. 다시 돌려도 같은 줄."""
    ver, pairs, _missing = universe(conn, corp_map)
    want = {c for _s, c in pairs}
    out = {"files": 0, "rows": 0, "skipped": 0, "ksic_rows": 0}
    latest = None
    for f in sorted(Path(raw_dir).glob("*.json.gz")):
        body = gzip.decompress(f.read_bytes())
        doc = json.loads(body.decode("utf-8"))
        corp = f.name.split(".")[0]
        out["files"] += 1
        if str(doc.get("status")) != dart.DART_OK or corp not in want:
            out["skipped"] += 1
            continue
        at = datetime.fromtimestamp(f.stat().st_mtime).astimezone().isoformat(timespec="seconds")
        latest = max(latest or at, at)
        conn.execute("BEGIN IMMEDIATE")
        try:
            got = upsert_company(conn, corp, keep_fields(doc), at=at, raw_sha256=_sha(body), universe_version=ver)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        out["rows"] += got in ("new", "changed")
    if latest:   # 일회 수집 시각을 「마지막 전체」 로 — 다음 전체는 그 7일 뒤
        conn.execute("BEGIN IMMEDIATE")
        _mark(conn, STATE_SOURCE, STATE_FULL, "done", out["files"] - out["skipped"],
              f"seed universe={ver} from={Path(raw_dir).name}", at=latest)
        conn.execute("COMMIT")
    if ksic_dir:
        KSIC_DIR.mkdir(parents=True, exist_ok=True)
        for local, _names in KSIC_FILES:
            src = Path(ksic_dir) / local
            if src.exists():
                if Path(ksic_dir).resolve() != KSIC_DIR.resolve():
                    shutil.copy2(src, KSIC_DIR / local)
                b = src.read_bytes()
                conn.execute("BEGIN IMMEDIATE")
                _mark(conn, KSIC_SOURCE, local, "done", len(b), f"sha256={_sha(b)} bytes={len(b)} url=seed")
                conn.execute("COMMIT")
        if (KSIC_DIR / KSIC_TABLE_FILE).exists():
            out["ksic_rows"] = sum(load_ksic(conn, KSIC_DIR).values())
    return out


# ==================================================
# 5. 상태 · 명령
# ==================================================
def status_lines(conn: sqlite3.Connection) -> List[str]:
    n_corp, n_rows = conn.execute("SELECT COUNT(DISTINCT corp_code), COUNT(*) FROM dart_company").fetchone()
    lens: Dict[int, int] = {}
    for (code,) in conn.execute(
            "SELECT d.induty_code FROM dart_company d WHERE d.last_seen_at = (SELECT MAX(last_seen_at) FROM dart_company e "
            "WHERE e.corp_code = d.corp_code)"):
        lens[len(code or "")] = lens.get(len(code or ""), 0) + 1
    lf = last_full(conn)
    k = dict(conn.execute("SELECT revision, COUNT(*) FROM ksic_code GROUP BY revision").fetchall())
    files = conn.execute("SELECT bas_dt, message, updated_at FROM ingest_day WHERE source=? ORDER BY bas_dt",
                         (KSIC_SOURCE,)).fetchall()
    out = [f"  기업 업종 {n_corp:,}곳 · 판 {n_rows:,}줄(바뀐 판 {n_rows - n_corp:,}) · 업종코드 자릿수 "
           + " · ".join(f"{L}자리 {c}" for L, c in sorted(lens.items())),
           f"  마지막 전체 {lf.isoformat(timespec='minutes') if lf else '-'} · 다음 전체 "
           + ((lf + timedelta(days=FULL_EVERY_DAYS)).date().isoformat() if lf else "다음 회차"),
           "  KSIC 코드표 " + (" · ".join(f"{r}차 {c:,}줄" for r, c in sorted(k.items(), reverse=True)) or "없음")]
    for name, msg, at in files:
        sha = (msg or "").split("sha256=", 1)[-1][:12]
        out.append(f"    원본 {name} · 지문 {sha} · 확인 {at[:16]}")
    return out


def _report(t: Tally) -> None:
    if t.mode == "새 회사만" and t.calls == 0:
        print(f"기업 업종 — 건너뜀(7일 전체 회차가 아니고 유니버스에 새로 든 회사 0곳) · 다음 전체 {t.next_full}")
        return
    print(f"기업 업종 — {t.mode} · 부름 {t.calls:,} · 새 {t.new} · 바뀜 {t.changed} · 같음 {t.same}"
          + (f" · 실패 {len(t.failed)}" if t.failed else "") + f" · KSIC 원본 {t.ksic}")
    for e in t.failed[:10]:
        print(f"  🟡 {e}")
    if t.ksic_warn:
        print(f"🟡 KSIC 원본 {t.ksic} — 통계분류포털 고시를 사람이 확인한다(개정이면 코드표 · 섹터 잇기 표를 다시 본다)")
    if t.stopped:
        print(f"\n멈춤: {t.stopped}")


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python -m collector.dart_company",
                                description="DART 기업개황 업종코드(분봉 유니버스 351곳) · KSIC 코드표")
    p.add_argument("mode", choices=["weekly", "refresh", "seed", "ksic-load", "status"])
    p.add_argument("--max-calls", type=int, default=500)
    p.add_argument("--raw-dir", default="", help="seed — 일회 수집 기업개황 원문 폴더(raw_company)")
    p.add_argument("--ksic-dir", default="", help="seed · ksic-load — KSIC 엑셀 폴더(비우면 수집 폴더의 ksic/)")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--db", default="", help="(시험용) 수집 DB 대신 쓸 SQLite 파일")
    a = p.parse_args(argv)
    conn = db.connect(Path(a.db) if a.db else None)
    try:
        if a.mode == "status":
            for ln in status_lines(conn):
                print(ln)
            return 0
        if a.mode == "ksic-load":
            cnt = load_ksic(conn, Path(a.ksic_dir) if a.ksic_dir else KSIC_DIR)
            print("KSIC 코드표 — " + " · ".join(f"{k} {v:,}" for k, v in cnt.items()))
            return 0
        if a.mode == "seed":
            if not a.raw_dir:
                print("멈춤: seed 에는 --raw-dir(일회 수집 raw_company 폴더)가 있어야 한다")
                return 2
            out = seed(conn, Path(a.raw_dir), ksic_dir=Path(a.ksic_dir) if a.ksic_dir else None)
            print(f"기업 업종 채우기 — 원문 {out['files']} · 넣은 판 {out['rows']} · 건너뜀 {out['skipped']} · "
                  f"KSIC {out['ksic_rows']:,}줄(네트워크 0회)")
            return 0
        try:
            config.dart_key()
        except config.MissingKey as e:
            print(f"🔴 DART 인증키가 없어 받지 않는다 — {e}")
            return EX_CONFIG
        t = run(conn, full=True if a.mode == "refresh" else None, max_calls=a.max_calls)
        _report(t)
        if t.stopped:
            return EX_STOPPED
        if t.ksic_warn:
            return EX_KSIC_WARN
        return 1 if [x for x in t.failed if "매핑에 없음" not in x] else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
