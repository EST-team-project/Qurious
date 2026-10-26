"""여러 PC 회차 임대 — 하루 한 회차는 한 PC 만 (설계 `docs/phase-3/02-design/system/여러PC-회차-설계.md` 4절).

이 파일이 답하는 질문은 하나다
------------------------------
**"PC 가 여럿일 때 오늘 12:30 회차를 누가 도는가 · 돌던 PC 가 꺼지면 누가 이어받는가."**

12:30 수집 회차(`scripts/daily_update.py`)는 2026-10-24 까지 노트북 한 대에 묶여 있었다. 사용자가 집 · 학원 데스크톱을 오가므로
(2026-10-25 「노트북/데스크톱 상관없이 12:30 회차가 돌아야」) 모든 PC 에 같은 예약 작업을 걸고, 한 회차 자리는 **먼저 임대를 잡은
PC 하나만** 돈다. 못 잡은 PC 는 끝나길 기다렸다가 바뀐 자료만 받는다(`scripts/hf_sync.py` · 러너의 따라가기).

어디에 — 백업 저장소 `qurious-quant/krx-daily-market` 의 전용 가지 ``runner-lease`` 에 ``lease.json`` 하나. 사용자 결정
(10-25 「기존 백업 저장소 안 파일」)을 따르되 가지를 나눠 백업 이력(main)에 임대 커밋이 섞이지 않게 했다(조사
`docs/phase-3/01-analysis/research/배경조사/2026-10-25-여러PC-회차-임대/결과.md` 3절 ①).

어떻게 하나만 잡히나 — HF ``create_commit(parent_commit=H)`` 는 가지 머리가 H 가 아니면 **412** 로 거절한다(조사 Q1 · 공식 시험
``test_create_commit_conflict``). 두 PC 가 같은 H 를 읽고 함께 써도 하나만 머리를 옮긴다. 쓸 때마다 새 ``write`` 값을 넣어 내용이
늘 다르게 한다 — 내용이 머리와 같으면 라이브러리가 커밋을 보내지 않아 비교 자체가 빠진다(조사 Q1 함정 1). 응답을 잃으면(시간
초과 · 5xx) 머리를 다시 읽어 **내 ``write`` 가 있으면 이긴 것**으로 본다(함정 2). 읽기는 가지 머리 SHA(40자)를 먼저 얻고 그
SHA 로 고정해 받는다 — 가지 이름으로 받으면 망 오류 때 옛 캐시를 예외 없이 준다(조사 Q3).

만료 — 쥔 PC 가 단계 사이마다(15분에 한 번까지) ``renewed_at`` 을 다시 쓴다. 90분 넘게 소식이 없으면 다른 PC 가 세대(``gen``)를
하나 올려 이어받는다(사용자 결정 10-25 · 가장 긴 단계 한도 60분 + 갱신 간격 15분 = 75분 < 90분).

좀비 — 절전에서 깨어난 옛 쥔 PC 는 다음 갱신 · 닫기의 비교가 412 라 멈추고(``LeaseLost``), 백업 올리기 앞에서 ``still_mine``
으로 한 번 더 본다. 백업(main) 쪽은 ``hf_dataset.upload`` 가 main 머리를 앞 커밋으로 따로 비교한다(가지가 달라 이 임대의 412 가
main 쓰기를 막아 주지 않는다 — 조사 Q4).

HF 에 닿지 못하면 회차를 잡지 않는다(fail-closed · ``LeaseError``) — 다음 반복 실행(1시간마다)이 다시 잡는다.

    python scripts/run_lease.py status       # 지금 임대 · 최근 회차 자리(원격을 읽기만)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import sys
import uuid
import zoneinfo
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")

#: 백업 저장소 — `scripts/hf_dataset.py` 의 REPO_ID 와 같아야 한다(TC-LE-01 이 맞댄다 · 이 모듈은 그 큰 모듈을 읽지 않고 뜬다).
REPO_ID = "qurious-quant/krx-daily-market"
#: 임대 가지 — main 에서 한 번 낸다(처음 잡는 PC 가 ``create_branch(exist_ok=True)``).
BRANCH = "runner-lease"
PATH_IN_REPO = "lease.json"
SCHEMA = 1

#: 이만큼 소식이 없으면 다른 PC 가 이어받는다(분 · 사용자 결정 2026-10-25 「90분 무소식」).
EXPIRE_MIN = 90
#: 갱신 간격의 아래 끝(분) — 단계 사이에서 이만큼 지났을 때만 다시 쓴다(회차당 커밋 3 ~ 5).
RENEW_MIN = 15
#: 회차 자리 기록을 남기는 수 — 누가 · 언제 · 결과(따라가는 PC 가 회차 기록을 만드는 재료).
KEEP_SLOTS = 14
#: 임대 가지 이력 정리 주기(일) — 한 해 1천 ~ 2천 커밋이 쌓이면 Hub 화면이 느려진다(조사 Q2). 되돌릴 수 없지만 가지 하나만.
SQUASH_DAYS = 30
#: 회차 자리의 경계 — 12:30 회차보다 2분 앞(러너의 따라잡기 여유 ``CATCH_UP_SLACK_MIN``)부터 그날 자리다. 그 앞은 전날 자리의
#: 따라잡기다(TC-LE-02 가 러너 값과 맞댄다).
SLOT_FROM = datetime.time(12, 28)
#: 따라가는 PC 가 쥔 PC 를 기다릴 때 읽는 간격 · 오래 기다리는 끝(분) — 작업 스케줄러 한도 4시간 안에서.
POLL_MIN = 5
WAIT_MAX_MIN = 180
#: 읽기 한도(초) — 기본 HTTP 클라이언트는 한도가 없어 끝없이 걸릴 수 있다(조사 Q1 함정 3).
READ_TIMEOUT_S = 30

#: 이 PC 가 마지막으로 본 임대 — 망 없이 읽는 곳(status · 앱이 「오늘 회차는 어느 PC」 를 보일 때).
STATE_PATH = config.STATE_DIR / "run_lease.json"
#: 임대 가지의 안내 — 가지를 처음 낼 때 main 에서 따라온 데이터 파일을 지우고 이것만 둔다(``_clean_branch``).
BRANCH_README = """---
viewer: false
---
# runner-lease — 여러 PC 회차 임대 (데이터 아님)

이 가지에는 `lease.json` 하나만 있다. Qurious 12:30 수집 회차를 지금 어느 PC 가 도는지 · 최근 회차 자리를 누가 끝냈는지 적는
표시다(저장소 `scripts/run_lease.py` · 설계 `docs/phase-3/02-design/system/여러PC-회차-설계.md`).

**데이터는 main 가지에 있다.** 받을 때는 main(기본값)을 쓴다 — 이 가지를 받으면 데이터가 없다.
"""
#: 가지를 정리할 때 남기는 파일.
_KEEP_ON_BRANCH = frozenset({PATH_IN_REPO, "README.md", ".gitattributes"})


class LeaseError(Exception):
    """HF 에 닿지 못했거나 판정할 수 없다 — 회차를 잡지 않는다(fail-closed). ``later`` 면 잠시 막힘(429 · 겨룸 두 번)."""

    def __init__(self, why: str, *, later: bool = False):
        super().__init__(why)
        self.why = why
        self.later = later


class LeaseLost(Exception):
    """남이 이어받았다 — 공유 쓰기(백업 올리기 · 닫기)를 하지 않는다."""


class _Conflict(Exception):
    """412 — 앞 커밋이 바뀌었다(누가 먼저 썼다)."""


@dataclass
class Held:
    """쥔 임대 — ``head`` 는 내가 마지막으로 쓴 가지 머리(다음 쓰기의 앞 커밋) · ``doc`` 은 그 내용."""
    head: str
    doc: Dict


def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def _iso(t: datetime.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s: Optional[str]) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def this_pc() -> str:
    """PC 이름 — 임대 · 회차 기록에 「어느 PC」 로 남는다(사용자 이름 · 경로는 적지 않는다)."""
    return platform.node() or os.environ.get("COMPUTERNAME") or "unknown"


def slot_of(now: datetime.datetime) -> str:
    """회차 자리 날짜(YYYY-MM-DD) — 12:28 부터 그날 · 그 앞은 전날(전날 12:30 을 놓친 따라잡기)."""
    d = now.astimezone(KST)
    return (d.date() if d.time() >= SLOT_FROM else d.date() - datetime.timedelta(days=1)).isoformat()


def expired(doc: Dict, now: datetime.datetime, minutes: int = EXPIRE_MIN) -> bool:
    t = _parse(doc.get("renewed_at")) or _parse(doc.get("acquired_at"))
    return t is None or (now - t).total_seconds() > minutes * 60


def decide(doc: Optional[Dict], *, now: datetime.datetime, kind: str, slot: str, pc: str) -> Tuple[str, str]:
    """임대를 읽고 할 일 — ``take``(잡는다) · ``busy``(남이 도는 중) · ``done``(이 자리는 끝났다) 과 까닭 한 줄.

    정기 회차(``schedule``)만 「자리가 끝났나」 를 본다 — 화면의 전체 수집 · 한 단계 다시는 남이 도는 중일 때만 막는다.
    같은 PC 의 ``running`` 은 이 PC 잠금을 잡은 지금 이미 끝난 실행이 남긴 것이다(러너는 PC 잠금을 먼저 잡는다).
    """
    if not doc:
        return "take", "임대가 비었다"
    if doc.get("state") == "running":
        if doc.get("pc") == pc:
            return "take", "이 PC 의 앞 실행이 남긴 임대 — 그 실행은 끝났다(이 PC 잠금을 잡았다)"
        if expired(doc, now):
            return "take", f"{doc.get('pc')} 의 임대가 {EXPIRE_MIN}분 넘게 소식이 없다 — 이어받는다"
        return "busy", f"{doc.get('pc')} 가 {doc.get('slot')} 자리를 돌고 있다({doc.get('kind')} · {doc.get('renewed_at')} 갱신)"
    if kind == "schedule":
        rec = (doc.get("slots") or {}).get(slot)
        if rec:
            return "done", f"{slot} 자리는 {rec.get('pc')} 가 {'끝냈다' if rec.get('ok') else '돌았다(실패 단계 있음)'}"
    return "take", "지금 도는 PC 가 없다"


def set_timeouts(read_s: float = 120.0, connect_s: float = 20.0) -> None:
    """이 프로세스의 HF 요청에 시간 한도를 준다 — 기본 클라이언트는 한도가 없어 커밋이 끝없이 걸릴 수 있다(조사 Q1 함정 3)."""
    import httpx2
    from huggingface_hub.utils import _http as hf_http

    def factory():
        c = hf_http.default_client_factory()
        c.timeout = httpx2.Timeout(read_s, connect=connect_s)
        return c

    hf_http.set_client_factory(factory)


def make_api():
    """쓰기 토큰으로 HfApi — 토큰은 찍지 않는다(없으면 ``LeaseError``)."""
    from huggingface_hub import HfApi

    tok = config.env("HUGGINGFACE_ACCESS_TOKEN")
    if not tok:
        raise LeaseError("HUGGINGFACE_ACCESS_TOKEN 이 없다 — 이 PC 는 회차를 잡을 수 없다(.env)")
    set_timeouts()
    return HfApi(token=tok)


def _status_of(e: BaseException) -> Optional[int]:
    return getattr(getattr(e, "response", None), "status_code", None)


def read(api) -> Tuple[Optional[str], Optional[Dict]]:
    """(가지 머리 40자, 임대 내용) — 가지가 없으면 (None, None) · 파일이 없으면 (머리, None). 머리 SHA 로 고정해 읽는다."""
    from huggingface_hub.errors import EntryNotFoundError, HfHubHTTPError, RevisionNotFoundError

    try:
        head = api.repo_info(REPO_ID, repo_type="dataset", revision=BRANCH, timeout=READ_TIMEOUT_S).sha
    except RevisionNotFoundError:
        return None, None
    except HfHubHTTPError as e:
        raise LeaseError(f"임대 가지를 읽지 못했다(HTTP {_status_of(e)})", later=_status_of(e) == 429) from e
    except Exception as e:  # noqa: BLE001 — 연결 끊김 · 시간 초과 · DNS
        raise LeaseError(f"HF 에 닿지 못했다 — {type(e).__name__}") from e
    if not head or len(str(head)) != 40:
        raise LeaseError("임대 가지 머리를 알 수 없다")
    try:
        p = api.hf_hub_download(REPO_ID, PATH_IN_REPO, repo_type="dataset", revision=head)
    except EntryNotFoundError:
        return head, None
    except Exception as e:  # noqa: BLE001
        raise LeaseError(f"임대 파일을 받지 못했다 — {type(e).__name__}") from e
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise LeaseError("임대 파일이 깨졌다") from e
    return head, doc if isinstance(doc, dict) else None


def _write(api, doc: Dict, parent: str, message: str) -> str:
    """임대 파일을 ``parent`` 위에 한 커밋으로 — 새 머리(40자). 412 → ``_Conflict`` · 429 → ``LeaseError(later)`` · 응답을 잃으면
    머리를 다시 읽어 판정한다. ``upload_folder`` 는 쓰지 않는다 — 스스로 다시 보내 이긴 커밋을 412 로 보이게 한다(조사 Q1 함정 2)."""
    from huggingface_hub import CommitOperationAdd
    from huggingface_hub.errors import HfHubHTTPError

    data = (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    try:
        info = api.create_commit(REPO_ID, [CommitOperationAdd(path_in_repo=PATH_IN_REPO, path_or_fileobj=data)],
                                 commit_message=message, repo_type="dataset", revision=BRANCH, parent_commit=parent)
    except HfHubHTTPError as e:
        code = _status_of(e)
        if code == 412:
            raise _Conflict() from e
        if code == 429:
            raise LeaseError("HF 가 잠시 막았다(429) — 나중에 다시", later=True) from e
        if code is not None and code < 500:
            raise LeaseError(f"HF 가 임대 쓰기를 거절했다(HTTP {code})") from e
        return _settle(api, doc, e)
    except Exception as e:  # noqa: BLE001 — 시간 초과 · 연결 끊김: 서버는 커밋했을 수 있다
        return _settle(api, doc, e)
    oid = str(getattr(info, "oid", "") or "")
    if len(oid) != 40 or oid == parent:
        # 내용이 머리와 같아 커밋을 건너뛴 경우(비교도 빠진다) — ``write`` 가 늘 새 값이라 생기면 안 된다
        raise LeaseError("임대 커밋이 생기지 않았다")
    return oid


def _settle(api, doc: Dict, err: BaseException) -> str:
    """응답을 잃은 쓰기 — 머리를 다시 읽어 내 ``write`` 가 있으면 그 머리, 없으면 ``LeaseError``."""
    try:
        head, cur = read(api)
    except LeaseError:
        raise LeaseError(f"임대 쓰기 결과를 모른다 — {type(err).__name__}") from err
    if head and cur and cur.get("write") == doc.get("write"):
        return head
    raise LeaseError(f"임대 쓰기가 들어가지 않았다 — {type(err).__name__}") from err


def _prune(slots: Dict) -> Dict:
    keep = sorted(slots)[-KEEP_SLOTS:]
    return {k: slots[k] for k in keep}


def _remember(doc: Optional[Dict], head: Optional[str], *, path: Optional[Path] = None) -> None:
    """마지막으로 본 임대를 이 PC 에 — 망 없이 status · 앱이 읽는다(못 써도 회차는 돈다)."""
    p = path or STATE_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"seen_at": _iso(now_kst()), "head": head, "lease": doc}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _clean_branch(api, head: str) -> Optional[str]:
    """새 임대 가지에서 main 에서 따라온 데이터 파일을 지우고 안내 README 만 둔다 — 새 머리(40자). 남이 먼저 정리했으면(412) None.

    가지는 main 에서 나므로 그때의 데이터 파일이 그대로 따라온다. 그대로 두면 HF 화면에서 이 가지를 고른 사람이 옛 데이터 사본으로
    오해한다(2026-10-25 · 시험 사고로 생긴 가지가 데이터 사본 109개 + 가짜 임대 기록이라 지웠다 — 사용자 「팀원들이 헷갈리면 지워야」).
    지우기는 이 가지의 파일 목록만 바꾼다 — main 과 저장된 파일 내용은 그대로다.
    """
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete
    from huggingface_hub.errors import HfHubHTTPError

    try:
        files = list(api.list_repo_files(REPO_ID, repo_type="dataset", revision=head))
    except Exception as e:  # noqa: BLE001
        raise LeaseError(f"임대 가지의 파일 목록을 읽지 못했다 — {type(e).__name__}") from e
    ops = [CommitOperationDelete(path_in_repo=f) for f in files if f not in _KEEP_ON_BRANCH]
    ops.append(CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=BRANCH_README.encode("utf-8")))
    try:
        info = api.create_commit(REPO_ID, ops, commit_message="임대 가지 — 데이터 파일 없이 안내만(데이터는 main)",
                                 repo_type="dataset", revision=BRANCH, parent_commit=head)
    except HfHubHTTPError as e:
        code = _status_of(e)
        if code == 412:
            return None                                       # 남이 먼저 정리했다 — 다시 읽는다
        if code is not None and code < 500:
            raise LeaseError(f"임대 가지를 정리하지 못했다(HTTP {code})", later=code == 429) from e
        return _settle_clean(api, e)
    except Exception as e:  # noqa: BLE001 — 시간 초과 · 끊김: 서버는 정리했을 수 있다
        return _settle_clean(api, e)
    oid = str(getattr(info, "oid", "") or "")
    if len(oid) != 40:
        raise LeaseError("임대 가지 정리 커밋이 생기지 않았다")
    return oid


def _settle_clean(api, err: BaseException) -> str:
    """응답을 잃은 정리 — 가지를 다시 읽어 안내 README 만 남았으면 그 머리, 아니면 LeaseError(다음 실행이 다시 정리한다)."""
    try:
        head = api.repo_info(REPO_ID, repo_type="dataset", revision=BRANCH, timeout=READ_TIMEOUT_S).sha
        files = set(api.list_repo_files(REPO_ID, repo_type="dataset", revision=head))
        readme = Path(api.hf_hub_download(REPO_ID, "README.md", repo_type="dataset", revision=head)).read_text(
            encoding="utf-8") if "README.md" in files else ""
    except Exception as e:  # noqa: BLE001
        raise LeaseError(f"임대 가지 정리 결과를 모른다 — {type(err).__name__}") from e
    if files <= _KEEP_ON_BRANCH and readme == BRANCH_README:
        return head
    raise LeaseError(f"임대 가지 정리가 들어가지 않았다 — {type(err).__name__}") from err


def _new_doc(cur: Optional[Dict], *, now: datetime.datetime, kind: str, slot: str, pc: str, pid: int, run: str) -> Dict:
    cur = cur or {}
    taken = None
    if cur.get("state") == "running":                        # 이어받기 — 누구의 무엇을(기록)
        taken = {k: cur.get(k) for k in ("pc", "gen", "slot", "kind", "renewed_at")}
    return {"schema": SCHEMA, "gen": int(cur.get("gen") or 0) + 1, "nonce": uuid.uuid4().hex, "write": uuid.uuid4().hex,
            "state": "running", "slot": slot, "kind": kind, "pc": pc, "pid": pid, "run": run,
            "acquired_at": _iso(now), "renewed_at": _iso(now), "finished_at": None, "result": None,
            "taken_from": taken, "slots": _prune(dict(cur.get("slots") or {})), "squashed_at": cur.get("squashed_at")}


def acquire(api, *, now: datetime.datetime, kind: str, run: str, pc: Optional[str] = None,
            pid: Optional[int] = None) -> Tuple[str, Optional[Held], Optional[Dict], str]:
    """임대를 잡아 본다 — (``acquired`` · ``busy`` · ``done``, 쥔 임대, 지금 내용, 까닭). 닿지 못하면 ``LeaseError``.

    겨루면(412) 다시 읽어 한 번 더 판정한다 — 대개 남의 ``running`` 이 보여 ``busy`` 로 끝난다.
    """
    pc = pc or this_pc()
    slot = slot_of(now)
    head, cur = read(api)
    if head is None:                                          # 가지가 아직 없다 — 처음 한 번(main 에서 낸다)
        try:
            api.create_branch(REPO_ID, repo_type="dataset", branch=BRANCH, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            raise LeaseError(f"임대 가지를 만들지 못했다 — {type(e).__name__}") from e
        head, cur = read(api)
        if head is None:
            raise LeaseError("임대 가지를 만든 뒤에도 보이지 않는다")
    if cur is None:                                           # 임대 파일이 아직 없다(새 가지 · 정리가 끊긴 가지) — 데이터 파일을 지우고 안내만
        cleaned = _clean_branch(api, head)                    # 남이 먼저 했으면(412) 다시 읽는다
        head, cur = (cleaned, cur) if cleaned else read(api)
    for _ in range(2):
        what, why = decide(cur, now=now, kind=kind, slot=slot, pc=pc)
        if what != "take":
            _remember(cur, head)
            return what, None, cur, why
        doc = _new_doc(cur, now=now, kind=kind, slot=slot, pc=pc, pid=pid or os.getpid(), run=run)
        try:
            new_head = _write(api, doc, head, f"임대 {slot} · {pc} · 세대 {doc['gen']}")
        except _Conflict:
            head, cur = read(api)                             # 남이 먼저 — 다시 읽어 한 번 더
            continue
        _remember(doc, new_head)
        return "acquired", Held(new_head, doc), doc, why
    raise LeaseError("임대를 두 번 겨뤄 모두 졌다 — 나중에 다시", later=True)


def _same_holder(cur: Optional[Dict], mine: Dict) -> bool:
    return bool(cur) and cur.get("gen") == mine.get("gen") and cur.get("nonce") == mine.get("nonce") \
        and cur.get("state") == "running"


def _lost_why(cur: Optional[Dict]) -> str:
    if not cur:
        return "임대 파일이 사라졌다"
    return f"{cur.get('pc')} 가 이어받았다(세대 {cur.get('gen')} · {cur.get('state')})"


def _write_mine(api, held: Held, doc: Dict, message: str) -> str:
    """내 임대를 다시 쓴다 — 412 면 다시 읽어 아직 내 것(세대 · nonce 같음)이면 새 머리 위에 한 번 더(가지 정리 등) · 아니면 LeaseLost."""
    parent = held.head
    for _ in range(2):
        try:
            return _write(api, doc, parent, message)
        except _Conflict:
            head, cur = read(api)
            if not head or not _same_holder(cur, held.doc):
                raise LeaseLost(_lost_why(cur))
            parent = head
    raise LeaseError("임대를 다시 쓰지 못했다(두 번 겨룸)", later=True)


def renew(api, held: Held, now: datetime.datetime, *, force: bool = False) -> Held:
    """「살아 있음」 — 앞 갱신에서 ``RENEW_MIN`` 이 지났을 때만 쓴다(``force`` 면 바로). 빼앗겼으면 ``LeaseLost``."""
    last = _parse(held.doc.get("renewed_at"))
    if not force and last and (now - last).total_seconds() < RENEW_MIN * 60:
        return held
    doc = dict(held.doc, renewed_at=_iso(now), write=uuid.uuid4().hex)
    head = _write_mine(api, held, doc, f"임대 갱신 {doc.get('slot')} · {doc.get('pc')}")
    _remember(doc, head)
    return Held(head, doc)


def still_mine(api, held: Held) -> Tuple[bool, str]:
    """백업 올리기 바로 앞 — 아직 내 임대인가(세대 · nonce · running). 아니면 그 까닭."""
    head, cur = read(api)
    ok = _same_holder(cur, held.doc)
    return ok, ("" if ok else _lost_why(cur))


def _due_squash(doc: Dict, now: datetime.datetime) -> bool:
    last = _parse(doc.get("squashed_at"))
    return last is None or (now - last).days >= SQUASH_DAYS


def release(api, held: Held, *, now: datetime.datetime, ok: bool, rc: int, summary: Dict,
            fill_slot: bool = True) -> Optional[Held]:
    """임대를 닫는다 — 정기 · 전체 수집이면 회차 자리 기록(누가 · 언제 · 결과 · 단계 줄)을 남긴다. 빼앗겼으면 쓰지 않고 None.

    ``fill_slot=False`` — 단계를 돌지 못한 회차(맞추기가 멈춤)는 자리를 채우지 않는다. 채우면 다른 PC 가 그날을 「끝남」 으로 보고
    따라가기만 해 그날 회차가 아무 데서도 돌지 않는다.

    한 달에 한 번 닫은 뒤 임대 가지의 이력을 하나로 줄인다(``super_squash_history`` · 그 가지만 · 실패해도 회차와 무관).
    """
    doc = dict(held.doc, state="done" if ok else "failed", finished_at=_iso(now), renewed_at=_iso(now),
               write=uuid.uuid4().hex, result={"ok": bool(ok), "rc": rc, "main": summary.get("main"),
                                               "stopped": summary.get("stopped")})
    if fill_slot and doc.get("kind") in ("schedule", "manual"):   # 한 단계 다시(only)는 자리를 채우지 않는다
        slots = dict(doc.get("slots") or {})
        slots[doc["slot"]] = {"pc": doc.get("pc"), "kind": doc.get("kind"), "ok": bool(ok), "rc": rc,
                              "finished_at": doc["finished_at"], **summary}
        doc["slots"] = _prune(slots)
    squash = _due_squash(doc, now)
    if squash:
        doc["squashed_at"] = _iso(now)
    try:
        head = _write_mine(api, held, doc, f"임대 닫기 {doc.get('slot')} · {doc.get('pc')} · {'성공' if ok else '실패 있음'}")
    except LeaseLost:
        return None
    if squash:
        try:
            api.super_squash_history(REPO_ID, repo_type="dataset", branch=BRANCH,
                                     commit_message=f"임대 가지 이력 정리 {doc['finished_at'][:10]}")
            head = read(api)[0] or head
        except Exception:  # noqa: BLE001 — 정리는 덤 · 다음 달에 다시
            pass
    _remember(doc, head)
    return Held(head, doc)


def wait_done(api, slot: str, *, now_fn: Callable[[], datetime.datetime], sleep_fn: Callable[[float], None],
              poll_min: float = POLL_MIN, max_min: float = WAIT_MAX_MIN,
              on_poll: Optional[Callable[[Dict], None]] = None) -> Tuple[str, Optional[Dict], Optional[str]]:
    """쥔 PC 가 그 자리를 끝낼 때까지 읽기만 — (``done`` · ``free`` · ``expired`` · ``timeout``, 내용, 머리).

    ``free`` = 도는 PC 가 없는데 그 자리 기록도 없다(한 단계 다시 · 전체 수집이 아닌 실행이 닫았다) → 부르는 쪽이 다시 잡는다.
    """
    t0 = now_fn()
    while True:
        head, cur = read(api)
        _remember(cur, head)
        if ((cur or {}).get("slots") or {}).get(slot):
            return "done", cur, head
        if not cur or cur.get("state") != "running":
            return "free", cur, head
        if expired(cur, now_fn()):
            return "expired", cur, head
        if (now_fn() - t0).total_seconds() >= max_min * 60:
            return "timeout", cur, head
        if on_poll:
            on_poll(cur)
        sleep_fn(poll_min * 60)


def seen(path: Optional[Path] = None) -> Dict:
    """이 PC 가 마지막으로 본 임대(망 없이) — 없으면 빈 사전."""
    try:
        return json.loads((path or STATE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status_lines(doc: Optional[Dict], head: Optional[str]) -> list:
    if not doc:
        return [f"― 임대 {REPO_ID}@{BRANCH} · 아직 없음" + (f"(가지 머리 {head[:8]})" if head else "(가지 없음)")]
    out = [f"― 임대 {REPO_ID}@{BRANCH} · 머리 {(head or '')[:8]}",
           f"  지금  {doc.get('state')} · {doc.get('pc')} · {doc.get('kind')} · 자리 {doc.get('slot')} · 세대 {doc.get('gen')}"
           f" · 잡음 {doc.get('acquired_at')} · 갱신 {doc.get('renewed_at')}"
           + (f" · 끝 {doc.get('finished_at')}" if doc.get("finished_at") else "")]
    if doc.get("taken_from"):
        t = doc["taken_from"]
        out.append(f"  이어받음 ← {t.get('pc')} 세대 {t.get('gen')}(마지막 갱신 {t.get('renewed_at')})")
    for slot, rec in sorted((doc.get("slots") or {}).items(), reverse=True)[:7]:
        out.append(f"  {slot}  {rec.get('pc')} · {'✅' if rec.get('ok') else '🔴/🟡'} · 종료코드 {rec.get('rc')}"
                   f" · {rec.get('started_at') or ''} → {rec.get('finished_at') or ''} · 시세 {rec.get('price_max') or '-'}")
    return out


def main(argv: Optional[list] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python scripts/run_lease.py", description="여러 PC 회차 임대(읽기만)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="지금 임대 · 최근 회차 자리 — 원격을 읽는다(쓰지 않음)")
    p.parse_args(argv)
    try:
        api = make_api()
        head, doc = read(api)
    except LeaseError as e:
        print(f"🟡 {e.why}")
        last = seen()
        if last:
            print(f"― 이 PC 가 마지막으로 본 임대({last.get('seen_at')})")
            print("\n".join(status_lines(last.get("lease"), last.get("head"))))
        return 1
    _remember(doc, head)
    print("\n".join(status_lines(doc, head)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
