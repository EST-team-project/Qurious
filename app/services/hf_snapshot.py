"""#280: 같은 HF 커밋의 사용 준비 근거. 전체 회차 종료 시각을 만들지 않는다."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROOF_VERSION = 1
REQUIRED_STEPS = ("price", "calendar", "export", "verify")
POST_UPLOAD_STEPS = {"upload", "ohlcv_upload", "journal_upload", "sector_laws"}


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ValueError("snapshot timestamp is missing or has no timezone") from None


def manifest_fingerprint(manifest):
    # scripts.hf_dataset._manifest_fp와 같은 파일 경로+SHA-256 계약.
    items = sorted((f["path"], f.get("sha256", ""))
                   for table in manifest["tables"].values() for f in table["files"])
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


def validate_snapshot(commit, record, manifest, verification, *, now=None):
    """메타데이터 결합 검사. 실제 파일 지문·복원·DB 무결성 검사는 받는 쪽에서 수행한다."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("snapshot commit must be an immutable SHA")
    tables = manifest.get("tables")
    if manifest.get("partial") is not False or not isinstance(tables, dict) or not {"price_daily", "price_adjusted", "market_calendar"} <= tables.keys():
        raise ValueError("snapshot manifest is incomplete")
    paths, size = set(), 0
    for table in tables.values():
        if not isinstance(table.get("files"), list) or not table["files"]:
            raise ValueError("snapshot table files are missing")
        for item in table["files"]:
            path = PurePosixPath(item["path"])
            if path.is_absolute() or ".." in path.parts or not path.parts or path.as_posix() in paths:
                raise ValueError("unsafe or duplicate manifest path")
            if not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")) or type(item.get("bytes")) is not int or item["bytes"] < 0:
                raise ValueError("invalid manifest file digest or size")
            paths.add(path.as_posix())
            size += item["bytes"]
    if len(paths) > 5000 or size > 20 * 1024**3:
        raise ValueError("snapshot exceeds local sync limits")
    fingerprint = manifest_fingerprint(manifest)
    if (verification.get("full") is not True or type(verification.get("fails")) is not int
            or verification["fails"] != 0 or type(verification.get("checks")) is not int or verification["checks"] <= 0
            or verification.get("manifest_fp") != fingerprint
            or verification.get("manifest_generated_at") != manifest.get("generated_at")):
        raise ValueError("verification does not prove this manifest")
    run = record.get("run") or {}
    if run.get("stopped") is not None or run.get("only") or run.get("fill") or run.get("skipped"):
        raise ValueError("snapshot is not an uninterrupted full collection run")
    times = [timestamp(v) for v in (run.get("started_at"), manifest.get("generated_at"),
                                   verification.get("at"), run.get("recorded_at"))]
    if not times[0] <= times[1] <= times[2] <= times[3] <= now:
        raise ValueError("snapshot metadata belongs to different runs or the future")
    for name in REQUIRED_STEPS:
        rows = [s for s in run.get("steps", []) if s.get("name") == name]
        if len(rows) != 1 or type(rows[0].get("rc")) is not int or rows[0]["rc"] != 0 or rows[0].get("warn"):
            raise ValueError(f"required snapshot step did not succeed: {name}")
    pending = run.get("pending_steps")
    if (not isinstance(pending, list) or not pending or pending[0] != "upload"
            or any(not isinstance(s, str) for s in pending) or len(set(pending)) != len(pending)
            or not set(pending) <= POST_UPLOAD_STEPS):
        raise ValueError("remaining steps may still change the collection database")
    price_max = (run.get("after") or {}).get("price_max")
    if not isinstance(price_max, str) or not re.fullmatch(r"\d{8}", price_max):
        raise ValueError("snapshot price date is missing")
    day = datetime.strptime(price_max, "%Y%m%d").date()
    if day > times[3].date():
        raise ValueError("snapshot price date is in the future")
    finished = run.get("finished_at")
    if finished and not times[3] <= timestamp(finished) <= now:
        raise ValueError("invalid original completion time")
    return {"proof_version": PROOF_VERSION, "snapshot_commit": commit, "source_head": commit,
            "started_at": run["started_at"], "recorded_at": run["recorded_at"],
            "finished_at": finished, "completion_is_original": bool(finished),
            "price_max": price_max, "manifest_fp": fingerprint,
            "manifest_generated_at": manifest["generated_at"], "verification_at": verification["at"]}


def read_ready_proof(folder: Path, *, now=None):
    """읽기 전용으로 배포된 동일 세대의 근거만 인정한다. 과거 세대에는 이 표지가 없다."""
    now = now or datetime.now(timezone.utc)
    folder = folder.resolve()
    def read(name):
        return json.loads((folder / name).read_text(encoding="utf-8"))
    receipt = read("provenance.json")
    if receipt.get("proof_version") != PROOF_VERSION or receipt.get("files_verified") is not True:
        raise ValueError("verified snapshot receipt is missing")
    proof = validate_snapshot(receipt["snapshot_commit"], read("meta/run_record.json"),
                              read("meta/manifest.json"), read("meta/last_verify.json"), now=now)
    if any(receipt.get(key) != value for key, value in proof.items()):
        raise ValueError("snapshot receipt and metadata differ")
    if not timestamp(proof["recorded_at"]) <= timestamp(receipt["data_ready_at"]) <= now:
        raise ValueError("invalid snapshot publication time")
    local = read("state/daily_update_last.json")
    original = read("meta/run_record.json")["run"]
    if local != original:
        raise ValueError("local run record differs from the verified snapshot")
    return receipt
