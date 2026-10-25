"""여러 PC 맞추기 — 원격 백업(HF `krx-daily-market` main)이 이 PC 수집 DB 보다 앞서면 바뀐 파티션만 받아 갈아 끼운다
(설계 `docs/phase-3/02-design/system/여러PC-회차-설계.md` 5절 · 사용자 결정 2026-10-25 「바뀐 파일만 갈아 끼우기」).

이 파일이 답하는 질문은 하나다
------------------------------
**"다른 PC 가 돌고 올린 뒤, 이 PC 의 수집 DB 를 원격과 같게 — 이 PC 만의 변경은 잃지 않고 — 어떻게 만드나."**

세 판을 견준다 — **기준**(이 PC 가 마지막으로 원격과 같았던 때의 파일 목록 · ``state/hf_sync_base.json`` · 올리기와 맞추기가 끝날
때 쓴다) · **원격**(main 머리의 ``meta/manifest.json``) · **이 PC**(수집 DB 파티션의 내용 지문 — 내보내기와 같은 셈 ``_content_sig``)::

    원격 = 기준                          → 그대로(이 PC 의 변경은 다음 올리기가 싣는다)
    원격 ≠ 기준 · 이 PC = 원격            → 받기만(DB 는 이미 같다 — 파일 · 목록만)
    원격 ≠ 기준 · 이 PC = 기준 또는 빈 조각 → 갈아 끼움 — 지우고 원격 파일로 채워 내용 지문이 원격과 같을 때만 커밋
    원격 ≠ 기준 · 이 PC ≠ 기준             → 겹침 — 멈춘다(``discard_local`` 이면 원격 것으로 · 사람이 정한다)

응답 원문(``raw_response``)은 갈아 끼우지 않고 **없는 줄만 더한다** — 기본 키에 받은 시각이 들어 있어 덧붙이기만 하는 표라(``raw_store``
가 새 시각으로 넣는다) 합치기가 늘 맞고, 412MB 짜리 조각을 지웠다 다시 쓰지 않는다. 따라가는 PC(``mode="follow"``)는 복구용 표
(``restore_only`` — 원문 · 수집 상태)를 건너뛴다 — 앱이 읽지 않는 큰 표라 하루 받는 양이 약 730MB → 100MB 아래로 준다. 회차를 잡은
PC(``mode="lead"``)는 전부 맞춘다 — 그 PC 가 올리는 조각이 원격의 다른 PC 줄을 지우지 않게.

받는 파일은 원격 머리 SHA(40자)로 고정해 받고 sha256 을 매니페스트와 대조한다(가지 이름으로 받으면 망 오류 때 옛 캐시를 준다 — 조사
Q3). 갈아 끼우기는 파티션마다 한 트랜잭션이라 도중에 죽어도 그 조각은 앞 모습 그대로다. 수집 DB 가 아예 없는 새 PC 는 전부 받아
복원한다(``full``).

    python scripts/hf_sync.py status                 # 기준 · 원격 · 이 PC 를 견준다(원격을 읽기만 · 쓰지 않음)
    python scripts/daily_update.py sync              # 맞추기 — 러너 잠금 · 막는 때를 지킨다(이 파일의 pull 을 부른다)
    python scripts/daily_update.py sync --discard-local
    python scripts/daily_update.py sync --full       # 수집 DB 가 없는 새 PC
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402
from scripts import hf_dataset as hd  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")
REPO_ID = hd.REPO_ID

#: 기준 — 이 PC 가 마지막으로 원격과 같았던 때의 파일 목록(경로 → sha256 · 내용 지문 · 행 수). 올리기 · 맞추기가 끝날 때 쓴다.
BASE_PATH = config.STATE_DIR / "hf_sync_base.json"
#: 마지막 맞추기의 요약(status · 러너 회차 기록 · 앱이 읽는다).
LAST_PATH = config.STATE_DIR / "hf_sync_last.json"
#: 받는 파일을 잠시 두는 곳 — 수집 DB 와 같은 볼륨(옮기기가 원자적) · gitignore 된 data/ 아래.
STAGE_DIR = config.ROOT / "data" / "hf_sync_stage"

#: 덧붙이기만 하는 표 — 갈아 끼우지 않고 없는 줄만 더한다(머리말).
UNION_TABLES = frozenset({"raw_response"})
#: 겹침 — 이 PC 도 원격도 같은 조각을 바꿨다(사람이 정함 · sysexits EX_DATAERR).
EX_CONFLICT = 65
READ_TIMEOUT_S = 30


class SyncError(Exception):
    """맞추기를 이어 갈 수 없다 — 그 까닭 한 줄."""


@dataclass
class Part:
    """원격이 기준과 다른 조각 하나와 할 일 — adopt(받기만) · replace(갈아 끼움) · union(없는 줄만) · conflict · schema · skip."""
    path: str
    table: str
    part: Optional[str]
    action: str
    remote: Dict
    base: Optional[Dict]
    local_rows: int = 0
    local_sig: Optional[str] = None
    why: str = ""


def _now() -> str:
    return datetime.datetime.now(KST).isoformat(timespec="seconds")


def files_of(man: Dict) -> Dict[str, Dict]:
    """매니페스트의 파일 → {경로: 칸 + 표 이름}."""
    out: Dict[str, Dict] = {}
    for t, rec in (man.get("tables") or {}).items():
        for f in rec.get("files") or []:
            out[f["path"]] = dict(f, table=t)
    return out


def fp_of(files: Dict[str, Dict]) -> str:
    """파일 구성 지문 — ``hf_dataset._manifest_fp`` 와 같은 셈(경로 + sha256 · TC-HS-01 이 맞댄다)."""
    items = sorted((p, e.get("sha256", "")) for p, e in files.items())
    return hashlib.sha256(json.dumps(items).encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def load_base() -> Dict:
    return _read_json(BASE_PATH)


def _base_entry(e: Dict) -> Dict:
    return {k: e.get(k) for k in ("sha256", "sig", "rows", "bytes", "table")}


def save_base(files: Dict[str, Dict], main: Optional[str], *, by: str, partial: bool = False) -> Dict:
    """기준을 쓴다 — 이 PC 가 지금 원격(main ``main``)과 같다고 확인한 파일 목록.

    ``partial`` = 따라가기가 복구용 표를 건너뛰어 그 조각들은 옛 기준 그대로다 — 머리가 같아도 「같음」 으로 지나치지 않는다
    (그 PC 가 나중에 회차를 잡으면 전부 맞춰야 올릴 수 있다 · TC-HS-07).
    """
    clean = {p: _base_entry(e) for p, e in files.items()}
    base = {"schema": 1, "main": main, "fp": fp_of(clean), "at": _now(), "by": by, "partial": bool(partial),
            "files": clean}
    _write_json(BASE_PATH, base)
    return base


def after_upload(man: Dict, main: str) -> Dict:
    """올리기가 끝난 뒤(``hf_dataset.upload``) — 올린 매니페스트가 곧 원격이다. 그 목록을 기준으로."""
    return save_base(files_of(man), main, by="upload")


def bootstrap_base(local_man: Dict) -> Dict:
    """기준 파일이 없을 때(이 판 앞의 PC) — 이 PC 매니페스트의 올린 기록(``uploaded.files``)이 곧 마지막으로 원격과 같았던 목록이다.

    내용 지문(sig)은 지금 매니페스트의 그 파일이 올린 것과 같을 때만 안다 — 모르면 None(이 PC 도 바꾼 것으로 보아 겹침 쪽으로 기운다).
    """
    up = ((local_man.get("uploaded") or {}).get("files")) or {}
    if not up:
        return {}
    cur = files_of(local_man)
    files: Dict[str, Dict] = {}
    for p, sha in up.items():
        e = cur.get(p) or {}
        same = e.get("sha256") == sha
        files[p] = {"sha256": sha, "sig": e.get("sig") if same else None, "rows": e.get("rows") if same else None,
                    "bytes": e.get("bytes") if same else None, "table": e.get("table") or p.split("/", 1)[0]}
    return {"schema": 1, "main": (local_man.get("uploaded") or {}).get("commit"), "fp": fp_of(files), "at": None,
            "by": "bootstrap", "files": files}


def base_or_bootstrap() -> Dict:
    return load_base() or bootstrap_base(hd._load_manifest())


def make_api():
    """쓰기 토큰으로 HfApi(읽기도 같은 토큰 — 비공개 저장소) · 요청 시간 한도를 준다. 토큰은 찍지 않는다."""
    from huggingface_hub import HfApi

    from scripts import run_lease

    run_lease.set_timeouts()
    return HfApi(token=hd._token())


def remote_head(api) -> str:
    """원격 main 머리(40자) — 오류를 캐시로 덮지 않는 읽기(``repo_info``)."""
    sha = str(getattr(api.repo_info(REPO_ID, repo_type="dataset", revision="main", timeout=READ_TIMEOUT_S), "sha", "")
              or "")
    if len(sha) != 40:
        raise SyncError("원격 main 머리를 알 수 없다")
    return sha


def remote_manifest(api, sha: str) -> Dict:
    """원격 매니페스트 — 머리 SHA 로 고정해 받는다(바뀌지 않는 판이라 캐시가 맞다). 아직 없으면(처음 올리기 전) 빈 사전."""
    from huggingface_hub.errors import EntryNotFoundError

    try:
        p = api.hf_hub_download(REPO_ID, "meta/manifest.json", repo_type="dataset", revision=sha)
    except EntryNotFoundError:
        return {}
    man = json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(man, dict) or "tables" not in man:
        raise SyncError("원격 매니페스트가 깨졌다")
    return man


def _empty_remote(rman: Dict) -> bool:
    return not rman or not files_of(rman)


def behind(api, head: Optional[str] = None) -> Optional[str]:
    """원격이 이 PC 의 기준보다 앞섰나 — 앞섰으면 까닭 한 줄, 아니면 None(올리기 바로 앞 · ``hf_dataset.upload``).

    머리가 같으면 바로 None. 머리가 달라도 파일 구성이 기준과 같으면(카드 · 가지 쪽 커밋) None.
    """
    head = head or remote_head(api)
    base = base_or_bootstrap()
    if base and base.get("main") == head and not base.get("partial"):
        return None
    rman = remote_manifest(api, head)
    if _empty_remote(rman):
        return None                                           # 원격에 아직 데이터가 없다 — 처음 올리기
    if not base:
        return "이 PC 에 기준(마지막으로 원격과 같았던 목록)이 없다 — 먼저 맞춘다(python scripts/daily_update.py sync)"
    if fp_of(files_of(rman)) == base.get("fp"):
        return None
    return (f"원격(main {head[:8]})이 이 PC 의 기준({str(base.get('main') or '옛 판')[:8]})보다 앞섰다 — "
            f"먼저 맞춘다(python scripts/daily_update.py sync)")


def spec_for(table: str, rtab: Dict) -> Optional[Dict]:
    """조각을 고르는 명세 — 이 판 코드의 표 명세, 없으면 원격 매니페스트의 칸(연도 조각은 날짜 칸이 있어야 한다)."""
    spec = hd.TABLES.get(table)
    if spec:
        return spec
    mode = rtab.get("partition")
    if mode == "year" and not rtab.get("date_col"):
        return None
    return {"partition": mode, "partition_col": rtab.get("partition_col"), "date_col": rtab.get("date_col") or "",
            "sort": tuple(rtab.get("sort") or ())}


def remote_columns(rtab: Dict) -> Optional[List[str]]:
    """원격 매니페스트의 표 모양(DDL)이 말하는 칸 이름 — 메모리 DB 에 그 DDL 을 실행해 읽는다(DDL 이 없거나 깨졌으면 None)."""
    ddl = (rtab.get("ddl") or {}).get("table")
    if not ddl:
        return None
    mem = sqlite3.connect(":memory:")
    try:
        mem.execute(ddl)
        name = mem.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()[0]
        return [r[1] for r in mem.execute(f"PRAGMA table_info({name})")]
    except sqlite3.Error:
        return None
    finally:
        mem.close()


def plan(base: Dict, rman: Dict, conn: sqlite3.Connection, *, mode: str = "lead") -> List[Part]:
    """원격이 기준과 다른 조각마다 할 일 — 머리말의 표. ``mode="follow"`` 면 복구용 표는 건너뛴다(skip)."""
    bfiles = (base or {}).get("files") or {}
    out: List[Part] = []
    for path, r in sorted(files_of(rman).items()):
        b = bfiles.get(path)
        if b and b.get("sha256") == r.get("sha256"):
            continue                                          # 원격이 기준 그대로
        table = r["table"]
        rtab = rman["tables"][table]
        if mode == "follow" and (rtab.get("restore_only") or (hd.TABLES.get(table) or {}).get("restore_only")):
            out.append(Part(path, table, None, "skip", r, b, why="복구용 표 — 따라가는 PC 는 받지 않는다"))
            continue
        spec = spec_for(table, rtab)
        if spec is None:
            out.append(Part(path, table, None, "schema", r, b, why="이 판 코드가 모르는 표 — 코드를 먼저 맞춘다(git pull)"))
            continue
        part = hd._part_of(path, table, spec)
        if not hd._table_exists(conn, table):
            out.append(Part(path, table, part, "replace", r, b, why="이 PC 에 없는 표 — 원격 모양으로 만든다"))
            continue
        cols = hd._columns(conn, table)
        want = remote_columns(rtab)
        if want is not None and sorted(want) != sorted(c for c, _ in cols):
            out.append(Part(path, table, part, "schema", r, b,
                            why=f"{table} 표 모양이 원격과 다르다(이 PC {len(cols)}칸 · 원격 {len(want)}칸) — 코드를 먼저 맞춘다(git pull)"))
            continue
        rows = hd._count(conn, table, spec, part)
        sig = hd._content_sig(conn, table, spec, part, cols) if rows else None
        if rows and sig == r.get("sig"):
            act, why = "adopt", "이 PC 가 이미 원격과 같다"
        elif table in UNION_TABLES:
            act, why = "union", "덧붙이기만 하는 표 — 없는 줄만 더한다"
        elif rows == 0:
            act, why = "replace", "이 PC 에는 그 조각이 비었다"
        elif b and b.get("sig") and sig == b.get("sig"):
            act, why = "replace", "원격만 바뀌었다"
        else:
            act = "conflict"
            why = ("이 PC 도 그 조각을 바꿨다(기준과 다름 · 아직 올리지 않음)" if b and b.get("sig")
                   else "이 PC 의 기준을 모른다 — 이 PC 도 바꾼 것으로 본다")
        out.append(Part(path, table, part, act, r, b, rows, sig, why))
    return out


def _download(api, sha: str, parts: List[Part], stage: Path) -> Dict[str, Path]:
    """조각 파일을 머리 SHA 로 고정해 받아 sha256 을 매니페스트와 대조한다."""
    got: Dict[str, Path] = {}
    for p in parts:
        fp = Path(api.hf_hub_download(REPO_ID, p.path, repo_type="dataset", revision=sha, local_dir=str(stage)))
        if hd._sha256(fp) != p.remote.get("sha256"):
            raise SyncError(f"받은 파일의 sha256 이 원격 매니페스트와 다르다 — {p.path}")
        got[p.path] = fp
    return got


def _ensure_table(conn: sqlite3.Connection, table: str, rtab: Dict) -> None:
    if hd._table_exists(conn, table):
        return
    ddl = rtab.get("ddl") or {}
    if not ddl.get("table"):
        raise SyncError(f"원격 매니페스트에 {table} 표 모양(DDL)이 없다")
    conn.execute(ddl["table"])
    for stmt in ddl.get("indexes") or []:
        conn.execute(stmt)


def _apply_part(conn: sqlite3.Connection, p: Part, src: Path, rman: Dict) -> int:
    """조각 하나를 한 트랜잭션으로 — replace(지우고 채움 · 내용 지문이 원격과 같아야 커밋) · union(없는 줄만 · 원격 줄이 다 있어야)."""
    import pyarrow.parquet as pq

    rtab = rman["tables"][p.table]
    spec = spec_for(p.table, rtab)
    _ensure_table(conn, p.table, rtab)
    cols = hd._columns(conn, p.table)
    names = [c for c, _ in cols]
    pf = pq.ParquetFile(src)
    remote_names = list(pf.schema_arrow.names)
    if sorted(remote_names) != sorted(names):
        raise SyncError(f"{p.table} 표 모양이 원격과 다르다(이 PC {len(names)}칸 · 원격 {len(remote_names)}칸) — "
                        f"코드를 먼저 맞춘다(git pull)")
    verb = "INSERT OR IGNORE" if p.action == "union" else "INSERT OR REPLACE"
    ins = f"{verb} INTO {p.table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
    where, params = hd._part_where(spec, p.part)
    want_rows = int(p.remote.get("rows") or 0)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if p.action != "union":
            conn.execute(f"DELETE FROM {p.table}{where}", params)
        n = 0
        for batch in pf.iter_batches(batch_size=int(rtab.get("fetch_rows") or hd.FETCH_ROWS), columns=names):
            d = batch.to_pydict()
            conn.executemany(ins, zip(*[d[c] for c in names]))
            n += batch.num_rows
        if n != want_rows:
            raise SyncError(f"{p.path} 파일 행 수 {n:,} ≠ 원격 매니페스트 {want_rows:,}")
        if p.action == "union":
            have = hd._count(conn, p.table, spec, p.part)
            if have < want_rows:
                raise SyncError(f"{p.path} 합친 뒤 행 수 {have:,} 가 원격 {want_rows:,} 보다 적다")
        else:
            got = hd._content_sig(conn, p.table, spec, p.part, cols)
            if got != p.remote.get("sig"):
                raise SyncError(f"{p.path} 갈아 끼운 뒤 내용 지문이 원격과 다르다({got} ≠ {p.remote.get('sig')})")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return n


def merge_manifest(local: Dict, rman: Dict, applied: List[Part]) -> Dict:
    """이 PC 매니페스트에 받은 조각을 넣고, 원격에 있는 파일은 「올린 것」 으로 적는다 — 다음 증분 올리기가 그것을 다시 싣지 않게.

    이 PC 만 바꾼 조각(원격이 기준 그대로)의 줄은 그대로 둔다 — 그 파일은 올린 기록과 sha256 이 달라 다음 올리기가 싣는다.
    """
    out = json.loads(json.dumps(local)) if local else {k: v for k, v in rman.items() if k not in ("tables", "uploaded")}
    tables = out.setdefault("tables", {})
    for p in applied:
        rtab = rman["tables"][p.table]
        t = tables.get(p.table)
        if t is None:
            t = {k: v for k, v in rtab.items() if k != "files"}
            t["files"] = []
            tables[p.table] = t
        entry = {k: v for k, v in p.remote.items() if k != "table"}
        files = sorted([f for f in t.get("files") or [] if f.get("path") != p.path] + [entry], key=lambda f: f["path"])
        t["files"] = files
        t["rows"] = sum(int(f.get("rows") or 0) for f in files)
        t["bytes"] = sum(int(f.get("bytes") or 0) for f in files)
        if rtab.get("ddl"):
            t["ddl"] = rtab["ddl"]
    up = dict(out.get("uploaded") or {})
    ufiles = dict(up.get("files") or {})
    for p in applied:
        ufiles[p.path] = p.remote.get("sha256")
    up.update(files=ufiles, repo_id=REPO_ID)
    out["uploaded"] = up
    out["partial"] = False
    return out


def _move_into_export(got: Dict[str, Path]) -> None:
    for rel, src in got.items():
        dst = hd.EXPORT_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)


def _record(result: str, **kw) -> Dict:
    rec = {"at": _now(), "result": result, **kw}
    _write_json(LAST_PATH, rec)
    return rec


def pull(api=None, *, mode: str = "lead", discard_local: bool = False, dry_run: bool = False,
         say=print) -> Tuple[int, Dict]:
    """원격이 앞섰으면 바뀐 조각만 받아 맞춘다 — (종료코드, 요약). 0 같음 · 맞춤 / 65 겹침 / 1 실패 · 그 밖은 까닭이 요약에.

    ``mode="lead"`` 는 회차를 잡은 PC(전부 맞춤 — 끝나면 기준 = 원격) · ``follow`` 는 따라가는 PC(복구용 표 건너뜀 — 받은 조각만 기준에).
    """
    t0 = time.time()
    api = api or make_api()
    head = remote_head(api)
    base = base_or_bootstrap()
    if base and base.get("main") == head and not (mode == "lead" and base.get("partial")):
        return 0, _record("same", main=head, mode=mode, why="원격 머리가 기준과 같다", changed=0)
    rman = remote_manifest(api, head)
    if _empty_remote(rman):
        return 0, _record("empty", main=head, mode=mode, why="원격에 아직 데이터가 없다(받을 것 없음)", changed=0)
    rfiles = files_of(rman)
    if base and fp_of(rfiles) == base.get("fp"):
        save_base(base.get("files") or {}, head, by=f"{mode}-same", partial=False)
        return 0, _record("same", main=head, mode=mode, why="원격 파일 구성이 기준과 같다(머리만 옮김)", changed=0)
    if not config.DB_PATH.exists():
        return 1, _record("no_db", main=head, mode=mode,
                          why="이 PC 에 수집 DB 가 없다 — 새 PC 는 python scripts/daily_update.py sync --full")
    conn = sqlite3.connect(config.DB_PATH, timeout=60, isolation_level=None)
    try:
        parts = plan(base, rman, conn, mode=mode)
        by = {a: [p for p in parts if p.action == a] for a in ("adopt", "replace", "union", "conflict", "schema", "skip")}
        for p in parts:
            say(f"  {p.action:<8} {p.path} · {p.why}")
        if by["schema"]:
            return 1, _record("schema", main=head, mode=mode, why=by["schema"][0].why,
                              parts=[p.path for p in by["schema"]])
        if by["conflict"] and not discard_local:
            return EX_CONFLICT, _record(
                "conflict", main=head, mode=mode, parts=[p.path for p in by["conflict"]],
                why=(f"이 PC 의 올리지 않은 변경과 원격 변경이 겹친다 {len(by['conflict'])}조각 — 이 PC 것을 버리려면 "
                     f"python scripts/daily_update.py sync --discard-local · 이 PC 것이 맞으면 사람이 정한다(설계 5.4)"))
        work = by["adopt"] + by["replace"] + by["union"] + (by["conflict"] if discard_local else [])
        if dry_run:
            return 0, {"result": "dry_run", "main": head, "plan": {a: len(v) for a, v in by.items()}}
        stage = STAGE_DIR / head[:12]
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True, exist_ok=True)
        got = _download(api, head, work, stage)
        rows = 0
        for p in work:
            if p.action in ("replace", "union", "conflict"):
                if p.action == "conflict":
                    p.action = "replace"                      # 이 PC 것을 버린다(사용자가 고름)
                rows += _apply_part(conn, p, got[p.path], rman)
    except SyncError as e:
        return 1, _record("error", main=head, mode=mode, why=str(e))
    finally:
        conn.close()
    _move_into_export(got)
    shutil.rmtree(STAGE_DIR / head[:12], ignore_errors=True)
    hd._write_json_atomic(hd.MANIFEST_PATH, merge_manifest(hd._load_manifest(), rman, work))
    if mode == "lead" or not by["skip"]:
        save_base(rfiles, head, by=mode)                      # 전부 맞췄다 — 기준 = 원격
    else:
        files = dict((base or {}).get("files") or {})         # 따라가기 — 받은 조각만 기준에(복구용 표는 옛 기준 그대로)
        files.update({p.path: p.remote for p in work})
        save_base(files, head, by=mode, partial=True)
    return 0, _record("synced", main=head, mode=mode, changed=len(work), rows=rows,
                      bytes=sum(int(p.remote.get("bytes") or 0) for p in work),
                      plan={a: len(v) for a, v in by.items()}, seconds=round(time.time() - t0, 1),
                      discarded=[p.path for p in by["conflict"]] if discard_local else [])


def full(api=None, *, say=print) -> Tuple[int, Dict]:
    """수집 DB 가 없는 새 PC — 원격 전부를 받아 복원하고(복원의 내용 지문 대조까지) 기준 = 원격. DB 가 있으면 하지 않는다."""
    t0 = time.time()
    if config.DB_PATH.exists():
        return 1, _record("exists", why=f"이미 수집 DB 가 있다({config.DB_PATH.name}) — 증분 맞추기(sync)를 쓴다 · "
                                        f"정말 새로 받으려면 그 파일을 다른 곳으로 옮긴 뒤")
    api = api or make_api()
    head = remote_head(api)
    rman = remote_manifest(api, head)
    if _empty_remote(rman):
        return 1, _record("empty", main=head, mode="full", why="원격에 아직 데이터가 없다 — 받을 것이 없다")
    rfiles = files_of(rman)
    stage = STAGE_DIR / f"full-{head[:12]}"
    stage.mkdir(parents=True, exist_ok=True)
    parts = [Part(p, e["table"], None, "replace", e, None) for p, e in sorted(rfiles.items())]
    say(f"  원격 main {head[:8]} · 파일 {len(parts)} · {sum(int(e.get('bytes') or 0) for e in rfiles.values()) / 1e9:.2f}GB 받기")
    try:
        got = _download(api, head, parts, stage)
    except SyncError as e:
        return 1, _record("error", main=head, mode="full", why=str(e))
    hd._write_json_atomic(stage / "meta" / "manifest.json", rman)
    tmp_db = config.DB_PATH.with_name(config.DB_PATH.name + ".restoring")
    rc = hd.restore(into=str(tmp_db), src=str(stage), force=True, verbose=False)
    if rc != 0:
        tmp_db.unlink(missing_ok=True)
        return 1, _record("error", main=head, mode="full", why="복원 검증이 실패했다 — hf_dataset restore 출력을 본다")
    os.replace(tmp_db, config.DB_PATH)
    _move_into_export(got)
    hd._write_json_atomic(hd.MANIFEST_PATH, merge_manifest({}, rman, parts))
    shutil.rmtree(stage, ignore_errors=True)
    save_base(rfiles, head, by="full")
    return 0, _record("full", main=head, mode="full", changed=len(parts), seconds=round(time.time() - t0, 1))


def status_lines(api=None) -> List[str]:
    base = base_or_bootstrap()
    last = _read_json(LAST_PATH)
    out = [f"― 맞추기 {REPO_ID}",
           f"  기준   main {str(base.get('main') or '-')[:8]} · 지문 {base.get('fp') or '-'} · {base.get('by') or '없음'}"
           f" · {base.get('at') or ''} · 파일 {len(base.get('files') or {})}"]
    if last:
        out.append(f"  마지막 {last.get('at')} · {last.get('result')} · {last.get('mode', '')} · 바뀐 조각 {last.get('changed', '-')}"
                   + (f" · {last.get('why')}" if last.get("why") else ""))
    if api is not None:
        head = remote_head(api)
        why = behind(api, head)
        out.append(f"  원격   main {head[:8]} · " + ("✅ 기준과 같은 파일 구성" if why is None else f"🟡 {why}"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python scripts/hf_sync.py", description="여러 PC 맞추기 — 기준 · 원격 · 이 PC 견주기")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="기준 · 원격 · 마지막 맞추기(원격을 읽기만)")
    s.add_argument("--plan", action="store_true", help="받을 조각 · 할 일까지(수집 DB 를 읽기만 · 쓰지 않음)")
    a = p.parse_args(argv)
    api = make_api()
    print("\n".join(status_lines(api)))
    if a.plan:
        rc, rec = pull(api, dry_run=True)
        print(f"  계획   {rec.get('plan') or rec.get('why') or rec.get('result')}")
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
