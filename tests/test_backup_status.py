"""백업 상태 시험 (TC-BK) — 「적재 · 백업」 화면이 읽는 HF 백업 판정(데이터 수집 화면 설계 3 · 2026-10-08).

지키는 것
1. 판정 규칙은 `scripts/hf_dataset.py` 한 곳 — 앱은 도구가 쓴 `state/hf_backup_status.json` 을 읽어 점검 줄 넷으로 묶기만 한다(결정 ③)
2. 확인하지 않은 것은 통과가 아니다 — 조건의 ok 가 null 이거나 기록에 없으면 「아직」, false 면 「다시」, 하나라도 남으면 지우기를 막는다
3. 기록이 없으면 「아직 판정 기록이 없습니다」 와 기록을 만드는 명령 · 다른 데이터셋 · 이 PC 용량은 그대로
4. 원격 다시 확인 · 복원 리허설은 PC 에서 돌릴 명령으로(결정 ①) · 관리자만
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lib.session import get_current_user
from app.routes import data as data_routes
from app.services import backup_status as bs
from app.services import collector_db

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 8, 14, 0, tzinfo=KST)
LABELS = {"tables": "DB 의 모든 표가 백업 대상에 들어 있다", "rows": "파케이 행수 = 지금 DB 행수",
          "files": "내보낸 파일이 전부 디스크에 있다", "deep_verify": "verify --deep 이 통과했다 (지문·행수·스키마·값)",
          "restore": "복구 리허설이 성공했다 (파케이 → SQLite)", "remote": "원격(HF)에 올라가 있다"}


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    cdir = tmp_path / "collector"
    (cdir / "state").mkdir(parents=True)
    (cdir / "market.sqlite3").write_bytes(b"")          # collector_dir() 가 이 폴더를 고르게(진짜 기록 폴더를 읽지 않게)
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(cdir / "market.sqlite3"))
    (cdir / "state" / "pc_disk.json").write_text(json.dumps(
        {"measured_at": "2026-10-08T13:30:00+09:00", "drive": "C:", "free_bytes": 124.3e9, "total_bytes": 1001.8e9,
         "collector_db_bytes": 5.3e9}), encoding="utf-8")
    return cdir / "state"


def _write(state_dir, oks: dict, **extra):
    conds = [{"key": k, "ok": oks.get(k), "label": LABELS[k], "why": f"{k} 까닭"} for k in LABELS if k in oks]
    snap = {"schema": 1, "written_at": "2026-10-08T13:25:00+09:00", "by": "upload", "repo_id": "qurious-quant/krx-daily-market",
            "manifest": {"generated_at": "2026-10-08T13:10:00+09:00", "bytes": 1.0e9, "files": 69, "rows": 21524235,
                         "db_bytes": 5.0e9}, "uploaded": {"at": "2026-10-08T13:25:00+09:00", "files_same": 69, "files_total": 69},
            "db_present": True, "remote_checked": False, "conditions": conds,
            "can_delete": all(v is True for v in oks.values()) and len(oks) == 6}
    snap.update(extra)
    (state_dir / bs.STATUS_FILE).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")


def _groups(out):
    return {g["key"]: g["state"] for g in out["groups"]}


def test_no_record_yet(state_dir):
    """TC-BK-01 · 기록이 없으면 「아직 판정 기록이 없습니다」 + 기록을 만드는 명령 · 이 PC 용량은 그대로 보인다."""
    out = bs.read(NOW)
    assert out["available"] is False and "판정 기록이 없습니다" in out["message"]
    assert out["command"] == "python scripts/hf_dataset.py status --write"
    assert out["disk"]["free_gb"] == 124.3 and out["datasets"] == []


def test_unchecked_is_not_pass(state_dir):
    """TC-BK-02 · 깊은 대조 · 리허설 · 원격이 확인 안 됨(null) — 기본 대조만 통과 · 셋은 「아직」 · 지우기를 막고 남은 조건 셋 · 명령."""
    _write(state_dir, {"tables": True, "rows": True, "files": True, "deep_verify": None, "restore": None, "remote": None})
    out = bs.read(NOW)
    assert _groups(out) == {"upload": "pending", "basic": "pass", "deep": "pending", "restore": "pending"}
    assert out["can_delete"] is False and len(out["remaining"]) == 3
    by = {g["key"]: g for g in out["groups"]}
    assert by["restore"]["command"] == "python scripts/hf_dataset.py restore"
    assert by["upload"]["command"] == "python scripts/hf_dataset.py status --remote --write"
    assert by["basic"]["command"] is None and by["deep"]["state_label"] == "아직"


def test_all_pass_allows_delete(state_dir):
    """TC-BK-03 · 여섯이 모두 참이면 넷 다 통과 · 지워도 된다 · 명령 없음."""
    _write(state_dir, {k: True for k in LABELS})
    out = bs.read(NOW)
    assert set(_groups(out).values()) == {"pass"} and out["can_delete"] is True and out["remaining"] == []
    assert all(g["command"] is None for g in out["groups"])


def test_false_is_redo_and_tool_flag_is_not_trusted_alone(state_dir):
    """TC-BK-04 · 행 수가 어긋나면 기본 대조 「다시」 · 도구가 can_delete 를 참으로 써도 남은 조건이 있으면 아니다."""
    _write(state_dir, {"tables": True, "rows": False, "files": True, "deep_verify": True, "restore": True, "remote": True})
    out = bs.read(NOW)
    assert _groups(out)["basic"] == "fail" and out["groups"][1]["state_label"] == "다시" and out["can_delete"] is False
    _write(state_dir, {"tables": True, "rows": True, "files": True, "deep_verify": True, "restore": None, "remote": True},
           can_delete=True)
    assert bs.read(NOW)["can_delete"] is False


def test_missing_condition_is_pending_and_schema_note(state_dir):
    """TC-BK-05 · 도구가 조건을 빠뜨리면(쓰지 않은 조건) 그 줄은 「아직」 · 판이 다르면 알린다."""
    _write(state_dir, {"tables": True, "rows": True, "files": True, "deep_verify": True, "restore": True}, schema=2)
    out = bs.read(NOW)
    assert _groups(out)["upload"] == "pending" and out["can_delete"] is False
    assert "판" in out["schema_note"]


def test_route_admin_only(state_dir):
    """TC-BK-06 · 라우트 — 관리자만(일반 사용자 403)."""
    _write(state_dir, {k: True for k in LABELS})
    app = FastAPI()
    app.include_router(data_routes.router)
    c = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "roles": ["user"]}
    assert c.get("/api/data/backup").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: {"id": "a1", "roles": ["admin"]}
    j = c.get("/api/data/backup").json()
    assert j["available"] is True and j["repo_id"] == "qurious-quant/krx-daily-market" and len(j["groups"]) == 4


def test_tool_writes_what_the_app_reads(tmp_path, monkeypatch):
    """TC-BK-07 · 정본 한 곳 — `scripts/hf_dataset.py` 가 쓴 판정 기록을 앱이 그대로 읽는다: 조건 열쇠 여섯의 차례가 같고,
    앱의 점검 줄 넷이 그 여섯을 다 덮고, 판을 같이 쓴다 · 내보내기만 한 백업은 깊은 대조 · 리허설이 「아직」 · 지우기를 막는다."""
    from scripts import hf_dataset
    from tests.test_hf_dataset_tables import OHLCV_TABLES, _fill

    cdir = tmp_path / "collector"
    (cdir / "state").mkdir(parents=True)
    src = cdir / "market.sqlite3"
    _fill(src)
    out = tmp_path / "hf_export"                       # 앱은 수집 폴더 옆 hf_export 의 매니페스트도 읽는다(다른 데이터셋 줄)
    for name, path in (("EXPORT_DIR", out), ("MANIFEST_PATH", out / "meta" / "manifest.json"), ("README_PATH", out / "README.md"),
                       ("VERIFY_LOG_PATH", out / "meta" / "last_verify.json"), ("RESTORE_LOG_PATH", out / "meta" / "last_restore.json"),
                       ("STATUS_SNAPSHOT_PATH", cdir / "state" / bs.STATUS_FILE)):
        monkeypatch.setattr(hf_dataset, name, path)
    monkeypatch.setattr(hf_dataset.config, "DB_PATH", src)
    monkeypatch.setenv(collector_db.ENV_DB_PATH, str(src))
    hf_dataset.export(tables=list(OHLCV_TABLES), verbose=False)
    assert hf_dataset.write_status_snapshot(by="status") == cdir / "state" / bs.STATUS_FILE

    got = bs.read(NOW)
    assert got["available"] is True and got["schema"] == hf_dataset.STATUS_SCHEMA == bs.SCHEMA
    assert [c["key"] for c in got["conditions"]] == list(hf_dataset.VERDICT_KEYS)
    assert {k for g in bs.GROUPS for k in g["conds"]} == set(hf_dataset.VERDICT_KEYS), "앱의 점검 줄이 도구의 조건을 다 덮는다"
    assert got["can_delete"] is False and _groups(got)["deep"] == _groups(got)["restore"] == "pending"
    assert got["manifest"]["rows"] == 9 and got["uploaded"] is None and got["written_by"] == "status"
    assert got["datasets"][0]["repo"] == hf_dataset.REPO_ID
