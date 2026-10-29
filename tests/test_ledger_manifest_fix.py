"""TC-LM — 원장 지문 목록(manifest.json)의 바이트 지문 정정 계산 (scripts/ledger_manifest_fix.py · 이슈 #400 · 2026-10-29)

원격에는 아무것도 하지 않는 순수 계산만 시험한다(실제 올리기는 사람이 `--yes` 로).
지키는 것
1. 같은 내용인데 바이트만 다른 항목만 정정하고, 정정본은 추가만 규칙(immutability_problems)을 통과한다. (TC-LM-01)
2. 내용이 다르거나 읽지 못했거나 파일이 없으면 하나도 정정하지 않는다 — 검증 우회가 아니다. (TC-LM-02)
3. 바이트 지문이 이미 맞는 항목은 건드리지 않고 내용도 보지 않는다. 입력은 바뀌지 않는다. (TC-LM-03)
4. 스크립트는 manifest.json 한 파일만 올리고 parent_commit 으로 머리를 걸고, 올린 뒤 다시 받아 확인한다(소스). (TC-LM-04)
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.paper_journal import immutability_problems  # noqa: E402
from scripts import ledger_manifest_fix as fix  # noqa: E402

SRC = (ROOT / "scripts" / "ledger_manifest_fix.py").read_text(encoding="utf-8")


def _manifest():
    return {"schema": 1, "counts": {"version": 1, "day": 2, "note": 0}, "files": {
        "versions/r-v1.json": {"kind": "version", "bytes": 10, "sha256": "aa", "content_sha256": "c1"},
        "rows/r/v1/2026-09-01.parquet": {"kind": "day", "bytes": 100, "sha256": "bb", "content_sha256": "c2"},
        "rows/r/v1/2026-09-02.parquet": {"kind": "day", "bytes": 100, "sha256": "cc", "content_sha256": "c3"},
    }}


def _actual():
    return {
        "versions/r-v1.json": {"bytes": 10, "sha256": "aa", "content_sha256": ""},              # 바이트가 맞아 내용은 안 쟀다
        "rows/r/v1/2026-09-01.parquet": {"bytes": 120, "sha256": "bb2", "content_sha256": "c2"},  # 같은 내용 · 다른 바이트
        "rows/r/v1/2026-09-02.parquet": {"bytes": 100, "sha256": "cc", "content_sha256": ""},
    }


def test_corrects_only_same_content_different_bytes_and_passes_append_only():
    """TC-LM-01 · 같은 내용 · 다른 바이트 항목만 sha256 · bytes 를 실제 값으로 — 내용 지문 · kind · counts 는 그대로 · 추가만 통과."""
    man = _manifest()
    out, fixed, problems = fix.plan_correction(man, _actual())
    assert problems == [] and fixed == ["rows/r/v1/2026-09-01.parquet"]
    f = out["files"]["rows/r/v1/2026-09-01.parquet"]
    assert (f["sha256"], f["bytes"], f["content_sha256"], f["kind"]) == ("bb2", 120, "c2", "day")
    assert out["counts"] == man["counts"] and out["schema"] == 1
    assert immutability_problems(man, out) == []


def test_refuses_all_correction_when_any_content_differs_or_is_unreadable_or_missing():
    """TC-LM-02 · 문제가 하나라도 있으면 정정본은 원본 그대로 · 정정한 경로 0 — 내용이 다른 파일을 지문 맞추기로 덮지 않는다."""
    man = _manifest()
    cases = {
        "내용 지문이 다르다": {"rows/r/v1/2026-09-01.parquet": {"bytes": 120, "sha256": "bb2", "content_sha256": "다른내용"}},
        "내용을 읽지 못했다": {"rows/r/v1/2026-09-01.parquet": {"bytes": 120, "sha256": "bb2", "content_sha256": ""}},
    }
    for why, patch in cases.items():
        actual = {**_actual(), **patch}
        out, fixed, problems = fix.plan_correction(man, actual)
        assert fixed == [] and out == man and len(problems) == 1 and why in problems[0], (why, problems)
    missing = _actual()
    del missing["rows/r/v1/2026-09-02.parquet"]
    out, fixed, problems = fix.plan_correction(man, missing)
    assert fixed == [] and out == man and "원격에 파일이 없다" in problems[0]
    # 한 항목은 고칠 수 있어도 다른 항목에 문제가 있으면 아무것도 고치지 않는다
    mixed = {**_actual(), "rows/r/v1/2026-09-02.parquet": {"bytes": 1, "sha256": "zz", "content_sha256": "다름"}}
    out, fixed, problems = fix.plan_correction(man, mixed)
    assert fixed == [] and out == man and len(problems) == 1


def test_leaves_matching_entries_alone_and_does_not_mutate_input():
    """TC-LM-03 · 이미 맞는 항목은 그대로 · 바이트 지문이 같으면 내용 지문이 비어 있어도 문제가 아니다 · 입력 사전은 바뀌지 않는다."""
    man, snapshot = _manifest(), copy.deepcopy(_manifest())
    actual = {rel: {"bytes": m["bytes"], "sha256": m["sha256"], "content_sha256": ""} for rel, m in man["files"].items()}
    out, fixed, problems = fix.plan_correction(man, actual)
    assert fixed == [] and problems == [] and out == man
    fix.plan_correction(man, _actual())
    assert man == snapshot


def test_script_uploads_only_manifest_pins_parent_and_verifies_after():
    """TC-LM-04 · 올리는 것은 manifest.json 하나 · parent_commit 으로 점검한 머리를 건다 · private · 공유 스위치 관문 · 올린 뒤 다시 받아 확인."""
    assert SRC.count("CommitOperationAdd(") == 1 and 'path_in_repo="manifest.json"' in SRC
    assert "parent_commit=head" in SRC
    assert "_assert_private(api, create=False)" in SRC and "_sharing_on()" in SRC
    assert "올린 뒤 확인" in SRC and SRC.index("api.create_commit") < SRC.index("올린 뒤 확인")
    assert "if not a.yes:" in SRC and SRC.index("if not a.yes:") < SRC.index("api.create_commit")      # 점검만이 기본
    assert "immutability_problems(manifest, corrected)" in SRC
