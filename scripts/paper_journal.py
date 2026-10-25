"""모의투자 그림자 일지 — 명령 (설계 `docs/phase-3/02-design/system/모의투자-그림자일지-설계.md` 9절).

    python scripts/paper_journal.py status                                판 · 행 수 · 마지막 거래일 · 지문이 같은지(쓰지 않음)
    python scripts/paper_journal.py register --rule card_ma_cross_20_60   판 1 등록(이미 있으면 멈춤 · --rule 을 여러 번)
    python scripts/paper_journal.py daily                                 마지막 행 뒤 준비된 거래일을 차례로 · 내보내기까지
    python scripts/paper_journal.py daily --dry-run                       쓰지 않고 이번에 계산할 날 · 판 바뀜만
    python scripts/paper_journal.py note --version 1 --kind change_reason --text "…" [--author 이동원] [--date YYYY-MM-DD]
    python scripts/paper_journal.py export                                앱 DB → 내보내기 폴더만 다시
    python scripts/paper_journal.py upload [--yes]                        내보내기 폴더 → HF 비공개 원장(새 파일만 · 추가만 확인)
    python scripts/paper_journal.py pull                                  HF 비공개 원장 → 이 PC 앱 DB(없는 판 · 행 · 메모만 · 여러 PC)
    python scripts/paper_journal.py daily --pull                          원장을 먼저 받고 그 뒤를 계산(12:30 러너가 이렇게 부른다)

12:30 러너의 `journal` 단계가 `daily --quiet --pull` 을, `journal_upload` 단계가 `upload --yes --quiet` 를 부른다. 앱 DB 주소는
러너가 넘겨 준다 — 손으로 돌릴 때 `DATABASE_URL` 이 없으면 러너와 같은 방법(compose 에서 PC 쪽 포트)으로 만든다.

여러 PC(2026-10-25 · 설계 `여러PC-회차-설계.md` 6절) — 회차가 PC 를 옮겨 다니면 판 등록 · 행이 앞 PC 의 앱 DB 에만 있다. 그대로
`daily` 를 돌리면 판이 「아직 등록 안 함」 으로 건너뛰거나, 원장에 있는 날을 다시 계산해 올리기가 「추가만 위반」 으로 멈춘다.
그래서 계산 앞에 원장(정본)을 받는다 — 판 · 메모 번호는 원장 그대로 넣고(판 지문 · 메모가 그 번호를 가리킨다), 넣은 뒤 다시
내보낸 내용 지문이 원장과 **모두** 같아야 커밋한다. 같은 경로에 다른 내용이 있으면 아무것도 쓰지 않고 멈춘다(사람이 정한다).
판 지문에 든 함수(`app/services/paper_journal.py`)는 고치지 않았다 — 받기는 이 파일에만 있다.

종료코드 — 0 성공 · 1 실패(추가만 위반 · private 아님 포함) · 2 받는 값이 틀림 · 3 앱 DB 꺼짐 · 4 원장 받기 실패(닿지 못함 · 이
PC 와 겹침 — 그날 계산도 하지 않는다) · 10 판 바뀜(새 판을 등록했다 — 러너가 「경고」 로 센다)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

REPO_ID = "qurious-quant/qurious-paper-log"
EXPORT_DIR = config.DATA_DIR.parent / "paper_journal" / "export"
LAST_PATH = config.STATE_DIR / "paper_journal_last.json"
HF_LAST_PATH = config.STATE_DIR / "paper_journal_hf_last.json"
#: 지난 파일이 없거나 바뀌면 올리지 않는다 — 지문 목록과 데이터셋 카드만 올릴 때마다 바뀐다.
MUTABLE = ("manifest.json", "README.md")


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ── 앱 DB ───────────────────────────────────────────────────────────────

def _db_ready() -> Optional[str]:
    """앱 DB 주소를 채우고 닿는지 본다 — 되면 None, 아니면 까닭. 러너가 준 주소가 있으면 그대로 쓴다."""
    from scripts import daily_update as du

    if not os.environ.get("DATABASE_URL"):
        env, why = du.host_app_db_env()
        if not env:
            return f"앱 DB 주소를 만들지 못했다 — {why}"
        os.environ.update(env)
    why = du.app_db_unreachable({"DATABASE_URL": os.environ["DATABASE_URL"]})
    return None if why is None else f"앱 DB 에 닿지 않는다({why})"


async def _with_session(fn):
    from app.database.postgres import close_postgres, connect_postgres, get_session_factory

    await connect_postgres()
    try:
        async with get_session_factory()() as session:
            return await fn(session)
    finally:
        await close_postgres()


def _now() -> datetime:
    from app.services.paper_journal import KST

    return datetime.now(KST)


# ── 명령 ────────────────────────────────────────────────────────────────

def cmd_status(_a) -> int:
    from app.services import paper_journal as pj

    st = asyncio.run(_with_session(pj.status))
    for rule, info in st["rules"].items():
        if info.get("state") == "unregistered":
            print(f"― {rule} · 아직 등록 안 함")
            continue
        same = "✅ 같음" if info["fingerprint_same"] else "🟡 다름 — 다음 daily 가 새 판을 등록한다"
        print(f"― {rule} · 판 {info['version']}(시도 {info['attempt']}) · 봉인 {info['seal_start']} ~ · 행 {info['rows']} · "
              f"마지막 {info['last'] or '-'} · 평가 {info['equity'] or '-'} · 지문 {same}")
    print(f"― 메모 {st['notes']}건")
    last, hf = _read_json(LAST_PATH), _read_json(HF_LAST_PATH)
    if last:
        print(f"― 마지막 daily {last.get('at')} · 새 행 {last.get('rows')} · 판 바뀜 {len(last.get('changed') or [])}")
    if hf:
        print(f"― 마지막 올리기 {hf.get('at')} · {hf.get('repo_id')} · 커밋 {hf.get('commit')} · 새 파일 {hf.get('uploaded')}")
    return 0


def cmd_register(a) -> int:
    from app.services import paper_journal as pj

    async def go(session):
        out = []
        for rule in a.rule:
            v = await pj.register(session, rule, now=_now(), by="manual")
            out.append((rule, v.version_no, v.attempt_no, v.seal_start, v.post_hoc_from, v.post_hoc_to, v.fingerprint))
        await session.commit()
        return out

    try:
        rows = asyncio.run(_with_session(go))
    except ValueError as e:
        print(f"[멈춤] {e}")
        return 2
    for rule, ver, att, seal, f, t, fp in rows:
        print(f"✅ {rule} 판 {ver} 등록 · 시도 {att} · 봉인 시작 {seal} · 사후 봉인 시험 {f} ~ {t} · 지문 {fp[:12]}")
    print("   다음: python scripts/paper_journal.py daily — 사후 봉인 시험 구간을 한 번 계산한다")
    return 0


def _export() -> dict:
    from app.services import paper_journal as pj

    async def go(session):
        return await pj.load_all(session)

    versions, days, notes = asyncio.run(_with_session(go))
    man = pj.write_export(pj.export_rows(versions, days, notes), EXPORT_DIR)
    man["generated_at"] = _now().isoformat(timespec="seconds")
    _write_json(EXPORT_DIR / "manifest.json", man)
    return man


def cmd_daily(a) -> int:
    from app.services import paper_journal as pj

    if getattr(a, "pull", False):                     # 여러 PC — 원장을 먼저 맞춘다(못 맞추면 계산하지 않는다)
        rc = cmd_pull(a)
        if rc:
            print("[건너뜀] 원장을 맞추지 못해 오늘 계산을 하지 않는다 — 다음 회차가 이어서 계산한다(catch_up)")
            return rc
    until = date.fromisoformat(a.to) if a.to else None

    async def go(session):
        return await pj.run_daily(session, now=_now(), until=until, dry_run=a.dry_run)

    summary = asyncio.run(_with_session(go))
    for rule, info in summary["rules"].items():
        state = info.get("state")
        if state == "unregistered":
            print(f"― {rule} · 아직 등록 안 함(건너뜀)")
        elif state == "version_would_change":
            print(f"― {rule} · 🟡 지문이 다름 — 실제로 돌리면 판 {info['version']} → {info['version'] + 1}(바뀐 조각 {', '.join(info['parts'])})")
        else:
            days = info["days"]
            span = f"{days[0]} ~ {days[-1]} {len(days)}일" if days else "새 거래일 없음"
            print(f"― {rule} · 판 {info['version']} · {span} · 새 행 {info['written']} · 마지막 {info['last'] or '-'}")
    for c in summary["changed"]:
        print(f"🟡 판 바뀜 — {c['rule_id']} 판 {c['from_version']} → 새 판 · 바뀐 조각 {', '.join(c['parts'])}")
    if a.dry_run:
        return 0
    if not a.no_export:
        man = _export()
        summary["export"] = {"files": len(man["files"]), "counts": man["counts"]}
        if not a.quiet:
            print(f"― 내보내기 {EXPORT_DIR} · 파일 {len(man['files'])} · {man['counts']}")
    _write_json(LAST_PATH, summary)
    return pj.EXIT_VERSION_CHANGED if summary["changed"] else 0


def cmd_note(a) -> int:
    from app.services import paper_journal as pj

    async def go(session):
        n = await pj.add_note(session, kind=a.kind, text=a.text, author=a.author, version_id=a.version,
                              trade_date=date.fromisoformat(a.date) if a.date else None, now=_now())
        await session.commit()
        return n.id

    print(f"✅ 메모 {asyncio.run(_with_session(go))} — {a.kind}")
    return 0


def cmd_export(_a) -> int:
    man = _export()
    print(f"✅ 내보내기 {EXPORT_DIR} · 파일 {len(man['files'])} · {man['counts']}")
    return 0


# ── HF 올리기 (앱 DB 없이 — 내보내기 폴더만) ─────────────────────────────

def _token(required: bool = True) -> Optional[str]:
    """HF 토큰. 절대 출력하지 않는다."""
    if required:
        return config.require("HUGGINGFACE_ACCESS_TOKEN", "Hugging Face 접근 토큰 (write 권한)")
    return config.env("HUGGINGFACE_ACCESS_TOKEN") or None


def _sharing_on() -> bool:
    return os.environ.get("QURIOUS_RAW_SHARING", "").lower() in ("1", "true", "yes")


def _readme(man: dict) -> str:
    c = man.get("counts", {})
    return "\n".join([
        "---", "license: other", "language: [ko]", "pretty_name: Qurious 모의투자 그림자 일지", "viewer: false", "---", "",
        "# Qurious 모의투자 그림자 일지 (`qurious-paper-log`)", "",
        "🔴 **이 저장소는 private 이어야 한다.** 원자료(공공데이터포털 시세)에서 계산한 기록이라 팀 안에서만 쓴다.", "",
        "등록한 규칙 판이 거래일마다 「그날 종가로 판단 → 다음 거래일 시가에 가상 체결」 한 기록이다. 증권사 주문은 없다. "
        "설계: 저장소 `docs/phase-3/02-design/system/모의투자-그림자일지-설계.md`.", "",
        f"- 판 {c.get('version', 0)} · 행 {c.get('day', 0)} · 메모 {c.get('note', 0)} · 만든 시각 {man.get('generated_at')}", "",
        "## 파일", "",
        "- `versions/<규칙>-v<판>.json` — 판 등록(얼린 명세 · 판 지문 · 봉인 시작일 · 사후 봉인 시험 구간). 바뀌지 않는다.",
        "- `rows/<규칙>/v<판>/<거래일>.parquet` — 그날 한 행. 묶음 칸(fills · decisions · ranking · orders · skipped · positions · "
        "flags)은 JSON 글자다. 바뀌지 않는다.",
        "- `notes/<번호>.json` — 개봉 기록 · 판 바뀜 까닭 · 판정 범위 · 해석. 바뀌지 않는다.",
        "- `manifest.json` — 파일마다 바이트 · 파일 SHA-256 · 내용 SHA-256. 올릴 때마다 바뀐다(추가만 확인의 기준).", "",
        "## 읽는 법", "", "```python", "import pandas as pd",
        f"df = pd.read_parquet('hf://datasets/{REPO_ID}/rows/card_ma_cross_20_60/v1/')", "```", "",
        "## 알아 둘 것", "",
        "- `grade` — `post_hoc` 는 사후 봉인 시험(판 1 등록 전 기간 · 한 단계 약한 증거) · `forward` 는 등록 뒤 전진 기록.",
        "- `recomputed` — 예정(다음 거래일)보다 늦게 계산한 전진 행. 값은 같다(규칙이 그날까지의 자료만 쓴다).",
        "- 몇 주 기록으로는 성과를 판정하지 않는다(기술 통계 + MinTRL). 판정은 E2(운영 일관성 · 백테스트와의 괴리).",
        "- 배당 입금 · 분할 수량 조정 없음 · 슬리피지 10bp 가정 · 시장 충격 없음.", "",
    ]) + "\n"


def _assert_private(api, create: bool) -> bool:
    if create:
        api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 확인 못 한 것은 통과가 아니다. 올리지 않는다.")
        return False
    if info.private:
        print("  ✅ 원격이 private 임을 확인했다")
        return True
    print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{REPO_ID}/settings 에서 Private 로.")
    return False


def _remote_manifest(api) -> dict:
    """원격 지문 목록 — 없으면 빈 사전(첫 올리기). 원격이 정본이다(이 PC 의 기록 파일이 지워져도 추가만을 지킨다)."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import EntryNotFoundError, RepositoryNotFoundError

    try:
        p = hf_hub_download(REPO_ID, "manifest.json", repo_type="dataset", token=api.token)
    except (EntryNotFoundError, RepositoryNotFoundError):
        return {}
    return json.loads(Path(p).read_text(encoding="utf-8"))


def plan_upload(local: dict, remote: dict) -> tuple[list[str], list[str]]:
    """(올릴 새 파일, 추가만 위반) — 원격에 있던 파일이 로컬에 없거나 내용이 다르면 위반."""
    from app.services.paper_journal import immutability_problems

    problems = immutability_problems(remote, local)
    new = sorted(rel for rel in local.get("files", {}) if rel not in (remote.get("files") or {}))
    return new, problems


def cmd_upload(a) -> int:
    man_p = EXPORT_DIR / "manifest.json"
    if not man_p.exists():
        print("― 올릴 것이 없다 — 일지가 아직 내보내지 않았다(등록 전이면 정상 · 건너뜀)")
        return 0
    local = _read_json(man_p)
    parts = sorted(EXPORT_DIR.rglob("*.part"))
    print(f"― 올리기 {'(실행)' if a.yes else '(dry-run — 아무것도 올리지 않는다)'} · {REPO_ID} · 로컬 파일 {len(local.get('files', {}))}")
    print(f"  관문 1 공유 스위치 {'✅ 켜짐' if _sharing_on() else '🔴 꺼짐 — 실제 올리기는 막힌다'}")
    print(f"  관문 2 반쪽 파일 {'✅ 없음' if not parts else f'🔴 {len(parts)}개'}")
    if not a.yes:
        print("  실제로 올리려면 `--yes` (원격 지문 목록과 견주는 것도 그때)")
        return 0
    if not _sharing_on():
        print("  🔴 QURIOUS_RAW_SHARING 이 꺼져 있다 — PowerShell `$env:QURIOUS_RAW_SHARING=\"1\"` · bash `export QURIOUS_RAW_SHARING=1`")
        return 1
    if parts:
        print("  🔴 반쪽 파일이 있다 — 내보내기를 다시 돌린다(python scripts/paper_journal.py export)")
        return 1
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=_token())
    if not _assert_private(api, create=True):
        return 1
    remote = _remote_manifest(api)
    new, problems = plan_upload(local, remote)
    if problems:
        print(f"  🔴 추가만 위반 {len(problems)}건 — 원격에 있던 파일이 로컬에 없거나 내용이 다르다. 올리지 않는다:")
        for p in problems[:10]:
            print(f"     {p}")
        return 1
    if not new:
        print("  ― 새 파일 0 — 원격과 같다(올리지 않는다)")
        return 0
    (EXPORT_DIR / "README.md").write_text(_readme(local), encoding="utf-8")
    ops = [CommitOperationAdd(path_in_repo=rel, path_or_fileobj=str(EXPORT_DIR / rel)) for rel in new]
    ops += [CommitOperationAdd(path_in_repo=m, path_or_fileobj=str(EXPORT_DIR / m)) for m in MUTABLE]
    c = local.get("counts", {})
    msg = f"그림자 일지 {_now().strftime('%Y-%m-%d')}(KST) · 새 파일 {len(new)} · 판 {c.get('version')} · 행 {c.get('day')}"
    info = api.create_commit(repo_id=REPO_ID, repo_type="dataset", operations=ops, commit_message=msg)
    commit = str(getattr(info, "oid", "") or "")[:8]
    print(f"  ✅ 올렸다 — 새 파일 {len(new)} · 커밋 {commit}")
    _write_json(HF_LAST_PATH, {"at": _now().isoformat(timespec="seconds"), "repo_id": REPO_ID, "commit": commit,
                               "uploaded": len(new), "counts": c})
    return 0


# ── HF 받기 (원장 → 이 PC 앱 DB · 여러 PC · 2026-10-25) ───────────────────────

#: 마지막 받기 요약 — 러너의 따라가기가 「받은 것이 있었나」 를 읽는다(아무것도 없으면 조용히 끝낸다).
PULL_LAST_PATH = config.STATE_DIR / "paper_journal_pull_last.json"
#: 원장 받기 실패 — 닿지 못했거나 이 PC 앱 DB 와 겹친다(러너는 경고로 센다 · 다음 회차가 다시).
EXIT_PULL = 4


def _ledger_download(api) -> tuple[Optional[str], dict, Optional[Path]]:
    """원장을 머리(40자)로 고정해 전부 받는다(작다 · 1MB 남짓) — (머리, 지문 목록, 받은 폴더). 저장소가 없으면 (None, {}, None)."""
    import hashlib
    import tempfile

    from huggingface_hub.errors import RepositoryNotFoundError

    try:
        head = api.repo_info(REPO_ID, repo_type="dataset", timeout=30).sha
    except RepositoryNotFoundError:
        return None, {}, None
    root = Path(tempfile.mkdtemp(prefix="qurious-journal-pull-"))
    api.snapshot_download(REPO_ID, repo_type="dataset", revision=head, local_dir=str(root))
    man = _read_json(root / "manifest.json")
    for rel, meta in (man.get("files") or {}).items():
        p = root / rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != meta.get("sha256"):
            raise ValueError(f"원장 파일이 지문 목록과 다르다 — {rel}")
    return head, man, root


def _ledger_record(path: Path) -> dict:
    """원장 파일 하나 → 내보낼 때의 기록 — json 은 그대로 · parquet 은 한 행(묶음 칸은 JSON 글자를 푼다)."""
    from app.services import paper_journal as pj

    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    import pyarrow.parquet as pq

    row = pq.ParquetFile(path).read().to_pylist()[0]
    return {k: (json.loads(v) if k in pj.NESTED and isinstance(v, str) else v) for k, v in row.items()}


def _d(s):
    return date.fromisoformat(s) if s else None


def _t(s):
    return datetime.fromisoformat(s) if s else None


def _version_row(r: dict) -> dict:
    keep = ("id", "rule_id", "version_no", "attempt_no", "registered_by", "fingerprint", "fingerprint_parts", "watch_parts",
            "spec", "code_commit", "python", "supersedes_id", "change_parts")
    return {**{k: r.get(k) for k in keep}, "registered_at": _t(r.get("registered_at")),
            "seal_start": _d(r.get("seal_start")), "post_hoc_from": _d(r.get("post_hoc_from")),
            "post_hoc_to": _d(r.get("post_hoc_to"))}


def _note_row(r: dict) -> dict:
    return {"id": r.get("id"), "version_id": r.get("version_id"), "trade_date": _d(r.get("trade_date")),
            "kind": r.get("kind"), "author": r.get("author"), "written_at": _t(r.get("written_at")), "text": r.get("text")}


def _day_row(r: dict) -> dict:
    from app.services import paper_journal as pj

    out = {k: r.get(k) for k in pj.DAY_FIELDS}
    out.update(trade_date=_d(r.get("trade_date")), data_as_of=_d(r.get("data_as_of")),
               computed_at=_t(r.get("computed_at")))
    return out


async def _pull(session, remote: dict, root: Path) -> dict:
    """원장 → 이 PC 앱 DB — 없는 판 · 메모 · 행만 더한다(추가만). 같은 경로에 다른 내용이 있거나 번호가 겹치면 아무것도 쓰지 않는다.

    넣은 뒤 다시 내보낸 내용 지문이 원장의 모든 파일과 같아야 커밋한다(아니면 되돌린다) — 다음 올리기의 「추가만」 확인과 같은 잣대.
    """
    from sqlalchemy import text

    from app.models.paper_journal import PaperJournalDay, PaperJournalNote, PaperJournalVersion
    from app.services import paper_journal as pj

    async def stop(state: str, why: str, paths: list) -> dict:
        await session.rollback()
        return {"state": state, "why": why, "paths": paths[:10]}

    versions, days, notes = await pj.load_all(session)
    local = pj.export_rows(versions, days, notes)
    rfiles = remote.get("files") or {}
    clash = sorted(rel for rel, meta in rfiles.items()
                   if rel in local and pj.content_sha(local[rel]["record"]) != meta.get("content_sha256"))
    if clash:
        return await stop("conflict", "같은 경로에 다른 내용 — 이 PC 앱 DB 의 일지가 원장과 갈라졌다", clash)
    todo = sorted(rel for rel in rfiles if rel not in local)
    if not todo:
        return {"state": "same", "imported": 0}
    recs = {rel: _ledger_record(root / rel) for rel in todo}
    new_versions = sorted((r for rel, r in recs.items() if rel.startswith("versions/")), key=lambda r: r["id"])
    taken = [f"판 id {r['id']}" for r in new_versions if r["id"] in {v["id"] for v in versions}]
    if taken:
        return await stop("conflict", "원장의 판 번호를 이 PC 의 다른 판이 쓰고 있다", taken)
    for r in new_versions:                            # 판 먼저 — 메모 · 행이 판 번호를 가리킨다(번호는 원장 그대로)
        session.add(PaperJournalVersion(**_version_row(r)))
    await session.flush()
    vid = {(v["rule_id"], v["version_no"]): v["id"] for v in versions}
    vid.update({(r["rule_id"], r["version_no"]): r["id"] for r in new_versions})
    have_notes = {n["id"] for n in notes}
    for rel, r in sorted(recs.items()):
        if rel.startswith("notes/"):
            if r.get("id") in have_notes:
                return await stop("conflict", "원장의 메모 번호를 이 PC 의 다른 메모가 쓰고 있다", [rel])
            session.add(PaperJournalNote(**_note_row(r)))
        elif rel.startswith("rows/"):
            key = (r.get("rule_id"), r.get("version_no"))
            if key not in vid:
                return await stop("conflict", "행의 판이 이 PC 에도 원장에도 없다", [rel])
            session.add(PaperJournalDay(version_id=vid[key], **_day_row(r)))
    await session.flush()
    for t in ("paper_journal_versions", "paper_journal_notes", "paper_journal_days"):   # 원장 번호를 넣었으니 다음 자동 번호는 그 뒤로
        await session.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                                   f"(SELECT COALESCE(MAX(id), 0) + 1 FROM {t}), false)"))
    v2, d2, n2 = await pj.load_all(session)
    again = pj.export_rows(v2, d2, n2)
    bad = sorted(rel for rel, meta in rfiles.items()
                 if rel not in again or pj.content_sha(again[rel]["record"]) != meta.get("content_sha256"))
    if bad:
        return await stop("mismatch", "받아 넣은 뒤 다시 내보낸 내용 지문이 원장과 다르다 — 되돌렸다", bad)
    await session.commit()
    kinds = [rel.split("/", 1)[0] for rel in todo]
    return {"state": "imported", "imported": len(todo), "versions": kinds.count("versions"), "rows": kinds.count("rows"),
            "notes": kinds.count("notes")}


def cmd_pull(a) -> int:
    from huggingface_hub import HfApi

    from scripts import run_lease

    tok = _token(required=False)
    if not tok:
        print("[건너뜀] HUGGINGFACE_ACCESS_TOKEN 이 없다 — 원장을 받을 수 없다(.env)")
        _write_json(PULL_LAST_PATH, {"at": _now().isoformat(timespec="seconds"), "state": "no_token", "imported": 0})
        return EXIT_PULL
    run_lease.set_timeouts()
    try:
        head, remote, root = _ledger_download(HfApi(token=tok))
    except Exception as e:  # noqa: BLE001 — 닿지 못함 · 지문 다름: 받기 실패로 끝낸다(계산하지 않는다)
        print(f"[실패] 원장을 받지 못했다 — {type(e).__name__}: {str(e)[:120]}")
        _write_json(PULL_LAST_PATH, {"at": _now().isoformat(timespec="seconds"), "state": "error",
                                     "why": type(e).__name__, "imported": 0})
        return EXIT_PULL
    if not remote:
        print("― 원장이 아직 없다(받을 것 없음)")
        _write_json(PULL_LAST_PATH, {"at": _now().isoformat(timespec="seconds"), "state": "empty", "imported": 0})
        return 0
    import shutil

    try:
        out = asyncio.run(_with_session(lambda s: _pull(s, remote, root)))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    out.update(at=_now().isoformat(timespec="seconds"), head=(head or "")[:12])
    _write_json(PULL_LAST_PATH, out)
    if out["state"] in ("conflict", "mismatch"):
        print(f"[멈춤] {out['why']} — {', '.join(out['paths'])}")
        return EXIT_PULL
    if out["state"] == "imported":
        print(f"― 원장 받기 {(head or '')[:8]} · 판 {out['versions']} · 행 {out['rows']} · 메모 {out['notes']}")
    elif not getattr(a, "quiet", False):
        print(f"― 원장 받기 {(head or '')[:8]} · 새 파일 0 — 이 PC 앱 DB 와 같다")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/paper_journal.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("register")
    p.add_argument("--rule", action="append", required=True, help="card_ma_cross_20_60 · auto_default (여러 번)")
    p = sub.add_parser("daily")
    p.add_argument("--to", help="이날까지만(YYYY-MM-DD · 기본 오늘)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-export", action="store_true", help="내보내기 폴더를 다시 쓰지 않는다")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--pull", action="store_true", help="계산 앞에 HF 원장을 이 PC 앱 DB 로 받는다(여러 PC)")
    p = sub.add_parser("pull", help="HF 원장 → 이 PC 앱 DB(없는 판 · 행 · 메모만)")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("note")
    p.add_argument("--version", type=int, help="판 id(빈칸이면 판 없는 메모)")
    p.add_argument("--kind", required=True, choices=("change_reason", "judgment", "interpretation", "ops"))
    p.add_argument("--text", required=True)
    p.add_argument("--author", default="이동원")
    p.add_argument("--date", help="거래일(YYYY-MM-DD)")
    sub.add_parser("export")
    p = sub.add_parser("upload")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "upload":
        return cmd_upload(a)
    try:
        for d in (getattr(a, "to", None), getattr(a, "date", None)):
            if d:
                date.fromisoformat(d)
    except ValueError:
        print("[멈춤] 날짜는 YYYY-MM-DD")
        return 2
    why = _db_ready()
    if why:
        print(f"[건너뜀] {why} — 앱 DB(PostgreSQL)가 떠 있는지 본다")
        return 3
    try:
        return {"status": cmd_status, "register": cmd_register, "daily": cmd_daily, "note": cmd_note,
                "export": cmd_export, "pull": cmd_pull}[a.cmd](a)
    except FileNotFoundError as e:
        print(f"[실패] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
