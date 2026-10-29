"""원장 지문 목록(manifest.json)의 바이트 지문을 원격 실제 바이트로 정정한다 (이슈 #400 · 2026-10-29).

    python scripts/ledger_manifest_fix.py          점검만(dry-run) — 원격을 임시 폴더에 받아 읽기만 한다. 아무것도 올리지 않는다
    python scripts/ledger_manifest_fix.py --yes    manifest.json **한 파일**만 올린다(정정본) — 원장 파일은 건드리지 않는다

왜: 원장(`qurious-quant/qurious-paper-log`)의 지문 목록에 적힌 바이트 지문(`sha256` · `bytes`)이 원격 실제 파일과 어긋난 항목이
있다 — 2026-10-28(#377) 이전의 올리기가 올리지 않은 기존 파일의 지문까지 자기 PC 의 pyarrow 로 만든 바이트로 덮었기 때문이다
(이후 올리기는 `keep_remote_meta` 로 원격 지문을 그대로 둔다). 내용은 같고(내용 지문 `content_sha256` 일치) 바이트만 다르다.
받는 쪽은 바이트가 어긋나면 내용 지문으로 한 번 더 대조하는데, 그 계산이 어떤 PC 에서는 다르게 나와 막힌다(#400).
지문 목록의 바이트 지문을 실제 바이트로 맞추면 바이트 대조에서 바로 통과하므로 받는 PC 의 pyarrow · 코드 판과 상관없이 풀린다.

지키는 것
- **원장 파일은 그대로** — 올리는 것은 manifest.json 하나. `content_sha256` · `kind` · `counts` 는 그대로고, 추가만 규칙
  (`immutability_problems`)을 통과해야 한다.
- **내용이 다른 파일이 하나라도 있으면 정정하지 않는다** — 정정은 「같은 내용인데 바이트만 다른」 항목에만 쓴다. 내용이 다르거나
  읽지 못하거나 파일이 없으면 무결성 문제이므로 사람이 본다(검증 우회 아님).
- **원격 머리가 그 사이 움직이면 거절** — 점검한 머리를 `parent_commit` 으로 건다(12:30 회차 올리기와 겹쳐도 덮어쓰지 않는다).
- 올린 뒤 **새 머리를 다시 받아** 모든 파일의 바이트 지문이 지문 목록과 같은지 확인한다.
- 실행은 `QURIOUS_RAW_SHARING=1` 일 때만(올리기와 같은 관문) · 원격이 private 임을 확인한 뒤에만.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMMIT_MESSAGE = "원장 지문 목록 정정(#400) — 바이트 지문(sha256 · bytes)을 원격 실제 파일에 맞춤 · 원장 파일 · 내용 지문은 그대로"


def plan_correction(manifest: dict, actual: dict[str, dict]) -> tuple[dict, list[str], list[str]]:
    """(정정한 지문 목록, 정정한 경로, 문제) — 순수 계산이라 시험이 직접 부른다.

    actual[경로] = {"bytes": 실제 크기, "sha256": 실제 바이트 지문, "content_sha256": 실제 내용 지문(못 읽었으면 "")}.
    파일이 없는 경로는 actual 에 키가 없다. 바이트 지문이 이미 같은 항목은 내용을 보지 않는다(받는 쪽 검사와 같은 순서).
    문제가 하나라도 있으면 정정본은 원본 그대로이고 정정한 경로는 비어 있다 — 호출자는 올리지 않는다.
    """
    problems: list[str] = []
    fixed: list[str] = []
    out = copy.deepcopy(manifest)
    for rel, meta in sorted((manifest.get("files") or {}).items()):
        got = actual.get(rel)
        if got is None:
            problems.append(f"{rel} — 지문 목록에는 있는데 원격에 파일이 없다")
            continue
        if got.get("sha256") == meta.get("sha256") and got.get("bytes") == meta.get("bytes"):
            continue
        if not got.get("content_sha256"):
            problems.append(f"{rel} — 내용을 읽지 못했다(바이트가 달라 내용으로 확인해야 하는데 확인 못 함)")
        elif got["content_sha256"] != meta.get("content_sha256"):
            problems.append(f"{rel} — 내용 지문이 다르다(같은 내용인데 바이트만 다른 경우가 아니다)")
        else:
            out["files"][rel]["sha256"] = got["sha256"]
            out["files"][rel]["bytes"] = got["bytes"]
            fixed.append(rel)
    if problems:
        return manifest, [], problems
    return out, fixed, []


def _measure(root: Path, manifest: dict, pj, app_pj) -> dict[str, dict]:
    """받은 폴더의 실제 값 — 바이트 지문이 어긋난 파일만 내용 지문을 잰다."""
    actual: dict[str, dict] = {}
    for rel, meta in (manifest.get("files") or {}).items():
        p = root / rel
        if not p.exists():
            continue
        data = p.read_bytes()
        row = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "content_sha256": ""}
        if row["sha256"] != meta.get("sha256") or row["bytes"] != meta.get("bytes"):
            try:
                row["content_sha256"] = app_pj.content_sha(pj._ledger_record(p))
            except Exception:
                row["content_sha256"] = ""
        actual[rel] = row
    return actual


def _download(api, repo_id: str, head: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="qurious-manifest-fix-"))
    api.snapshot_download(repo_id, repo_type="dataset", revision=head, local_dir=str(root))
    return root


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="원장 지문 목록의 바이트 지문 정정(#400)")
    ap.add_argument("--yes", action="store_true", help="정정본 manifest.json 을 실제로 올린다(없으면 점검만)")
    a = ap.parse_args(argv)

    import pyarrow
    from huggingface_hub import CommitOperationAdd, HfApi

    from app.services import paper_journal as app_pj
    from scripts import paper_journal as pj

    api = HfApi(token=pj._token())
    print(f"― 원장 지문 목록 정정 {'(실행)' if a.yes else '(점검만 — 아무것도 올리지 않는다)'} · {pj.REPO_ID} · 이 PC pyarrow {pyarrow.__version__}")
    if not pj._assert_private(api, create=False):
        return 1
    head = api.repo_info(pj.REPO_ID, repo_type="dataset").sha
    root = _download(api, pj.REPO_ID, head)
    try:
        manifest = pj._read_json(root / "manifest.json")
        if not manifest.get("files"):
            print("  🔴 원격 manifest.json 을 읽지 못했거나 비어 있다 — 정정할 수 없다")
            return 1
        actual = _measure(root, manifest, pj, app_pj)
        corrected, fixed, problems = plan_correction(manifest, actual)
        total = len(manifest["files"])
        print(f"  원격 머리 {head[:12]} · 파일 {total}개 · 바이트 지문이 이미 맞음 {total - len(fixed) - len(problems)} · 정정 대상 {len(fixed)} · 문제 {len(problems)}")
        for rel in fixed[:5]:
            print(f"    정정: {rel}  {str(manifest['files'][rel].get('sha256'))[:12]} → {corrected['files'][rel]['sha256'][:12]}")
        if len(fixed) > 5:
            print(f"    … 외 {len(fixed) - 5}개")
        if problems:
            print("  🔴 정정할 수 없다 — 무결성 문제가 있다(사람이 본다. 검증을 우회하지 않는다):")
            for p in problems[:10]:
                print(f"     {p}")
            return 1
        bad = app_pj.immutability_problems(manifest, corrected)
        if bad:
            print(f"  🔴 추가만 위반 {len(bad)}건 — 올리지 않는다: {bad[:3]}")
            return 1
        if not fixed:
            print("  ✅ 정정할 것이 없다 — 바이트 지문이 모두 원격과 같다")
            return 0
        print("  ✅ 점검 통과 — 정정 대상은 모두 내용이 같고 바이트만 다르다 · 원장 파일은 올리지 않는다(manifest.json 하나)")
        if not a.yes:
            print("  실제로 올리려면 같은 명령에 `--yes` (QURIOUS_RAW_SHARING=1 필요 · 12:30 회차가 도는 동안은 피한다)")
            return 0
        if not pj._sharing_on():
            print("  🔴 QURIOUS_RAW_SHARING 이 꺼져 있다 — PowerShell `$env:QURIOUS_RAW_SHARING=\"1\"` · bash `export QURIOUS_RAW_SHARING=1`")
            return 1
        body = json.dumps(corrected, ensure_ascii=False, indent=1, default=str).encode("utf-8")
        try:
            info = api.create_commit(
                repo_id=pj.REPO_ID, repo_type="dataset", commit_message=COMMIT_MESSAGE, parent_commit=head,
                operations=[CommitOperationAdd(path_in_repo="manifest.json", path_or_fileobj=body)])
        except Exception as exc:                      # 머리가 그 사이 움직였거나 네트워크 — 아무것도 바뀌지 않았다
            print(f"  🔴 올리지 못했다({type(exc).__name__}: {str(exc)[:200]}) — 원격은 그대로다. 다시 점검부터")
            return 1
        new_head = str(getattr(info, "oid", "") or "")
        print(f"  ✅ 올렸다 — manifest.json 정정 {len(fixed)}개 · 커밋 {new_head[:8]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # 올린 뒤 새 머리를 다시 받아, 모든 파일의 바이트 지문이 지문 목록과 같은지(받는 쪽이 내용 대조 없이 통과하는지) 확인한다
    root2 = _download(api, pj.REPO_ID, new_head)
    try:
        man2 = pj._read_json(root2 / "manifest.json")
        left = [rel for rel, m in man2["files"].items()
                if not (root2 / rel).exists() or hashlib.sha256((root2 / rel).read_bytes()).hexdigest() != m.get("sha256")]
        if left:
            print(f"  🔴 올린 뒤 확인 — 바이트 지문이 아직 다른 파일 {len(left)}개: {left[:3]}")
            return 1
        print(f"  ✅ 올린 뒤 확인 — 파일 {len(man2['files'])}개 모두 바이트 지문이 지문 목록과 같다(내용 대조 없이 통과)")
    finally:
        shutil.rmtree(root2, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
