"""HF ``qurious-quant/dart-disclosure-financials`` (private) — DART 공시 목록 · 재무 주요계정 · 정책 회의 일정 보관.

    PYTHONPATH=. python scripts/hf_dart.py export --asof 2026-10-04   수집 DB → 연도별 파케이 · manifest.json · README.md
    PYTHONPATH=. python scripts/hf_dart.py status                     로컬 매니페스트 · 마지막 실행 기록 (읽기만)
    PYTHONPATH=. python scripts/hf_dart.py status --remote            + 원격 공개 범위 · 파일 수 · 태그 (읽기만)
    PYTHONPATH=. python scripts/hf_dart.py upload                     dry-run — 무엇을 올릴지만 보여 준다
    PYTHONPATH=. python scripts/hf_dart.py upload --yes               실제로 올리고 태그 ``dart-<기준일>`` 을 단다
    PYTHONPATH=. python scripts/hf_dart.py verify                     올린 판을 임시 폴더에 받아 대조 + SQLite 로 되살리기(복원 리허설)
    PYTHONPATH=. python scripts/hf_dart.py all --asof 2026-10-04 --yes   export → upload → verify (세션 밖 실행용 · 잠금 · 결과 JSON)

왜 따로 두나
  ``krx-daily-market``(``scripts/hf_dataset.py``)은 수집 DB 를 통째로 되살리는 **백업**이라 12:30 러너가 날마다 덮는다.
  이쪽은 공시 · 재무를 분석하는 사람이 바로 읽는 **보관본**이다 — 기준일마다 태그가 남아 그날 판을 다시 받을 수 있다.

기준일 거름(``--asof``)
  공시는 ``rcept_dt <= 기준일`` · 재무는 ``known_at <= 기준일`` 만 담는다. 12:30 러너가 오늘 공시를 더 넣은 뒤에
  내보내도 같은 기준일이면 같은 판이 나온다(지난 행의 비고 ``rm`` 이 다시 받혀 바뀐 경우만 다르다 — 카드에 적었다).
  정책 회의 일정은 앞으로 열릴 회의가 요점이라 거르지 않는다.

파일 규칙
  공시는 접수일 연도, 재무는 ``known_at`` 연도로 파일을 나눈다 — 새 공시 · 새 정정본은 늘 그해 파일에만 들어가서
  지난 해 파일의 바이트가 바뀌지 않는다. 파케이 옵션은 ``hf_dataset.PARQUET_OPTS`` 를 그대로 쓴다(한 곳에서만 정한다).

관문 넷 (``hf_ohlcv.py`` 와 같은 원칙)
  1. ``QURIOUS_RAW_SHARING`` 이 켜져 있다 — 원자료 공유는 팀 결정을 확인한 흔적이 있어야 한다
  2. 매니페스트가 있고 반쪽(.part) 파일이 없으며 로컬 파일의 sha256 이 매니페스트와 같다
  3. hf_xet 이 켜져 있다 — 바뀐 청크만 올라간다
  4. 원격이 **실제로 private** 이다 — ``create_repo(private=True, exist_ok=True)`` 는 이미 있는 저장소의
     공개 범위를 바꾸지 않으므로, 만들고 나서 ``repo_info`` 로 다시 확인한다(API · CLI 의 기본값은 public)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collector import config  # noqa: E402
from collector import manifest as collector_manifest  # noqa: E402
from collector.ohlcv import KST  # noqa: E402
import hf_dataset as _hd  # noqa: E402  — 파케이 옵션 · 칸 · DDL · sha256 도우미를 한 곳에서 가져온다

REPO_ID = "qurious-quant/dart-disclosure-financials"

#: 내보내기 폴더 — ``data/collector/`` 아래라 .gitignore 로 커밋에서 빠진다(이 팀 저장소는 Public 이다).
OUT_DIR = config.DATA_DIR / "hf_dart"
META_DIR = OUT_DIR / "meta"
MANIFEST_PATH = META_DIR / "manifest.json"
LAST_UPLOAD = META_DIR / "last_upload.json"     # 올리지 않는 기록 파일 — 아래 UPLOAD_IGNORE
LAST_VERIFY = META_DIR / "last_verify.json"
LAST_RUN = META_DIR / "last_run.json"
LOCK_PATH = META_DIR / "run.lock"
UPLOAD_IGNORE = ["*.part", "*.tmp", "meta/run.lock", "meta/last_*.json", "logs/*", ".cache/**"]

#: 담는 표. ``date_col`` 이 있으면 그 칸의 연도로 파일을 나누고 기준일로 거른다.
TABLES: Dict[str, Dict] = {
    "disclosure": {
        "date_col": "rcept_dt", "prefix": "rcept",
        "sort": ["rcept_no"],
        "about": "공시 목록 — OpenDART 공시검색(list.json) · 유형 A~J × 시장 유가 · 코스닥 · 코넥스",
    },
    "financial_statement": {
        "date_col": "known_at", "prefix": "known",
        "sort": ["corp_code", "bsns_year", "reprt_code", "fs_div", "sj_div", "ord", "account_nm", "rcept_no"],
        "about": "재무 주요계정 — OpenDART 다중회사 주요계정(fnlttMultiAcnt.json) · 정정본마다 판(접수번호) 하나",
    },
    "policy_meeting": {
        "date_col": None, "prefix": "",
        "sort": ["org", "meeting_date"],
        "about": "통화정책 회의 일정 — 한국은행 금융통화위원회 · 미국 연준 FOMC",
    },
}


# ==================================================
# 잔손질
# ==================================================
def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _token(required: bool = True) -> Optional[str]:
    """HF 토큰. 절대 출력하지 않는다."""
    if required:
        return config.require("HUGGINGFACE_ACCESS_TOKEN", "Hugging Face 접근 토큰 (write 권한)")
    return config.env("HUGGINGFACE_ACCESS_TOKEN") or None


def _sharing_on() -> bool:
    return bool(collector_manifest.RAW_SHARING) or os.environ.get("QURIOUS_RAW_SHARING", "").lower() in ("1", "true", "yes")


def _xet_on() -> bool:
    try:
        from huggingface_hub.utils._runtime import is_xet_available
        return bool(is_xet_available())
    except Exception:
        return False


def _read_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _rel(p: Path) -> str:
    """저장소 기준 상대 경로 — 저장소 밖이면 파일 이름만(매니페스트 · 로그에 사용자 절대 경로를 남기지 않는다)."""
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def _git_info() -> Dict:
    """만든 코드의 커밋 — git 읽기만. 커밋 전 변경이 있으면 그 경로를 함께 적는다(정직하게)."""
    def git(*args: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                               encoding="utf-8", timeout=30)
            return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    dirty = [ln[3:] for ln in git("status", "--porcelain", "--", "collector", "scripts/hf_dart.py",
                                  "scripts/hf_dataset.py").splitlines() if ln.strip()]
    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(dirty), "dirty_paths": dirty}


#: DDL 에 줄 끝 주석이 없는 칸의 뜻 — 주석이 있으면 주석이 먼저다.
_FALLBACK_NOTES = {
    "corp_code": "DART 고유번호 8자리",
    "stock_code": "종목 단축코드 6자리(상장폐지 종목 포함)",
    "currency": "통화(응답 그대로 · 대부분 KRW)",
    "raw_sha256": "이 행이 나온 응답 원문의 sha256 — 수집 DB 의 원문 표와 잇는 열쇠",
}


def _column_notes(ddl: str) -> List[Tuple[str, str, str]]:
    """CREATE TABLE 원문의 칸 · 형 · 줄 끝 주석 — 카드의 칸 표를 손으로 옮기지 않고 DDL 에서 만든다."""
    out = []
    for line in ddl.splitlines():
        code, _, note = line.partition("--")
        m = re.match(r"\s*(\w+)\s+(TEXT|INTEGER|REAL|BLOB)\b", code)
        if m:
            out.append((m.group(1), m.group(2), note.strip() or _FALLBACK_NOTES.get(m.group(1), "")))
    return out


def _part_where(spec: Dict, year: Optional[str], asof_ymd: str) -> Tuple[str, list]:
    col = spec["date_col"]
    if not col:
        return "", []
    # TEXT 칸이라 문자열로 비교한다 — 「그해 이상 · 다음 해 미만」 반열린 구간(hf_dataset 의 DF-40 교훈)
    return (f" WHERE {col} >= ? AND {col} < ? AND {col} <= ?", [year, str(int(year) + 1), asof_ymd])


def _write_part(conn: sqlite3.Connection, table: str, spec: Dict, year: Optional[str],
                asof_ymd: str, out: Path) -> Dict:
    """파일 하나를 스트리밍으로 쓴다(배치 하나 = 로우그룹 하나). ``.part`` 에 쓰고 끝나면 이름을 바꾼다."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = _hd._columns(conn, table)
    names = [c for c, _ in cols]
    schema = _hd._arrow_schema(cols)
    where, params = _part_where(spec, year, asof_ymd)
    sql = f"SELECT {', '.join(names)} FROM {table}{where} ORDER BY {', '.join(spec['sort'])}"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.part")
    tmp.unlink(missing_ok=True)
    opts = {k: v for k, v in _hd.PARQUET_OPTS.items() if k != "row_group_size"}
    t0 = time.time()
    rows = 0
    writer = pq.ParquetWriter(str(tmp), schema, **opts)
    try:
        cur = conn.execute(sql, params)
        while True:
            chunk = cur.fetchmany(_hd.FETCH_ROWS)
            if not chunk:
                break
            columnar = list(zip(*chunk))
            batch = pa.RecordBatch.from_arrays(
                [pa.array(columnar[i], type=schema.field(i).type) for i in range(len(names))], schema=schema)
            writer.write_batch(batch)
            rows += len(chunk)
    except Exception:
        writer.close()
        tmp.unlink(missing_ok=True)
        raise
    writer.close()
    out.unlink(missing_ok=True)
    tmp.rename(out)
    size = out.stat().st_size
    print(f"    {out.relative_to(OUT_DIR).as_posix():<48} {rows:>10,}행 · {_hd._human(size):>9} · {time.time() - t0:5.1f}초",
          flush=True)
    return {"path": out.relative_to(OUT_DIR).as_posix(), "rows": rows, "bytes": size, "sha256": _hd._sha256(out)}


# ==================================================
# export
# ==================================================
def export(asof: str) -> int:
    asof_ymd = asof.replace("-", "")
    if not re.fullmatch(r"\d{8}", asof_ymd):
        print(f"🔴 기준일 모양이 틀렸다: {asof!r} — YYYY-MM-DD 로 준다")
        return 2
    if not config.DB_PATH.exists():
        print(f"🔴 수집 DB 가 없다: {_rel(config.DB_PATH)}")
        return 1
    print(f"― 내보내기 · 기준일 {asof} · {_rel(OUT_DIR)} ―", flush=True)
    t0 = time.time()
    conn = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    man: Dict = {
        "dataset": REPO_ID, "schema": 1, "as_of": asof, "built_at": _now_kst(),
        "code": _git_info(), "source_db": _rel(config.DB_PATH),
        "parquet_opts": _hd.PARQUET_OPTS, "tables": {},
    }
    try:
        for table, spec in TABLES.items():
            col = spec["date_col"]
            db_rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            files: List[Dict] = []
            if col:
                years = [r[0] for r in conn.execute(
                    f"SELECT DISTINCT substr({col}, 1, 4) FROM {table} WHERE {col} <= ? ORDER BY 1", (asof_ymd,))
                    if r[0] and re.fullmatch(r"\d{4}", r[0])]
                for y in years:
                    files.append(_write_part(conn, table, spec, y, asof_ymd, OUT_DIR / table / f"{spec['prefix']}_{y}.parquet"))
                rng = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {table} WHERE {col} <= ?", (asof_ymd,)).fetchone()
            else:
                files.append(_write_part(conn, table, spec, None, asof_ymd, OUT_DIR / table / f"{table}.parquet"))
                rng = conn.execute(f"SELECT MIN(meeting_date), MAX(meeting_date) FROM {table}").fetchone()
            rows = sum(f["rows"] for f in files)
            # 이번에 쓴 파일 밖의 옛 파케이는 지운다 — 단 이번에 쓴 것이 0 이면 지우지 않는다(S87 규칙)
            keep = {f["path"] for f in files}
            if rows > 0:
                for old in sorted((OUT_DIR / table).glob("*.parquet")):
                    if old.relative_to(OUT_DIR).as_posix() not in keep:
                        print(f"    (옛 파일 지움) {old.relative_to(OUT_DIR).as_posix()}")
                        old.unlink()
            man["tables"][table] = {
                "about": spec["about"],
                "partition": f"{col} 연도" if col else "없음(파일 하나)",
                "filter": f"{col} <= '{asof_ymd}'" if col else "",
                "sort": spec["sort"], "rows": rows, "db_rows": db_rows, "excluded_rows": db_rows - rows,
                "date_range": list(rng) if rng else [], "ddl": _hd._ddl(conn, table), "files": files,
            }
            print(f"  {table}: {rows:,}행 (DB {db_rows:,} · 거른 것 {db_rows - rows:,}) · 파일 {len(files)}개", flush=True)
    finally:
        conn.close()
    _write_json(MANIFEST_PATH, man)
    (OUT_DIR / "README.md").write_text(_readme(man), encoding="utf-8")
    total = sum(f["bytes"] for t in man["tables"].values() for f in t["files"])
    print(f"  ✅ 끝 · {_hd._human(total)} · {time.time() - t0:,.1f}초 · 매니페스트 {_rel(MANIFEST_PATH)}",
          flush=True)
    return 0


# ==================================================
# 데이터셋 카드
# ==================================================
def _readme(man: Dict) -> str:
    t = man["tables"]
    rows = {k: v["rows"] for k, v in t.items()}
    code = man.get("code") or {}
    code_s = f"`{code.get('commit', '')}`" + (" + 커밋 전 변경(" + " · ".join(code.get("dirty_paths", [])) + ")"
                                             if code.get("dirty") else "")
    tag = f"dart-{man['as_of']}"
    L = [
        "---", "license: other", "language: [ko]",
        "pretty_name: DART 공시 목록 · 재무 주요계정 · 통화정책 회의 일정 (Qurious 보관본)",
        "viewer: false", "tags: [finance, korea, dart, point-in-time]", "---", "",
        "# DART 공시 · 재무 보관본 — `dart-disclosure-financials`", "",
        "🔴 **이 저장소는 private 이어야 한다.** 까닭은 아래 「출처와 이용 조건」 에 있다. 공개로 바꾸려면 팀 결정과 이용 조건 검토가 먼저다.", "",
        f"- 자료 기준일 **{man['as_of']}** · 태그 `{tag}` (기준일마다 태그가 남아 그날 판을 다시 받을 수 있다)",
        f"- 만든 시각 {man['built_at']} · 만든 코드 Qurious {code_s} · `scripts/hf_dart.py export --asof {man['as_of']}`",
        f"- 행 수 — 공시 {rows.get('disclosure', 0):,} · 재무 주요계정 {rows.get('financial_statement', 0):,} · "
        f"통화정책 회의 {rows.get('policy_meeting', 0):,}",
        "- 수집 DB 를 통째로 되살리는 백업은 따로 있다(`qurious-quant/krx-daily-market` · 날마다 덮어씀). 이쪽은 분석 · 보관용이다.", "",
        "## 파일", "",
        "| 표 | 파일 | 행 | 크기 | sha256(앞 12자) |", "|---|---|--:|--:|---|",
    ]
    for name, tt in t.items():
        for f in tt["files"]:
            L.append(f"| {name} | `{f['path']}` | {f['rows']:,} | {_hd._human(f['bytes'])} | `{f['sha256'][:12]}` |")
    L += [
        "", "전체 sha256 · 행 수 · 표를 다시 만드는 DDL 원문은 `meta/manifest.json` 에 있다.", "",
        "## 출처와 이용 조건", "",
        "- **공시 · 재무** — 금융감독원 전자공시 OpenDART(https://opendart.fss.or.kr) 의 공시검색(`list.json`) · "
        "다중회사 주요계정(`fnlttMultiAcnt.json`) 응답을 칸 이름 그대로 옮겼다.",
        "  - OpenDART FAQ 「상업적 사용」 (2026-10-04 조회) 요지: 공공데이터법에 따른 공공데이터라 공익이나 타인의 권리를 침해하지 않는 선에서 "
        "공개 · 활용은 제한되지 않는다. 다만 **재배포 · 재가공과 관련한 모든 책임은 이용자 부담**이다.",
        "  - 이용약관 제23조①: 공시정보는 공시제출인의 책임 하에 작성되었으며, 금융감독원은 정확성 · 완전성을 보장하지 않는다.",
        "- **통화정책 회의 일정** — 한국은행 금융통화위원회 일정 · 미국 연준 FOMC 일정 누리집(행마다 `source_url`).",
        "- **private 인 까닭** — ① 재배포 책임이 이용자에게 있는데 팀은 그 책임을 질 검토를 하지 않았다 "
        "② 수집 내부 칸(응답 원문 지문 `raw_sha256` · 받은 시각)이 들어 있다 ③ 팀 안 분석 · 보관이 목적이다.", "",
    ]
    for name, tt in t.items():
        L += [f"## 표 `{name}` — {tt['about']}", "",
              f"- 파일 나누기: {tt['partition']} · 거름: {tt['filter'] or '없음'} · 정렬: {', '.join(tt['sort'])}",
              f"- 값의 범위: {' ~ '.join(str(x) for x in tt['date_range'])}", "",
              "| 칸 | 형 | 뜻 |", "|---|---|---|"]
        for c, ty, note in _column_notes(tt["ddl"]["table"]):
            L.append(f"| `{c}` | {ty} | {note.replace('|', '/')} |")
        L.append("")
    L += [
        "## 「그날 알 수 있었던 값」(point-in-time) 고르기 — `known_at` · `first_known_at`", "",
        "OpenDART 는 한 기간(사업연도 · 보고서 종류)에 대해 **가장 최근 정정본의 값만** 준다. 그래서 2026-10-04 에 한꺼번에 받은 과거분은 "
        "정정된 기간이면 정정본 값만 있고 처음 보고값이 없다. 2026-10-05 부터는 매일 그날 접수된 판을 받아 쌓으므로, 그 뒤 기간은 처음 보고값과 "
        "정정값이 판(`rcept_no`)마다 따로 남는다.", "",
        "- `known_at` — 그 값이 실린 보고서(`rcept_no`)의 접수일(YYYYMMDD) = 값이 공개된 날",
        "- `first_known_at` — 그 기간 **원본** 보고서의 접수일(공시 목록에서 이음 · 못 이으면 빈칸 — 공시 목록이 없는 2019년 분기 · 반기 보고서 등)",
        "- **strict(권장)** — 기준일 D 에는 `known_at < D` 인 판 가운데 접수번호가 가장 큰 판만 쓴다. 정정된 기간은 정정일 전까지 비어 있다 — "
        "미래 값이 섞이지 않는다(Sharadar As-Reported · Compustat 처음 보고값과 같은 뜻). Qurious 앱은 접수일 **다음 거래일**부터 쓴다.",
        "- **first** — 원본이 D 전에 나왔으면(`first_known_at < D`) 정정본 값이라도 쓴다. 빈 기간이 없는 대신 미래 값이 섞인다.", "",
        "```python",
        "import pandas as pd",
        "fs = pd.read_parquet(\"financial_statement\")          # 폴더째 읽으면 known_* 파일이 모두 붙는다",
        "D = \"20250401\"                                      # 기준일 YYYYMMDD",
        "key = [\"corp_code\", \"bsns_year\", \"reprt_code\", \"fs_div\", \"sj_div\", \"account_nm\"]",
        "strict = fs[fs.known_at < D].sort_values(\"rcept_no\").groupby(key).tail(1)",
        "```", "",
        "## 받기 · 되살리기", "",
        "```python",
        "from huggingface_hub import snapshot_download",
        f"path = snapshot_download(\"{REPO_ID}\", repo_type=\"dataset\", revision=\"{tag}\")   # private — 토큰 필요",
        "```", "",
        "`meta/manifest.json` 의 `tables.<표>.ddl` 로 SQLite 표를 만들고 파케이를 넣으면 수집 DB 의 그 표가 그대로 돌아온다 "
        "(올린 뒤 `scripts/hf_dart.py verify` 가 이 되살리기를 실제로 해 본다).", "",
        "## 파일이 바뀌는 규칙", "",
        "- 공시는 접수일 연도, 재무는 `known_at` 연도로 파일을 나눈다 — 새 공시 · 새 정정본은 늘 그해 파일에만 들어가 지난 해 파일은 바뀌지 않는다.",
        "- 예외: 공시의 비고 `rm`(유 · 코 · 정 · 철 …)은 마지막으로 받은 날 기준이라, 지난 행을 다시 받으면 그 행이 바뀐다(`updated_at`).",
        "- 파케이 옵션은 `krx-daily-market` 과 같다(zstd 3 · 로우그룹 25만 · content-defined chunking) — 같은 내용이면 같은 바이트다.", "",
    ]
    return "\n".join(L)


# ==================================================
# status
# ==================================================
def status(remote: bool = False) -> int:
    man = _read_json(MANIFEST_PATH)
    if man:
        tot = sum(f["bytes"] for t in man["tables"].values() for f in t["files"])
        print(f"― 로컬 · 기준일 {man['as_of']} · 만든 시각 {man['built_at']} · {_hd._human(tot)}")
        for name, t in man["tables"].items():
            print(f"    {name:<20} {t['rows']:>10,}행 · 파일 {len(t['files'])}개 · 거른 것 {t['excluded_rows']:,}")
    else:
        print("― 로컬 내보내기 없음 — `export --asof YYYY-MM-DD` 를 먼저 돌린다")
    for label, p in (("마지막 실행", LAST_RUN), ("마지막 올리기", LAST_UPLOAD), ("마지막 대조", LAST_VERIFY)):
        d = _read_json(p)
        if d:
            print(f"― {label}: {json.dumps(d, ensure_ascii=False)[:600]}")
    if LOCK_PATH.exists():
        print(f"― 🟡 잠금 있음(실행 중이거나 죽은 흔적): {LOCK_PATH.read_text(encoding='utf-8').strip()}")
    if remote:
        tok = _token(required=False)
        if not tok:
            print("  토큰 없음 — 원격은 보지 않았다")
            return 0
        from huggingface_hub import HfApi
        api = HfApi(token=tok)
        try:
            info = api.repo_info(REPO_ID, repo_type="dataset")
            refs = api.list_repo_refs(REPO_ID, repo_type="dataset")
            # 메시지를 단 태그는 target_commit 이 태그 객체 번호다 — 실제 커밋은 그 태그로 repo_info 를 물어 푼다
            tags = ", ".join(f"{r.name}→커밋 {api.repo_info(REPO_ID, repo_type='dataset', revision=r.name).sha[:8]}"
                             for r in refs.tags) or "없음"
            print(f"― 원격 {REPO_ID} · {'private ✅' if info.private else '🔴 public'} · 파일 {len(info.siblings or [])}개 · "
                  f"마지막 커밋 {str(info.sha)[:8]} · 태그 {tags}")
        except Exception as e:
            print(f"― 원격 {REPO_ID} · 아직 없거나 권한이 없다({type(e).__name__})")
    return 0


# ==================================================
# upload
# ==================================================
def _assert_private(api, create: bool) -> bool:
    if create:
        api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 확인 못 한 것은 통과가 아니다. 올리지 않는다.")
        return False
    if info.private:
        print("  ✅ 관문 4 원격이 private 임을 확인했다")
        return True
    print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{REPO_ID}/settings 에서 Private 로.")
    return False


def _local_ok(man: Dict) -> List[str]:
    """관문 2 — 반쪽 파일 · 빠진 파일 · sha256 어긋남을 모은다(비어 있으면 통과)."""
    bad = [f"반쪽 파일 {p.relative_to(OUT_DIR).as_posix()}" for p in OUT_DIR.rglob("*.part")]
    for t in man.get("tables", {}).values():
        for f in t["files"]:
            p = OUT_DIR / f["path"]
            if not p.exists():
                bad.append(f"빠짐 {f['path']}")
            elif _hd._sha256(p) != f["sha256"]:
                bad.append(f"sha256 다름 {f['path']}")
    return bad


def upload(yes: bool) -> int:
    man = _read_json(MANIFEST_PATH)
    if not man:
        print("올릴 것이 없다 — `export --asof YYYY-MM-DD` 를 먼저 돌린다.")
        return 1
    bad = _local_ok(man)
    tag = f"dart-{man['as_of']}"
    files = [p for p in OUT_DIR.rglob("*") if p.is_file() and p.suffix not in (".part", ".tmp")
             and not p.relative_to(OUT_DIR).as_posix().startswith(("meta/last_", "meta/run.lock", "logs/"))]
    total = sum(p.stat().st_size for p in files)
    print(f"― 업로드 {'(실행)' if yes else '(dry-run — 아무것도 올리지 않는다)'} ―")
    print(f"  대상   {REPO_ID} (dataset · private 이어야 한다) · 태그 {tag}")
    print(f"  파일   {len(files):,}개 · {_hd._human(total)}")
    print(f"  관문 1 공유 스위치 {'✅ 켜짐' if _sharing_on() else '🔴 꺼짐 — 실제 업로드는 막힌다'}")
    print(f"  관문 2 로컬 파일 {'✅ 반쪽 0 · sha256 일치' if not bad else '🔴 ' + ' · '.join(bad[:5])}")
    print(f"  관문 3 hf_xet {'✅ 켜짐' if _xet_on() else '⚠️ 없음 — 파일 전체가 다시 올라간다'}")
    if not yes:
        tok = _token(required=False)
        if tok:
            from huggingface_hub import HfApi
            try:
                info = HfApi(token=tok).repo_info(REPO_ID, repo_type="dataset")
                print(f"  관문 4 원격 {'✅ private' if info.private else '🔴 public — 이대로면 올리지 않는다'} (읽기만)")
            except Exception as e:
                print(f"  관문 4 원격 아직 없다({type(e).__name__}) — `--yes` 가 private 으로 만든다")
        print("  실제로 올리려면 `--yes` 를 준다.")
        return 0
    if not _sharing_on():
        print("  🔴 QURIOUS_RAW_SHARING 이 꺼져 있다 — PowerShell `$env:QURIOUS_RAW_SHARING=\"1\"` · bash `export QURIOUS_RAW_SHARING=1`")
        return 1
    if bad:
        print("  🔴 로컬 파일이 매니페스트와 다르다 — export 를 다시 돌린다")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=_token())
    if not _assert_private(api, create=True):
        return 1
    rows = {k: v["rows"] for k, v in man["tables"].items()}
    msg = (f"DART 보관본 · 기준일 {man['as_of']} · 공시 {rows.get('disclosure', 0):,} · "
           f"재무 {rows.get('financial_statement', 0):,} · 통화정책 회의 {rows.get('policy_meeting', 0):,}")
    t0 = time.time()
    info = api.upload_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=str(OUT_DIR),
                             commit_message=msg, ignore_patterns=UPLOAD_IGNORE)
    commit = str(getattr(info, "oid", "") or "")
    print(f"  ✅ 올렸다 · 커밋 {commit[:8]} · {time.time() - t0:,.1f}초", flush=True)
    tag_note = "새로 닮"
    try:
        api.create_tag(REPO_ID, repo_type="dataset", tag=tag, tag_message=msg, revision=commit or None)
    except Exception as e:
        # 같은 기준일을 다시 올린 경우 — 태그는 옮기지 않는다(대조는 태그가 아니라 커밋으로 한다)
        tag_note = f"이미 있어 그대로 둠({type(e).__name__})"
    print(f"  태그 {tag} — {tag_note}")
    _write_json(LAST_UPLOAD, {"at": _now_kst(), "repo_id": REPO_ID, "commit": commit, "tag": tag, "tag_note": tag_note,
                              "as_of": man["as_of"], "rows": rows, "bytes": total,
                              "seconds": round(time.time() - t0, 1)})
    return 0


# ==================================================
# verify — 받아서 대조 + 되살리기
# ==================================================
def verify(keep: bool = False) -> int:
    """올린 판(마지막 올리기의 커밋)을 임시 폴더에 받아 ① 원격 매니페스트 = 로컬 매니페스트 ② 파일마다 sha256 · 행 수
    ③ DDL 로 임시 SQLite 를 만들어 전부 넣어 보기(기본 키 중복이면 여기서 터진다) ④ 지금 수집 DB 의 같은 거름 행 수를 본다."""
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    last = _read_json(LAST_UPLOAD)
    lman = _read_json(MANIFEST_PATH)
    rev = last.get("commit") or last.get("tag")
    if not rev or not lman:
        print("🔴 올린 기록(meta/last_upload.json)이나 로컬 매니페스트가 없다 — upload 를 먼저")
        return 1
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="hf_dart_verify_"))
    checks: List[Tuple[str, bool, str]] = []
    try:
        print(f"― 대조 · {REPO_ID}@{rev[:8]} → 임시 폴더에 받기 ―", flush=True)
        snapshot_download(repo_id=REPO_ID, repo_type="dataset", revision=rev, local_dir=str(tmp), token=_token())
        rman = _read_json(tmp / "meta" / "manifest.json")
        lfiles = {f["path"]: f["sha256"] for t in lman["tables"].values() for f in t["files"]}
        rfiles = {f["path"]: f["sha256"] for t in rman.get("tables", {}).values() for f in t["files"]}
        checks.append(("원격 매니페스트 = 로컬 매니페스트(파일 · sha256)", lfiles == rfiles and rman.get("as_of") == lman["as_of"],
                       f"파일 {len(rfiles)} · 기준일 {rman.get('as_of')}"))
        sha_bad, row_bad = [], []
        for t in rman.get("tables", {}).values():
            for f in t["files"]:
                p = tmp / f["path"]
                if not p.exists() or _hd._sha256(p) != f["sha256"]:
                    sha_bad.append(f["path"])
                elif pq.ParquetFile(str(p)).metadata.num_rows != f["rows"]:
                    row_bad.append(f["path"])
        checks.append(("받은 파일 sha256 = 매니페스트", not sha_bad, " · ".join(sha_bad[:5]) or "전부 같음"))
        checks.append(("파케이 행 수 = 매니페스트", not row_bad, " · ".join(row_bad[:5]) or "전부 같음"))
        known = set(rfiles) | {"README.md", ".gitattributes", "meta/manifest.json"}
        extra = sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*")
                       if p.is_file() and ".cache" not in p.parts and p.relative_to(tmp).as_posix() not in known)
        checks.append(("원격에 매니페스트 밖 파일 없음", not extra, " · ".join(extra[:5]) or "없음"))

        # 되살리기 — DDL 원문으로 표를 만들고 파케이를 전부 넣는다
        db = tmp / "restore.sqlite3"
        rc = sqlite3.connect(str(db))
        try:
            for name, t in rman["tables"].items():
                rc.execute(t["ddl"]["table"])
                n = 0
                for f in t["files"]:
                    pf = pq.ParquetFile(str(tmp / f["path"]))
                    cols = pf.schema_arrow.names
                    sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                    for batch in pf.iter_batches(batch_size=50_000):
                        data = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
                        rc.executemany(sql, zip(*data))
                        n += batch.num_rows
                rc.commit()
                got = rc.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                checks.append((f"되살리기 {name}", got == t["rows"] == n, f"{got:,}행 (매니페스트 {t['rows']:,})"))
        finally:
            rc.close()

        # 지금 수집 DB 의 같은 거름 행 수 — 12:30 러너가 늦게 들어온 지난 날짜 공시를 더 넣었으면 DB 가 많다(🟡)
        if config.DB_PATH.exists():
            asof_ymd = rman["as_of"].replace("-", "")
            conn = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
            try:
                for name, t in rman["tables"].items():
                    col = TABLES[name]["date_col"]
                    q = f"SELECT COUNT(*) FROM {name}" + (f" WHERE {col} <= ?" if col else "")
                    now_n = conn.execute(q, (asof_ymd,) if col else ()).fetchone()[0]
                    note = f"DB 지금 {now_n:,} · 올린 것 {t['rows']:,}"
                    if now_n > t["rows"]:
                        note += f" — 그 뒤 들어온 행 {now_n - t['rows']:,}(🟡 다음 판에 담긴다)"
                    checks.append((f"수집 DB 같은 거름 {name}", now_n >= t["rows"], note))
            finally:
                conn.close()
    finally:
        if keep:
            print(f"  (받은 폴더를 남겼다: {tmp})")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    ok = all(c[1] for c in checks)
    for name, good, note in checks:
        print(f"  {'✅' if good else '🔴'} {name} — {note}")
    print(f"  {'✅ 대조 통과' if ok else '🔴 대조 실패'} · {time.time() - t0:,.1f}초", flush=True)
    _write_json(LAST_VERIFY, {"at": _now_kst(), "revision": rev, "ok": ok, "seconds": round(time.time() - t0, 1),
                              "checks": [{"name": n, "ok": g, "note": s} for n, g, s in checks]})
    return 0 if ok else 1


# ==================================================
# all — 세션 밖 실행용(잠금 · 결과 JSON)
# ==================================================
def run_all(asof: str, yes: bool) -> int:
    META_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age_h = (time.time() - LOCK_PATH.stat().st_mtime) / 3600
        if age_h < 6:
            print(f"🔴 잠금이 있다({age_h:.1f}시간 전) — 이미 돌고 있다. 죽은 흔적이면 {_rel(LOCK_PATH)} 를 지운다")
            return 2
        LOCK_PATH.unlink()
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, f"pid {os.getpid()} · 시작 {_now_kst()} · 기준일 {asof}".encode("utf-8"))
    os.close(fd)
    steps = []
    try:
        for name, fn in (("export", lambda: export(asof)), ("upload", lambda: upload(yes)), ("verify", verify)):
            t0 = time.time()
            try:
                code = fn()
            except Exception as e:                       # 단계가 죽어도 기록은 남긴다
                print(f"🔴 {name} 단계 예외: {type(e).__name__}: {e}", flush=True)
                code = 99
            steps.append({"step": name, "code": code, "seconds": round(time.time() - t0, 1)})
            _write_json(LAST_RUN, {"at": _now_kst(), "as_of": asof, "steps": steps, "done": False})
            if code != 0 or (name == "upload" and not yes):
                break
    finally:
        LOCK_PATH.unlink(missing_ok=True)
    ok = all(s["code"] == 0 for s in steps) and len(steps) == 3
    _write_json(LAST_RUN, {"at": _now_kst(), "as_of": asof, "steps": steps, "done": True, "ok": ok})
    print(f"― {'✅ 전부 성공' if ok else '🔴 멈춤'} · " + " · ".join(f"{s['step']} {s['code']}({s['seconds']}초)" for s in steps))
    return 0 if ok else 1


def main(argv=None) -> int:
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
    ap = argparse.ArgumentParser(prog="python scripts/hf_dart.py", description=f"HF {REPO_ID} (private) 보관본")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export")
    p.add_argument("--asof", default=yesterday, help="자료 기준일 YYYY-MM-DD (기본: 어제 KST)")
    p = sub.add_parser("status")
    p.add_argument("--remote", action="store_true")
    p = sub.add_parser("upload")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--keep", action="store_true", help="받은 임시 폴더를 지우지 않는다")
    p = sub.add_parser("all")
    p.add_argument("--asof", default=yesterday)
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        return export(a.asof)
    if a.cmd == "status":
        return status(a.remote)
    if a.cmd == "upload":
        return upload(a.yes)
    if a.cmd == "verify":
        return verify(a.keep)
    return run_all(a.asof, a.yes)


if __name__ == "__main__":
    sys.exit(main())
