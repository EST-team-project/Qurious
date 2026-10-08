"""적재 · 백업 화면 — 수집 자료의 Hugging Face 백업 상태(데이터 수집 화면 설계 3 · 2026-10-08).

판정은 한 곳에서 (2026-10-08 결정 ③ · SSoT)
--------------------------------------------
「로컬 원본을 지워도 되나」 의 조건 여섯(표 빠짐 · 행 수 · 파일 · 깊은 대조 · 복원 리허설 · 원격)은 `scripts/hf_dataset.py` 의
`_deletion_verdict` 한 곳에 있다. 그 도구가 판정 결과를 상태 폴더의 `hf_backup_status.json` 에 쓰고(검증 · 올리기 · 복원 리허설 ·
`status --write` 가 끝날 때마다), 앱은 그 파일을 읽어 화면의 점검 줄 넷으로 **묶기만** 한다 — 앱 컨테이너에는 `scripts/` 가 없고,
규칙을 여기 베끼면 한쪽만 고쳐지는 날이 온다(단계 이름표 사본을 없앤 결정 ④ 와 같은 까닭).

확인하지 않은 것은 통과가 아니다 — 조건의 `ok` 가 null 이면 「아직」 이고, 하나라도 「아직 · 다시」 면 지우기를 막는다.

원격 다시 확인 · 복원 리허설은 화면이 돌리지 않는다(2026-10-08 결정 ①) — 앱은 수집 폴더를 읽기만 하므로 PC 에서 돌릴 명령을 준다.
"""
from __future__ import annotations

from datetime import datetime

from app.services import data_status

STATUS_FILE = "hf_backup_status.json"     # 상태 폴더(data/collector/state) — 러너의 다른 기록과 같은 자리
SCHEMA = 1

#: 화면의 단추 · 안내가 보이는 명령(PC 에서 돌린다)
COMMANDS = {
    "remote": "python scripts/hf_dataset.py status --remote --write",
    "restore": "python scripts/hf_dataset.py restore",
    "deep": "python scripts/hf_dataset.py verify --deep",
    "write": "python scripts/hf_dataset.py status --write",
}

#: 화면의 점검 줄 넷 ← 도구가 쓴 조건 여섯의 열쇠(순서 = 화면 순서)
GROUPS = [
    {"key": "upload", "label": "마지막 올림", "conds": ["remote"], "command": "remote"},
    {"key": "basic", "label": "기본 대조 — 표 · 행 수 · 파일", "conds": ["tables", "rows", "files"], "command": None},
    {"key": "deep", "label": "깊은 대조 — 값까지", "conds": ["deep_verify"], "command": "deep"},
    {"key": "restore", "label": "복원 리허설", "conds": ["restore"], "command": "restore"},
]
GROUP_STATE = {"pass": "통과", "pending": "아직", "fail": "다시"}


def _group(g: dict, conds: dict[str, dict]) -> dict:
    found = [conds[k] for k in g["conds"] if k in conds]
    oks = [c.get("ok") for c in found]
    missing = len(found) < len(g["conds"])          # 도구가 그 조건을 쓰지 않았다 = 확인하지 않았다
    if any(o is False for o in oks):
        state = "fail"
    elif missing or any(o is not True for o in oks):
        state = "pending"
    else:
        state = "pass"
    # 한 줄 설명 — 통과가 아닌 조건의 까닭을 먼저(사람이 할 일이 거기 있다)
    whys = [c.get("why") or "" for c in found if c.get("ok") is not True] or [c.get("why") or "" for c in found]
    return {"key": g["key"], "label": g["label"], "state": state, "state_label": GROUP_STATE[state],
            "why": " · ".join(w for w in whys if w)[:300],
            "command": COMMANDS.get(g["command"]) if g["command"] and state != "pass" else None}


def read(now: datetime | None = None) -> dict:
    """백업 상태 — 도구가 쓴 판정 + 다른 데이터셋의 이 PC 기록 + 이 PC 용량."""
    cdir = data_status.collector_dir()
    sdir = cdir / "state" if cdir else None
    now = now or data_status._now()  # noqa: SLF001 — 같은 시계(KST)
    out: dict = {"checked_at": now.isoformat(timespec="seconds"), "commands": COMMANDS,
                 "datasets": data_status.hf_state(cdir), "disk": data_status.pc_disk(sdir)}
    snap = data_status._read_json(sdir / STATUS_FILE) if sdir is not None else None  # noqa: SLF001
    if not snap or not isinstance(snap.get("conditions"), list):
        out.update(available=False,
                   message="아직 백업 판정 기록이 없습니다 — 다음 수집 회차가 끝나면 생깁니다",
                   command=COMMANDS["write"])
        return out
    conds = {c.get("key"): c for c in snap["conditions"] if isinstance(c, dict) and c.get("key")}
    groups = [_group(g, conds) for g in GROUPS]
    remaining = [c.get("label") for c in snap["conditions"] if isinstance(c, dict) and c.get("ok") is not True]
    out.update(
        available=True,
        schema=snap.get("schema"),
        written_at=snap.get("written_at"),
        written_by=snap.get("by"),
        repo_id=snap.get("repo_id"),
        manifest=snap.get("manifest") or {},
        uploaded=snap.get("uploaded"),
        db_present=snap.get("db_present"),
        remote_checked=bool(snap.get("remote_checked")),
        conditions=snap["conditions"],
        groups=groups,
        # 지워도 되나 — 도구의 판정을 그대로(조건이 하나라도 확인 안 됨 · 실패면 아니다)
        can_delete=bool(snap.get("can_delete")) and not remaining,
        remaining=remaining,
    )
    if snap.get("schema") != SCHEMA:
        out["schema_note"] = f"판정 기록의 판({snap.get('schema')})이 화면이 아는 판({SCHEMA})과 다르다 — 앱과 도구를 같은 판으로"
    return out
