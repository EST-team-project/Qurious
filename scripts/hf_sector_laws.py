"""HF ``qurious-quant/kb-sector-laws`` (private) — 섹터별 · 연도별 근거 법령 보관.

    PYTHONPATH=. python scripts/hf_sector_laws.py export           섹터 법령 DB → 섹터 폴더 · 해마다 파케이 · 매니페스트 · 카드
    PYTHONPATH=. python scripts/hf_sector_laws.py status [--remote] 로컬 · 마지막 올리기 · 대조 기록 (읽기만)
    PYTHONPATH=. python scripts/hf_sector_laws.py upload [--yes]    dry-run(기본) · 실제로 올리고 태그 ``sector-laws-<날짜>``
    PYTHONPATH=. python scripts/hf_sector_laws.py verify            올린 판을 임시 폴더에 받아 sha256 · 행 수 대조
    PYTHONPATH=. python scripts/hf_sector_laws.py weekly --yes      7일에 한 번 — 판 목록 대조 → 바뀌었으면 내보내기 · 올리기 · 대조(러너 단계)

받기는 `collector/kb_sector.py`(법령 API · 해마다 그해 시행 판). 이 파일은 그 결과를 파케이로 내보내고 올린다.
법령 · 시행령은 저작권 보호 대상이 아니지만(저작권법 제7조) 팀 데이터셋은 모두 private 로 둔다(같은 원칙 · 관문 4).
관문 넷은 `scripts/hf_dart.py` 와 같다 — 공유 스위치 · 로컬 sha256 · hf_xet · 원격 private 확인.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collector import config, kb_law, kb_sector  # noqa: E402
from collector.ohlcv import KST  # noqa: E402
import hf_dart as _dart  # noqa: E402  — 토큰 · 공유 스위치 · hf_xet · git 커밋 도우미를 같이 쓴다
import hf_dataset as _hd  # noqa: E402  — 파케이 옵션 · sha256 · 크기 표기

REPO_ID = "qurious-quant/kb-sector-laws"
OUT_DIR = config.DATA_DIR / "hf_sector_laws"          # data/collector/ 아래 — .gitignore 로 커밋에서 빠진다
META_DIR = OUT_DIR / "meta"
MANIFEST_PATH = META_DIR / "manifest.json"
LAST_UPLOAD = META_DIR / "last_upload.json"
LAST_VERIFY = META_DIR / "last_verify.json"
STATE_PATH = config.STATE_DIR / "kb_sector_last.json"  # 매주 대조 기록(마지막 대조 시각 · 결과)
UPLOAD_IGNORE = ["*.part", "*.tmp", "meta/last_*.json", "logs/*", ".cache/**"]
WEEK_DAYS = 7

COLUMNS = [("sector_code", "string"), ("sector", "string"), ("year", "int64"), ("as_of", "string"), ("title", "string"),
           ("parent", "string"), ("role", "string"), ("law_type", "string"), ("dept", "string"), ("source_id", "string"),
           ("effective_at", "string"), ("promulgation_no", "string"), ("promulgated_at", "string"), ("status", "string"),
           ("seq", "int64"), ("label", "string"), ("heading", "string"), ("part", "string"), ("text", "string"),
           ("source_url", "string")]


def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ==================================================
# export
# ==================================================
def export(quiet: bool = False) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not kb_sector.DB_PATH.exists():
        print("🔴 섹터 법령 DB 가 없다 — `python -m collector.kb_sector fetch` 를 먼저")
        return 1
    rows = kb_sector.load_map()
    conn = kb_sector.connect()
    t0 = time.time()
    schema = pa.schema([pa.field(n, getattr(pa, t)()) for n, t in COLUMNS])
    opts = {k: v for k, v in _hd.PARQUET_OPTS.items() if k != "row_group_size"}
    docs = {r["title"]: dict(r) for r in conn.execute("SELECT * FROM ks_doc")}
    files: List[Dict] = []
    keep = set()
    try:
        years = [r[0] for r in conn.execute("SELECT DISTINCT year FROM ks_choice ORDER BY year")]
        for code in kb_sector.SECTOR_CODES:
            mine = [r for r in rows if r.sector_code == code]
            # 섹터의 문서 = 표의 법률 + decree=Y 인 법률의 시행령(표 차례)
            titles = [(r.title, r.role, "") for r in mine] + [(f"{r.title} 시행령", r.role, r.title) for r in mine if r.decree]
            for y in years:
                cols: Dict[str, list] = {n: [] for n, _ in COLUMNS}
                for title, role, parent in titles:
                    ch = conn.execute("SELECT * FROM ks_choice WHERE title=? AND year=?", (title, y)).fetchone()
                    if ch is None:
                        continue
                    doc = docs.get(title, {})
                    url = kb_law.source_url(kb_law.DocSpec("x", title, "law", 1),
                                            kb_law.Version(source_id=ch["source_id"], promulgation_no=ch["promulgation_no"],
                                                           promulgated_at=ch["promulgated_at"], effective_at=ch["effective_at"]))
                    for a in conn.execute("SELECT seq, label, heading, part, text FROM ks_article WHERE title=? AND year=? "
                                          "ORDER BY seq", (title, y)):
                        for n, v in (("sector_code", code), ("sector", kb_sector.SECTOR_NAMES[code]), ("year", y),
                                     ("as_of", ch["as_of"]), ("title", title), ("parent", parent), ("role", role),
                                     ("law_type", doc.get("law_type", "")), ("dept", doc.get("dept", "")),
                                     ("source_id", ch["source_id"]), ("effective_at", ch["effective_at"]),
                                     ("promulgation_no", ch["promulgation_no"]), ("promulgated_at", ch["promulgated_at"]),
                                     ("status", ch["status"]), ("seq", a["seq"]), ("label", a["label"]),
                                     ("heading", a["heading"]), ("part", a["part"]), ("text", a["text"]), ("source_url", url)):
                            cols[n].append(v)
                if not cols["title"]:
                    continue
                out = OUT_DIR / "by_sector" / code / f"{y}.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".parquet.part")
                table = pa.table({n: pa.array(cols[n], type=schema.field(n).type) for n, _ in COLUMNS}, schema=schema)
                pq.write_table(table, str(tmp), row_group_size=_hd.PARQUET_OPTS["row_group_size"], **opts)
                tmp.replace(out)
                rel = out.relative_to(OUT_DIR).as_posix()
                keep.add(rel)
                files.append({"path": rel, "sector_code": code, "year": y, "rows": table.num_rows,
                              "docs": len(set(cols["title"])), "bytes": out.stat().st_size, "sha256": _hd._sha256(out)})
        choices = [dict(r) for r in conn.execute(
            "SELECT title, year, as_of, source_id, effective_at, promulgation_no, status, n_articles, content_sha256, notes "
            "FROM ks_choice ORDER BY title, year")]
        doc_rows = [dict(r) for r in conn.execute("SELECT * FROM ks_doc ORDER BY title")]
    finally:
        conn.close()
    if files:                                  # 이번에 쓴 것이 0 이면 옛 파일을 지우지 않는다(S87 규칙)
        for old in sorted((OUT_DIR / "by_sector").rglob("*.parquet")):
            if old.relative_to(OUT_DIR).as_posix() not in keep:
                old.unlink()
    META_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(kb_sector.MAP_PATH, META_DIR / "sector_laws.tsv")
    man = {"dataset": REPO_ID, "schema": 1, "built_at": _now_kst(), "code": _dart._git_info(),
           "rule": "해마다 그해 12월 31일(올해는 받은 날)에 시행 중인 판 — kb_text.select_version + kb_law.check_later",
           "parquet_opts": _hd.PARQUET_OPTS, "years": sorted({f["year"] for f in files}),
           "files": files, "documents": doc_rows, "choices": choices}
    _dart._write_json(MANIFEST_PATH, man)
    (OUT_DIR / "README.md").write_text(_readme(man, rows), encoding="utf-8")
    if not quiet:
        tot = sum(f["bytes"] for f in files)
        print(f"  ✅ 내보내기 — 파일 {len(files)} · 행 {sum(f['rows'] for f in files):,} · {_hd._human(tot)} · "
              f"{time.time() - t0:,.1f}초")
    return 0


def _readme(man: Dict, rows) -> str:
    docs = man["documents"]
    L = ["---", "license: other", "language: [ko]", "pretty_name: 섹터별 · 연도별 근거 법령 (Qurious)", "viewer: false",
         "tags: [law, korea, sector, gics]", "---", "",
         "# 섹터별 · 연도별 근거 법령 — `kb-sector-laws`", "",
         "Qurious 근거 답(RAG)의 근거 문서를 **섹터(산업)별 · 연도별**로 모은 보관본이다. 섹터는 우리 섹터 분류(GICS 11섹터 꼴)와 같고, "
         "「공통」 은 모든 상장사에 걸리는 법이다.", "",
         f"- 만든 시각 {man['built_at']} · 만든 코드 Qurious `{man['code'].get('commit', '')}`"
         + (" + 커밋 전 변경" if man["code"].get("dirty") else "") + " · `scripts/hf_sector_laws.py export`",
         f"- 해: {', '.join(str(y) for y in man['years'])} · 문서 {len(docs)}개(법률 · 시행령) · 파일 {len(man['files'])}개",
         f"- 판 고르기: {man['rule']}", "",
         "## 출처와 이용 조건", "",
         "- 국가법령정보센터 Open API(법제처 · `target=eflaw` 시행일 판). 행마다 `source_url` 이 그 판의 국가법령정보센터 화면이다.",
         "- 법령은 저작권법 제7조(보호받지 못하는 저작물) 「헌법 · 법률 · 조약 · 명령 · 조례 및 규칙」 에 든다. 팀 데이터셋은 원칙대로 private 로 둔다.",
         "- 법률 해석이나 투자 판단의 근거로 그대로 쓰지 않는다 — 시행일 · 부칙의 경과 규정은 원문을 다시 확인한다.", "",
         "## 파일", "", "- `by_sector/<섹터코드>/<해>.parquet` — 그 섹터 법령들의 그해 판 조문(한 행 = 조 하나 · 삭제 조 없음)",
         "- `meta/sector_laws.tsv` — 섹터 ↔ 법령 표(역할 · 시행령 포함 여부 · 고른 까닭)", "- `meta/manifest.json` — 파일 · 행 · sha256 · 해마다 고른 판", "",
         "## 섹터 ↔ 법령", "", "| 섹터 | 법령 | 역할 | 시행령 | 고른 까닭 |", "|---|---|---|:-:|---|"]
    for r in rows:
        L.append(f"| {r.sector}({r.sector_code}) | {r.title} | {r.role} | {'○' if r.decree else ''} | {r.why.replace('|', '/')} |")
    L += ["", "## 칸", "", "| 칸 | 뜻 |", "|---|---|",
          "| `sector_code` · `sector` | 섹터 코드 · 이름(섹터 파일과 같음 · All = 공통) |",
          "| `year` · `as_of` | 해 · 기준일(그해 12-31 · 올해는 받은 날) |",
          "| `title` · `parent` | 문서 이름 · 시행령이면 그 법률 |", "| `role` | 업법(그 사업의 진입 · 영업 규칙) · 관련(원가 · 매출에 닿는 법) |",
          "| `law_type` · `dept` | 법률 · 대통령령 · 소관 부처 |",
          "| `source_id` · `effective_at` · `promulgation_no` · `promulgated_at` · `status` | 고른 판의 법령일련번호 · 시행일 · 공포번호 · 공포일 · 받을 때 표시 |",
          "| `seq` · `label` · `heading` · `part` · `text` | 조 차례 · 제N조 · 조 제목 · 편장절 · 조 글 |", "| `source_url` | 그 판의 국가법령정보센터 화면 |", ""]
    return "\n".join(L)


# ==================================================
# status · upload · verify
# ==================================================
def status(remote: bool = False) -> int:
    man = _dart._read_json(MANIFEST_PATH)
    if man:
        print(f"― 로컬 · 만든 시각 {man['built_at']} · 해 {man['years']} · 파일 {len(man['files'])} · "
              f"행 {sum(f['rows'] for f in man['files']):,} · {_hd._human(sum(f['bytes'] for f in man['files']))}")
    else:
        print("― 로컬 내보내기 없음")
    for label, p in (("마지막 올리기", LAST_UPLOAD), ("마지막 대조", LAST_VERIFY), ("매주 대조", STATE_PATH)):
        d = _dart._read_json(p)
        if d:
            print(f"― {label}: {json.dumps(d, ensure_ascii=False)[:500]}")
    if remote:
        tok = _dart._token(required=False)
        if tok:
            from huggingface_hub import HfApi
            try:
                info = HfApi(token=tok).repo_info(REPO_ID, repo_type="dataset")
                print(f"― 원격 {REPO_ID} · {'private ✅' if info.private else '🔴 public'} · 파일 {len(info.siblings or [])} · "
                      f"마지막 커밋 {str(info.sha)[:8]}")
            except Exception as e:
                print(f"― 원격 {REPO_ID} · 아직 없거나 권한이 없다({type(e).__name__})")
    return 0


def _assert_private(api) -> bool:
    api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 올리지 않는다")
        return False
    if not info.private:
        print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{REPO_ID}/settings")
        return False
    print("  ✅ 관문 4 원격이 private 임을 확인했다")
    return True


def upload(yes: bool) -> int:
    man = _dart._read_json(MANIFEST_PATH)
    if not man:
        print("올릴 것이 없다 — export 를 먼저")
        return 1
    bad = [f["path"] for f in man["files"] if not (OUT_DIR / f["path"]).exists()
           or _hd._sha256(OUT_DIR / f["path"]) != f["sha256"]] + [str(p) for p in OUT_DIR.rglob("*.part")]
    tag = f"sector-laws-{datetime.now(KST).strftime('%Y-%m-%d')}"
    print(f"― 업로드 {'(실행)' if yes else '(dry-run)'} · {REPO_ID} · 태그 {tag} · 파일 {len(man['files'])}")
    print(f"  관문 1 공유 스위치 {'✅' if _dart._sharing_on() else '🔴 꺼짐'} · 관문 2 로컬 {'✅' if not bad else '🔴 ' + ' · '.join(bad[:3])}"
          f" · 관문 3 hf_xet {'✅' if _dart._xet_on() else '⚠️ 없음'}")
    if not yes:
        print("  실제로 올리려면 `--yes`")
        return 0
    if not _dart._sharing_on() or bad:
        print("  🔴 관문을 넘지 못했다 — 올리지 않는다")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=_dart._token())
    if not _assert_private(api):
        return 1
    msg = (f"섹터별 · 연도별 근거 법령 · 해 {man['years'][0]}~{man['years'][-1]} · 파일 {len(man['files'])} · "
           f"행 {sum(f['rows'] for f in man['files']):,}")
    t0 = time.time()
    info = api.upload_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=str(OUT_DIR), commit_message=msg,
                             ignore_patterns=UPLOAD_IGNORE)
    commit = str(getattr(info, "oid", "") or "")
    try:
        api.create_tag(REPO_ID, repo_type="dataset", tag=tag, tag_message=msg, revision=commit or None)
        note = "새로 닮"
    except Exception as e:
        note = f"이미 있어 그대로 둠({type(e).__name__})"
    print(f"  ✅ 올렸다 · 커밋 {commit[:8]} · 태그 {tag} {note} · {time.time() - t0:,.1f}초")
    _dart._write_json(LAST_UPLOAD, {"at": _now_kst(), "commit": commit, "tag": tag, "tag_note": note,
                                    "files": {f["path"]: f["sha256"] for f in man["files"]}})
    return 0


def verify(keep: bool = False) -> int:
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    last, man = _dart._read_json(LAST_UPLOAD), _dart._read_json(MANIFEST_PATH)
    if not last or not man:
        print("🔴 올린 기록이나 매니페스트가 없다")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="hf_sector_verify_"))
    checks = []
    try:
        snapshot_download(repo_id=REPO_ID, repo_type="dataset", revision=last["commit"], local_dir=str(tmp),
                          token=_dart._token())
        rman = _dart._read_json(tmp / "meta" / "manifest.json")
        same = {f["path"]: f["sha256"] for f in rman.get("files", [])} == {f["path"]: f["sha256"] for f in man["files"]}
        checks.append(("원격 매니페스트 = 로컬", same))
        bad = [f["path"] for f in rman.get("files", []) if not (tmp / f["path"]).exists()
               or _hd._sha256(tmp / f["path"]) != f["sha256"] or pq.ParquetFile(str(tmp / f["path"])).metadata.num_rows != f["rows"]]
        checks.append((f"받은 파일 sha256 · 행 수({len(rman.get('files', []))}개)", not bad))
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    ok = all(g for _, g in checks)
    for n, g in checks:
        print(f"  {'✅' if g else '🔴'} {n}")
    _dart._write_json(LAST_VERIFY, {"at": _now_kst(), "revision": last["commit"], "ok": ok,
                                    "checks": [{"name": n, "ok": g} for n, g in checks]})
    return 0 if ok else 1


# ==================================================
# weekly — 러너 단계(7일에 한 번)
# ==================================================
def weekly(yes: bool, force: bool = False, quiet: bool = True) -> int:
    from datetime import date

    st = _dart._read_json(STATE_PATH)
    last = st.get("checked_at", "")
    if last and not force:
        try:
            if datetime.now(KST) - datetime.fromisoformat(last) < timedelta(days=WEEK_DAYS):
                print(f"  건너뜀 — 마지막 대조 {last}(7일 안)")
                return 0
        except ValueError:
            pass
    conn = kb_sector.connect()
    client = kb_sector.CachedClient(kb_law.LawClient(conn=conn), conn, max_calls=1500)
    today = date.today()
    try:
        r = kb_sector.fetch(conn, client, kb_sector.documents(kb_sector.load_map()),
                            kb_sector.parse_years("", today), today, quiet=quiet)
    finally:
        conn.close()
    prev = {f["path"]: f["sha256"] for f in _dart._read_json(MANIFEST_PATH).get("files", [])}
    code = export(quiet=quiet)
    now = {f["path"]: f["sha256"] for f in _dart._read_json(MANIFEST_PATH).get("files", [])}
    changed = sorted(p for p in now if now[p] != prev.get(p)) + sorted(p for p in prev if p not in now)
    up = (_dart._read_json(LAST_UPLOAD).get("files") or {})
    need = code == 0 and (changed or now != up)
    out = {"checked_at": _now_kst(), "fetch": r, "calls": client.calls, "changed_files": changed[:20],
           "uploaded": False}
    if need and yes:
        code = upload(True) or verify()
        out["uploaded"] = code == 0
    _dart._write_json(STATE_PATH, out)
    print(f"  매주 대조 — 해 새로 {r['years_new']} · 그대로 {r['years_same']} · 호출 {client.calls} · 바뀐 파일 {len(changed)} · "
          f"올림 {'예' if out['uploaded'] else '아니오'}")
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/hf_sector_laws.py", description=f"HF {REPO_ID} (private)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    p = sub.add_parser("status")
    p.add_argument("--remote", action="store_true")
    p = sub.add_parser("upload")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--keep", action="store_true")
    p = sub.add_parser("weekly")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--force", action="store_true", help="7일 안이어도 대조한다")
    p.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        return export()
    if a.cmd == "status":
        return status(a.remote)
    if a.cmd == "upload":
        return upload(a.yes)
    if a.cmd == "verify":
        return verify(a.keep)
    return weekly(a.yes, a.force, a.quiet)


if __name__ == "__main__":
    sys.exit(main())
