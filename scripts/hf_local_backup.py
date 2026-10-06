"""HF private 백업 — 근거 DB · 근거 벡터(Qdrant) · 수집 자료 검색 색인 (다시 만들 수 있지만 오래 걸리는 것).

    PYTHONPATH=. python scripts/hf_local_backup.py export kb|search|all     사본 · 스냅숏 · manifest.json · README.md
    PYTHONPATH=. python scripts/hf_local_backup.py upload kb|search|all     dry-run — 무엇을 올릴지만
    PYTHONPATH=. python scripts/hf_local_backup.py upload kb|search|all --yes
    PYTHONPATH=. python scripts/hf_local_backup.py verify kb|search|all     받아서 sha256 · SQLite 열어 행 수 · 벡터 되살리기
    PYTHONPATH=. python scripts/hf_local_backup.py all kb|search|all --yes  export → upload → verify

왜 따로 두나 (2026-10-06 사용자 요청 「로컬에 있는 것 HF 에」)
  수집 원자료는 이미 HF 에 있다 — ``krx-daily-market``(수집 DB 통째 · 12:30 러너) · ``krx-ohlcv`` · ``dart-disclosure-financials``
  · ``kb-sector-laws``. 빠진 것은 수집 자료에서 **다시 만들 수 있지만 오래 걸리는 계산물** 셋이다.

  ==========  ===========================================  ================================  ====================
  대상          무엇                                            다시 만들면                           HF 데이터셋
  ==========  ===========================================  ================================  ====================
  kb          근거 DB ``data/collector/kb.sqlite3``(법령 ·       법령 API 로 다시 받기 · 조각           kb-legal-base
              감독규정 · 섹터 법령 조각 · 분류 낱말 표)
  kb          근거 벡터 Qdrant ``kb_v1``(bge-m3)                  임베딩 약 1시간(9,725 + 4,067 조각)   kb-legal-base/qdrant/
  search      수집 자료 검색 색인 ``data/collector/search.sqlite3``   ``search_index build`` 약 8분          search-index
  ==========  ===========================================  ================================  ====================

어떻게
  - SQLite 는 ``sqlite3`` 의 backup API 로 사본을 뜬다 — 앱(도커 · 읽기 전용)이 읽는 중이어도 한 시점의 사본이 된다.
    사본은 롤백 저널로 둔다(읽기 전용으로 붙는 DB 를 WAL 로 두면 앱이 못 연다 — DF-67 · DF-74).
  - Qdrant 는 ``POST /collections/{name}/snapshots`` 로 스냅숏을 만들어 받고, 받은 뒤 서버의 스냅숏은 지운다.
  - 압축하지 않는다 — hf_xet 이 내용 단위로 잘라 다음 판에서 바뀐 청크만 올린다(gzip 이면 매번 통째로 바뀐다).
  - 관문은 ``hf_dart.py`` 와 같다: ① 공유 스위치 ② 매니페스트 sha256 ③ hf_xet ④ 원격이 실제로 private.

되살리기 (README 카드에도 적는다)
  ``snapshot_download`` 로 받아 ``kb.sqlite3`` · ``search.sqlite3`` 를 ``data/collector/`` 에 두고, 벡터는
  ``POST {QDRANT}/collections/kb_v1/snapshots/upload?priority=snapshot`` 에 스냅숏 파일을 올린다(``verify`` 가 임시 컬렉션으로
  같은 길을 실제로 밟아 점 수를 맞춘다).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Optional

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collector import config  # noqa: E402
import hf_dart as _hdart  # noqa: E402  — 토큰 · 공유 스위치 · xet · JSON · git 정보 도우미를 한 곳에서
import hf_dataset as _hd  # noqa: E402  — sha256 · 크기 표시

QDRANT_URL = config.env("KB_QDRANT_URL", "http://127.0.0.1:16333").rstrip("/")
BACKUP_DIR = config.DATA_DIR / "hf_backup"      # data/collector/ 아래라 .gitignore 로 커밋에서 빠진다
UPLOAD_IGNORE = ["*.part", "*.tmp", "meta/**", "logs/*", ".cache/**"]

#: 백업 대상 — 표 칸은 매니페스트 · 대조에 적을 행 수(있는 표만 센다)
TARGETS: Dict[str, Dict] = {
    "kb": {
        "repo": "qurious-quant/kb-legal-base",
        "about": "근거 DB(법령 · 감독규정 · 섹터 법령 조각 · 분류 낱말 표)와 그 벡터(Qdrant kb_v1)",
        "sqlite": [("kb.sqlite3", "kb.sqlite3")],
        "tables": ["kb_document", "kb_chunk", "kb_vector", "kb_sector_word", "kb_raw"],
        "qdrant": ["kb_v1"],
    },
    "search": {
        "repo": "qurious-quant/search-index",
        "about": "수집 자료 검색 색인(공시 · 재무 · 뉴스 · 일정 · 이름표 — search_index build 결과)",
        "sqlite": [("search.sqlite3", "search.sqlite3")],
        "tables": [],
        "qdrant": [],
    },
}


def _out(target: str) -> Path:
    return BACKUP_DIR / target


# ==================================================
# 1. 사본 · 스냅숏
# ==================================================
def sqlite_copy(src: Path, dst: Path) -> Dict:
    """한 시점의 사본(backup API) → 롤백 저널 · 무결성 검사(quick_check) 결과와 표 목록을 돌려준다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(dst.suffix + ".part")
    part.unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(part)
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")
        ok = d.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        d.close()
        s.close()
    part.replace(dst)
    return {"quick_check": ok}


def table_rows(db: Path, tables: List[str]) -> Dict[str, int]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        names = tables or sorted(n for n in have if not n.startswith("sqlite_") and "_fts_" not in n)
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in names if t in have}
    finally:
        con.close()


def _http(method: str, url: str, body: Optional[bytes] = None, headers: Optional[Dict] = None, timeout: float = 600):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def qdrant_info(name: str) -> Dict:
    with _http("GET", f"{QDRANT_URL}/collections/{name}", timeout=30) as r:
        res = json.loads(r.read())["result"]
    vec = (res.get("config") or {}).get("params", {}).get("vectors", {})
    return {"points": res.get("points_count"), "size": vec.get("size"), "distance": vec.get("distance")}


def qdrant_snapshot(name: str, dst: Path) -> Dict:
    """스냅숏을 만들어 받고 서버 쪽 스냅숏은 지운다."""
    with _http("POST", f"{QDRANT_URL}/collections/{name}/snapshots?wait=true", b"", timeout=1800) as r:
        snap = json.loads(r.read())["result"]["name"]
    part = dst.with_suffix(dst.suffix + ".part")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _http("GET", f"{QDRANT_URL}/collections/{name}/snapshots/{snap}", timeout=1800) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        part.replace(dst)
    finally:
        try:
            _http("DELETE", f"{QDRANT_URL}/collections/{name}/snapshots/{snap}", timeout=60).close()
        except Exception:  # noqa: BLE001 — 서버 쪽 스냅숏 지우기 실패는 백업을 막지 않는다(다음에 다시 지운다)
            pass
    return {"server_snapshot": snap}


def export(target: str) -> int:
    spec, out = TARGETS[target], _out(target)
    print(f"― 내보내기 · {target} → {out} ―", flush=True)
    t0 = time.time()
    files = []
    for name, src_name in spec["sqlite"]:
        src = config.DATA_DIR / src_name
        if not src.exists():
            print(f"  🔴 없음 {src}")
            return 1
        res = sqlite_copy(src, out / name)
        rows = table_rows(out / name, spec["tables"])
        files.append({"path": name, "kind": "sqlite", "bytes": (out / name).stat().st_size,
                      "sha256": _hd._sha256(out / name), "quick_check": res["quick_check"], "rows": rows})
        print(f"  ✅ {name} · {_hd._human((out / name).stat().st_size)} · quick_check {res['quick_check']} · "
              f"{', '.join(f'{k} {v:,}' for k, v in list(rows.items())[:5])}", flush=True)
    vectors = []
    for col in spec["qdrant"]:
        info = qdrant_info(col)
        path = f"qdrant/{col}.snapshot"
        res = qdrant_snapshot(col, out / path)
        vectors.append({"collection": col, "path": path, "bytes": (out / path).stat().st_size,
                        "sha256": _hd._sha256(out / path), **info})
        print(f"  ✅ Qdrant {col} · 점 {info['points']:,} · {info['size']}차원 {info['distance']} · "
              f"{_hd._human((out / path).stat().st_size)}", flush=True)
    man = {"target": target, "repo": spec["repo"], "about": spec["about"], "made_at": _hdart._now_kst(),
           "git": _hdart._git_info(), "files": files, "vectors": vectors, "seconds": round(time.time() - t0, 1)}
    _hdart._write_json(out / "manifest.json", man)
    (out / "README.md").write_text(_readme(man), encoding="utf-8")
    _hdart._write_json(out / "meta" / "last_export.json", {"at": man["made_at"], "seconds": man["seconds"]})
    print(f"  매니페스트 · 카드 · {man['seconds']}초", flush=True)
    return 0


def _readme(man: Dict) -> str:
    rows = "\n".join(f"| `{f['path']}` | {_hd._human(f['bytes'])} | `{f['sha256'][:16]}…` | "
                     + ", ".join(f"{k} {v:,}" for k, v in f["rows"].items()) + " |" for f in man["files"])
    vecs = "\n".join(f"| `{v['path']}` | {_hd._human(v['bytes'])} | `{v['sha256'][:16]}…` | 점 {v['points']:,} · "
                     f"{v['size']}차원 · {v['distance']} |" for v in man["vectors"])
    return f"""---
license: other
pretty_name: Qurious {man['target']} backup
---
# {man['repo']} — {man['about']}

Qurious 팀 **private** 백업(조직 안에서만). 수집 자료에서 다시 만들 수 있지만 오래 걸리는 계산물을 보관한다.
만든 때 {man['made_at']} · 코드 `{(man['git'] or {}).get('commit', '')[:10]}` · 만든 도구 `scripts/hf_local_backup.py`.

| 파일 | 크기 | sha256 | 내용 |
|---|---|---|---|
{rows}
{vecs}

## 되살리기
1. `huggingface_hub.snapshot_download("{man['repo']}", repo_type="dataset", revision=<태그 또는 커밋>)`
2. SQLite 파일을 `data/collector/` 에 둔다(앱이 읽기 전용으로 붙는다 — 롤백 저널 그대로 둔다).
3. 벡터가 있으면 `curl -X POST "http://127.0.0.1:16333/collections/<이름>/snapshots/upload?priority=snapshot" -F "snapshot=@qdrant/<이름>.snapshot"`.

## 이용 조건
- 법령 · 감독규정 원문은 공공 자료다. 검색 색인에는 공시 · 공공누리 제1유형 정책뉴스 본문 · 언론사 제목 · 주소(본문 없음)가 들어 있다 —
  수집 원자료의 이용 조건(재배포 금지 등)을 그대로 따르므로 **private 으로만** 둔다.
"""


# ==================================================
# 2. 올리기 · 대조
# ==================================================
def _local_ok(target: str, man: Dict) -> List[str]:
    out = _out(target)
    bad = [f"반쪽 파일 {p.relative_to(out).as_posix()}" for p in out.rglob("*.part")]
    for f in man.get("files", []) + man.get("vectors", []):
        p = out / f["path"]
        if not p.exists():
            bad.append(f"빠짐 {f['path']}")
        elif _hd._sha256(p) != f["sha256"]:
            bad.append(f"sha256 다름 {f['path']}")
    return bad


def _assert_private(api, repo: str) -> bool:
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(repo, repo_type="dataset")
    except Exception as e:  # noqa: BLE001
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 올리지 않는다")
        return False
    if info.private:
        print("  ✅ 관문 4 원격이 private 임을 확인했다")
        return True
    print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{repo}/settings 에서 Private 로.")
    return False


def upload(target: str, yes: bool) -> int:
    spec, out = TARGETS[target], _out(target)
    man = _hdart._read_json(out / "manifest.json")
    if not man:
        print(f"올릴 것이 없다 — `export {target}` 를 먼저 돌린다.")
        return 1
    bad = _local_ok(target, man)
    tag = f"{target}-{man['made_at'][:10]}"
    total = sum(f["bytes"] for f in man["files"] + man["vectors"])
    print(f"― 업로드 {target} {'(실행)' if yes else '(dry-run)'} · {spec['repo']} · {_hd._human(total)} · 태그 {tag} ―")
    print(f"  관문 1 공유 스위치 {'✅ 켜짐' if _hdart._sharing_on() else '🔴 꺼짐'}")
    print(f"  관문 2 로컬 파일 {'✅ 반쪽 0 · sha256 일치' if not bad else '🔴 ' + ' · '.join(bad[:5])}")
    print(f"  관문 3 hf_xet {'✅ 켜짐' if _hdart._xet_on() else '⚠️ 없음 — 파일 전체가 다시 올라간다'}")
    if not yes:
        print("  실제로 올리려면 `--yes` 를 준다.")
        return 0
    if not _hdart._sharing_on():
        print("  🔴 QURIOUS_RAW_SHARING 이 꺼져 있다 — bash `export QURIOUS_RAW_SHARING=1`")
        return 1
    if bad:
        print("  🔴 로컬 파일이 매니페스트와 다르다 — export 를 다시 돌린다")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=_hdart._token())
    if not _assert_private(api, spec["repo"]):
        return 1
    msg = f"Qurious {target} 백업 · {man['made_at']} · " + " · ".join(f["path"] for f in man["files"] + man["vectors"])
    t0 = time.time()
    info = api.upload_folder(repo_id=spec["repo"], repo_type="dataset", folder_path=str(out), commit_message=msg,
                             ignore_patterns=UPLOAD_IGNORE)
    commit = str(getattr(info, "oid", "") or "")
    note = "새로 닮"
    try:
        api.create_tag(spec["repo"], repo_type="dataset", tag=tag, tag_message=msg, revision=commit or None)
    except Exception as e:  # noqa: BLE001 — 같은 날 다시 올리면 태그는 그대로 둔다(대조는 커밋으로)
        note = f"이미 있어 그대로 둠({type(e).__name__})"
    print(f"  ✅ 올렸다 · 커밋 {commit[:8]} · {time.time() - t0:,.1f}초 · 태그 {tag} {note}", flush=True)
    _hdart._write_json(out / "meta" / "last_upload.json", {"at": _hdart._now_kst(), "repo": spec["repo"],
                                                           "commit": commit, "tag": tag, "bytes": total})
    return 0


def verify(target: str, keep: bool = False) -> int:
    """마지막으로 올린 커밋을 임시 폴더에 받아 ① sha256 ② SQLite 를 열어 quick_check · 행 수 ③ 벡터는 임시 컬렉션에
    되살려 점 수를 맞춘다(되살린 임시 컬렉션은 지운다)."""
    from huggingface_hub import snapshot_download
    spec, out = TARGETS[target], _out(target)
    man = _hdart._read_json(out / "manifest.json")
    last = _hdart._read_json(out / "meta" / "last_upload.json")
    if not man or not last:
        print("대조할 것이 없다 — export · upload 를 먼저")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix=f"qbk-{target}-"))
    bad: List[str] = []
    t0 = time.time()
    try:
        got = Path(snapshot_download(spec["repo"], repo_type="dataset", revision=last["commit"], local_dir=str(tmp),
                                     token=_hdart._token()))
        for f in man["files"] + man["vectors"]:
            p = got / f["path"]
            if not p.exists() or _hd._sha256(p) != f["sha256"]:
                bad.append(f"sha256 {f['path']}")
        for f in man["files"]:
            p = got / f["path"]
            if p.exists():
                rows = table_rows(p, spec["tables"])
                if rows != f["rows"]:
                    bad.append(f"행 수 {f['path']}")
                con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
                ok = con.execute("PRAGMA quick_check").fetchone()[0]
                con.close()
                if ok != "ok":
                    bad.append(f"quick_check {f['path']}: {ok}")
        for v in man["vectors"]:
            name = f"{v['collection']}_restore_{uuid.uuid4().hex[:6]}"
            p = got / v["path"]
            boundary = uuid.uuid4().hex
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"snapshot\"; filename=\"{p.name}\"\r\n"
                    f"Content-Type: application/octet-stream\r\n\r\n").encode() + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            try:
                _http("POST", f"{QDRANT_URL}/collections/{name}/snapshots/upload?priority=snapshot&wait=true", body,
                      {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=1800).close()
                pts = qdrant_info(name)["points"]
                if pts != v["points"]:
                    bad.append(f"벡터 점 수 {v['collection']}: 되살림 {pts} · 매니페스트 {v['points']}")
                else:
                    print(f"  ✅ 벡터 되살리기 {v['collection']} → 임시 {name} · 점 {pts:,}", flush=True)
            finally:
                try:
                    _http("DELETE", f"{QDRANT_URL}/collections/{name}", timeout=120).close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    secs = round(time.time() - t0, 1)
    _hdart._write_json(out / "meta" / "last_verify.json", {"at": _hdart._now_kst(), "commit": last["commit"],
                                                           "ok": not bad, "problems": bad, "seconds": secs})
    print(f"  {'✅ 대조 통과' if not bad else '🔴 ' + ' · '.join(bad)} · {secs}초", flush=True)
    return 0 if not bad else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python scripts/hf_local_backup.py", description="근거 DB · 벡터 · 검색 색인 HF 백업")
    p.add_argument("cmd", choices=["export", "upload", "verify", "all"])
    p.add_argument("target", choices=["kb", "search", "all"])
    p.add_argument("--yes", action="store_true")
    p.add_argument("--keep", action="store_true", help="verify: 받은 임시 폴더를 지우지 않는다")
    a = p.parse_args(argv)
    targets = list(TARGETS) if a.target == "all" else [a.target]
    code = 0
    for t in targets:
        if a.cmd in ("export", "all"):
            code |= export(t)
        if a.cmd in ("upload", "all") and not code:
            code |= upload(t, a.yes)
        if a.cmd in ("verify", "all") and not code and (a.cmd == "verify" or a.yes):
            code |= verify(t, a.keep)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
