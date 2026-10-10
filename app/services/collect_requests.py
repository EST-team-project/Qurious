"""화면 수집 요청 — 요청 표의 상태 바꾸기 · 보이기를 한 곳에 (목표 기능 ① 수집 단추 · 2026-10-10).

앱 API(`app/routes/data.py`)와 PC 작업자(`scripts/collect_worker.py`)가 **같은 함수**로 줄을 바꾼다. 상태를 바꾸는 코드가
두 곳에 흩어지면 한쪽만 고쳐 어긋난다(정본 한 곳). 앱 설정(`app.config`)을 읽지 않으므로 PC 쪽 작업자도 그대로 불러 쓴다 —
DB 연결은 부르는 쪽이 넘긴다(앱은 요청마다의 세션 · 작업자는 compose 포트 짝으로 만든 127.0.0.1 주소).

상태::

    queued(대기) ── claim ──▶ running(도는 중) ── finish ──▶ done(끝) · warning(경고) · failed(실패)
       │   ◀── requeue(막힘 — 러너가 지금은 돌 수 없다 · 다시 기다림) ──┘
       ├── cancel ─▶ cancelled(취소 — 관리자 · 대기일 때만)
       ├── reject ─▶ rejected(거절 — 작업자가 받지 않는 요청: 목록에서 사라진 단계 · 올리기를 받지 않는 작업자)
       └── expire ─▶ expired(만료 — 3시간 안에 시작하지 못함)

지키는 원칙
- 멱등 — 같은 대상(종류 + 단계)의 활성 줄은 하나다. 정본은 DB 의 부분 고유 색인이고, 만들기는 `INSERT … ON CONFLICT DO
  NOTHING` 뒤 있던 줄을 돌려준다(두 관리자가 동시에 눌러도 한 줄).
- 원자성 — 요청 줄과 감사 줄은 한 트랜잭션이다. 실패를 삼키는 `app.services.audit.audit()` 는 이 길에서 쓰지 않는다
  (요청은 남고 감사만 빠지는 일이 없게). 상태 바꾸기는 모두 「지금 상태가 X 일 때만」 조건 UPDATE 라 가져가기 경쟁은 DB 가 가른다.
- 말없는 대체 금지 — 작업자가 꺼져 있어도 요청은 받되 「대기 — PC 작업자 꺼짐」 으로 보인다. 결과를 모르는 줄을 「끝」 으로
  적지 않는다(작업자가 러너 기록에서 요청 번호로 결과를 찾지 못하면 「실패 — 결과 기록 없음」).
- 받는 값은 고르기 목록뿐 — 종류(step · all)와 러너가 쓴 단계 목록의 이름. 명령 글자는 받지 않는다(OWASP 명령 주입 —
  허용 목록 · Rundeck 2025 옵션 탈출 결함과 같은 꼴을 피한다). 작업자도 러너의 단계 목록으로 한 번 더 확인한다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collect import CollectRequest, CollectWorker
from app.models.misc import AuditEvent
from app.models.user import User

KST = timezone(timedelta(hours=9))

KIND_STEP, KIND_ALL = "step", "all"
KINDS = (KIND_STEP, KIND_ALL)
KIND_LABEL = {KIND_STEP: "단계 하나", KIND_ALL: "전체 수집"}

QUEUED, RUNNING, DONE, WARNING, FAILED, REJECTED, CANCELLED, EXPIRED = (
    "queued", "running", "done", "warning", "failed", "rejected", "cancelled", "expired")
ACTIVE = (QUEUED, RUNNING)
#: 러너가 돈 뒤의 끝 — 러너 화면과 같은 말(성공 · 멈추지 않는 단계의 실패는 경고 · 멈추는 단계의 실패는 실패)
FINISHED = (DONE, WARNING, FAILED)
STATUS_LABEL = {QUEUED: "대기", RUNNING: "도는 중", DONE: "끝", WARNING: "경고", FAILED: "실패",
                REJECTED: "거절", CANCELLED: "취소", EXPIRED: "만료"}

IDLE, WAITING, BUSY = "idle", "waiting", "running"
WORKER_STATES = (IDLE, WAITING, BUSY)
WORKER_LABEL = {IDLE: "쉬는 중", WAITING: "기다리는 중", BUSY: "도는 중", "off": "꺼짐", "missing": "없음"}   # 화면은 앞에 「PC 작업자 」 를 붙인다(TC-CL-09)

#: 이보다 오래 시작하지 못한 대기 요청은 만료 — 작업자가 꺼져 있던 요청이 몇 시간 뒤 엉뚱한 때(다음 날 · 12:30 무렵) 돌지 않게
#: (Prefect 의 Late 와 같은 생각). 3시간 = 막는 때가 가장 긴 전체 수집(11:00 ~ 13:30 · 150분)을 기다려도 남는 길이.
EXPIRE_AFTER = timedelta(hours=3)
#: 작업자는 작업 스케줄러가 매 분 띄운다(사용자 결정 2026-10-10) — 신호가 3분 넘게 없으면 「꺼짐」.
#: 1분 간격 · 파이썬이 뜨는 몇 초 · 작업 스케줄러가 한 번 건너뛸 여유를 둔 값이다.
WORKER_STALE_AFTER = timedelta(minutes=3)

#: 상태를 바꾸는 요청(만들기 · 취소)에 화면이 붙이는 머리글 — SameSite 쿠키 위에 한 겹 더(OWASP CSRF · Jenkins crumb).
#: 다른 사이트의 폼 · 단순 요청은 사용자 정의 머리글을 붙일 수 없고, fetch 로 붙이면 사전 요청에서 막힌다(CORS 를 열지 않는다).
ACTION_HEADER = "X-Qurious-Action"
ACTION_VALUE = "collect"

INSTALL_HINT = "python scripts/collect_worker.py install"
EXPIRED_NOTE = "3시간 안에 시작하지 못해 만료됐습니다 — 작업자가 꺼져 있었거나 막는 때가 길었습니다"
CANCELLED_NOTE = "관리자가 취소"


class RequestError(Exception):
    """API 가 그대로 HTTP 상태로 돌려줄 오류 — 422 받는 값 · 404 없음 · 409 지금 상태로는 안 됨."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(KST).isoformat(timespec="seconds") if t else None


def _uid(raw) -> uuid.UUID | None:
    """세션의 사용자 ID · 요청 ID 를 UUID 로 — 아니면 None(감사 도우미 `_resolve_user_id` 와 같은 규칙)."""
    if raw is None or isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


# ── 받는 값 · 단계 목록 ───────────────────────────────────────────────────
def current_catalog() -> dict:
    """러너가 쓴 단계 목록(이름표 · 막는 때) — 앱은 사본을 두지 않고 이 기록만 읽는다(`data_status.load_catalog`)."""
    from app.services import data_status   # 늦게 부른다 — PC 작업자가 이 모듈을 부를 때 수집 DB 도구까지 끌고 오지 않게

    cdir = data_status.collector_dir()
    return data_status.load_catalog(cdir / "state" if cdir else None)


def validate(kind: str, step: str | None, catalog: dict) -> tuple[str, str]:
    """받는 값 확인 — (종류, 단계 이름). 단계 이름은 러너가 쓴 단계 목록에 있는 것만(허용 목록). 아니면 422."""
    if kind not in KINDS:
        raise RequestError(422, "종류는 step(단계 하나) · all(전체 수집) 가운데 하나입니다")
    step = (step or "").strip()
    if kind == KIND_ALL:
        if step:
            raise RequestError(422, "전체 수집에는 단계 이름을 주지 않습니다")
        return kind, ""
    if not step:
        raise RequestError(422, "단계 하나를 다시 돌리려면 단계 이름이 있어야 합니다")
    names = (catalog or {}).get("by_name") or {}
    if not names:
        raise RequestError(422, "단계 목록이 없습니다 — 이 PC 에서 러너를 한 번 돌리거나 "
                                "`python scripts/daily_update.py steps --write` 로 단계 목록을 쓰세요")
    if step not in names:
        raise RequestError(422, f"모르는 단계입니다 — 러너 단계 목록에 있는 이름만 받습니다({len(names)}개)")
    return kind, step


def _window_now(window, now_kst: datetime) -> dict | None:
    """창 하나(러너가 쓴 「HH:MM」 두 칸)에 지금이 드는가 — {blocked, until}. 러너의 `rerun_blocked` · `full_run_blocked` 와
    같은 비교(그날 날짜 · 양끝 포함)라 화면의 단추와 러너의 막힘 판정이 어긋나지 않는다(TC-CQ-17). 창이 없거나 글이 틀리면 「모름」(None)."""
    if not isinstance(window, dict):
        return None
    try:
        lo, hi = ([int(x) for x in str(window[k]).split(":")] for k in ("from", "to"))
        lo_t = now_kst.replace(hour=lo[0], minute=lo[1], second=0, microsecond=0)
        hi_t = now_kst.replace(hour=hi[0], minute=hi[1], second=0, microsecond=0)
    except (KeyError, ValueError, IndexError):
        return None
    blocked = lo_t <= now_kst <= hi_t
    return {"blocked": blocked, "until": window["to"] if blocked else None}


def rules(catalog: dict, now: datetime | None = None) -> dict:
    """막는 때 · 만료 · 꺼짐 기준 — 막는 때는 러너가 막는 데 쓰는 함수로 셈해 단계 목록에 쓴 값 그대로(앱은 창을 다시 셈하지 않는다).

    `blocked_now` 는 그 창에 **서버 시각**이 드는가다(화면 단추를 끄는 데 쓴다 · 2026-10-10 결정 「막는 때에는 단추를 끈다」).
    화면 PC 의 시계로 견주면 시계가 틀린 PC 에서 단추와 러너 판정이 어긋나므로 여기서 정한다. 창이 없으면 None(모름).
    """
    g = (catalog or {}).get("guards") or {}
    out = {"schedule": g.get("schedule"), "full": dict(g["full"]) if isinstance(g.get("full"), dict) else None,
           "steps": {k: dict(v) for k, v in (g.get("steps") or {}).items() if isinstance(v, dict)},
           "expire_hours": int(EXPIRE_AFTER.total_seconds() // 3600),
           "worker_stale_s": int(WORKER_STALE_AFTER.total_seconds()), "blocked_now": None}
    if not g:
        out["note"] = "단계 목록에 막는 때가 없습니다 — 러너가 다음 회차(또는 steps --write)에 적습니다"
        return out
    now_kst = _now(now).astimezone(KST)
    out["blocked_now"] = {"full": _window_now(out["full"], now_kst),
                          "steps": {k: _window_now(v, now_kst) for k, v in out["steps"].items()}}
    return out


# ── 보이기 ────────────────────────────────────────────────────────────────
def worker_view(row: CollectWorker | None, *, now: datetime | None = None) -> dict:
    """작업자 상태 — 신호가 3분 안이면 그 상태 그대로, 넘으면 「꺼짐」(마지막 신호 시각) · 줄이 없으면 「없음」."""
    now = _now(now)
    base = {"stale_after_s": int(WORKER_STALE_AFTER.total_seconds())}
    if row is None:
        return {**base, "name": None, "alive": False, "status": "missing", "status_label": WORKER_LABEL["missing"],
                "last_state": None, "note": f"이 PC 에 작업자가 등록되지 않았습니다 — {INSTALL_HINT}",
                "seen_at": None, "seen_ago_s": None, "pid": None, "allow_upload": None, "request_id": None}
    ago = (now - row.seen_at).total_seconds()
    alive = ago <= WORKER_STALE_AFTER.total_seconds()
    status = row.state if alive else "off"
    note = row.note or ""
    if not alive:
        note = (f"마지막 신호 {row.seen_at.astimezone(KST):%H:%M} — 작업자가 돌지 않습니다"
                f"(작업 스케줄러 등록 · 로그온 확인 · {INSTALL_HINT})")
    return {**base, "name": row.name, "alive": alive, "status": status,
            "status_label": WORKER_LABEL.get(status, status), "last_state": row.state, "note": note,
            "seen_at": _iso(row.seen_at), "seen_ago_s": int(ago), "pid": row.pid,
            "allow_upload": bool(row.allow_upload), "request_id": str(row.request_id) if row.request_id else None}


def wait_reason(request_id, worker: dict) -> str:
    """대기 줄의 까닭 한 줄 — 작업자 꺼짐 · 앞 요청이 도는 중 · 작업자가 기다리는 까닭 · 곧 시작."""
    st = worker.get("status")
    if st == "missing":
        return "PC 작업자 꺼짐 — 이 PC 에 작업자가 없습니다(등록하면 돕니다)"
    if st == "off":
        return f"PC 작업자 꺼짐 — {worker.get('note') or '신호 없음'}"
    if st == BUSY:
        if worker.get("request_id") and worker["request_id"] == str(request_id):
            return "도는 중"
        return "앞 요청이 도는 중 — 끝나면 돕니다"
    if st == WAITING:
        return worker.get("note") or "기다리는 중"
    return "곧 시작합니다(작업자가 1분 안에 가져갑니다)"


def request_view(row: CollectRequest, *, catalog: dict, worker: dict | None, now: datetime,
                 requester: str | None = None) -> dict:
    by = (catalog or {}).get("by_name") or {}
    st = row.status
    out = {"id": str(row.id), "kind": row.kind, "kind_label": KIND_LABEL.get(row.kind, row.kind),
           "step": row.step or None, "step_label": ((by.get(row.step) or {}).get("label") or row.step) or None,
           "status": st, "status_label": STATUS_LABEL.get(st, st),
           "requested_at": _iso(row.requested_at),
           "requested_by": str(row.requested_by) if row.requested_by else None, "requested_by_name": requester,
           "started_at": _iso(row.started_at), "finished_at": _iso(row.finished_at),
           "minutes": (round((row.finished_at - row.started_at).total_seconds() / 60, 1)
                       if row.started_at and row.finished_at else None),
           "worker": row.worker or None, "exit_code": row.exit_code, "result": row.result or "",
           "log": row.log_path or None, "wait": None, "expires_at": None}
    if st == QUEUED:
        exp = row.requested_at + EXPIRE_AFTER
        out["expires_at"] = _iso(exp)
        if now >= exp:
            # 아직 아무도 줄을 고치지 않았지만 이미 만료 — 보이기는 만료로(작업자 · 다음 만들기가 줄을 고친다)
            out.update(status=EXPIRED, status_label=STATUS_LABEL[EXPIRED], result=EXPIRED_NOTE)
        elif worker is not None:
            out["wait"] = wait_reason(row.id, worker)
    return out


async def _latest_worker(db: AsyncSession) -> CollectWorker | None:
    return (await db.execute(select(CollectWorker).order_by(CollectWorker.seen_at.desc()).limit(1))).scalar_one_or_none()


async def _view(db: AsyncSession, rid: uuid.UUID, *, catalog: dict, now: datetime) -> dict:
    row, name = (await db.execute(
        select(CollectRequest, User.name).outerjoin(User, User.id == CollectRequest.requested_by)
        .where(CollectRequest.id == rid))).one()
    return request_view(row, catalog=catalog, worker=worker_view(await _latest_worker(db), now=now), now=now,
                        requester=name)


async def _expire(db: AsyncSession, now: datetime) -> int:
    res = await db.execute(update(CollectRequest)
                           .where(CollectRequest.status == QUEUED, CollectRequest.requested_at < now - EXPIRE_AFTER)
                           .values(status=EXPIRED, finished_at=now, result=EXPIRED_NOTE))
    return int(res.rowcount or 0)


# ── 앱 API 쪽 ─────────────────────────────────────────────────────────────
async def create(db: AsyncSession, *, kind: str, step: str | None, user: dict, catalog: dict,
                 now: datetime | None = None) -> tuple[dict, bool]:
    """요청 만들기 — (요청, 새로 만들었나). 같은 대상의 활성 줄이 있으면 그 줄을 돌려준다(멱등 · 감사 줄 없음)."""
    now = _now(now)
    kind, step = validate(kind, step, catalog)
    await _expire(db, now)                                   # 만료된 대기 줄이 활성 자리를 막지 않게(같은 트랜잭션)
    uid = _uid(user.get("id"))
    ins = (pg_insert(CollectRequest)
           .values(kind=kind, step=step, status=QUEUED, requested_by=uid, requested_at=now)
           .on_conflict_do_nothing(index_elements=["kind", "step"], index_where=CollectRequest.status.in_(ACTIVE))
           .returning(CollectRequest.id))
    new_id = (await db.execute(ins)).scalar_one_or_none()
    if new_id is not None:
        db.add(AuditEvent(user_id=uid, client_id=user.get("client_id") or "", event_type="collect.request",
                          payload={"request_id": str(new_id), "kind": kind, "step": step}))
        rid = new_id
    else:
        rid = (await db.execute(select(CollectRequest.id).where(
            CollectRequest.kind == kind, CollectRequest.step == step, CollectRequest.status.in_(ACTIVE)))).scalar_one()
    await db.commit()
    return await _view(db, rid, catalog=catalog, now=now), new_id is not None


async def cancel(db: AsyncSession, *, request_id, user: dict, catalog: dict, now: datetime | None = None) -> dict:
    """대기 요청 취소 — 대기가 아니면 409(도는 중은 1판에서 멈추지 않는다 · 수집 DB 쓰기 · 올리기 중간에 멈추면 치울 것이 생긴다)."""
    now = _now(now)
    rid = _uid(request_id)
    if rid is None:
        raise RequestError(404, "그런 요청이 없습니다")
    await _expire(db, now)
    got = (await db.execute(update(CollectRequest)
                            .where(CollectRequest.id == rid, CollectRequest.status == QUEUED)
                            .values(status=CANCELLED, finished_at=now, result=CANCELLED_NOTE)
                            .returning(CollectRequest.id))).scalar_one_or_none()
    if got is None:
        cur = (await db.execute(select(CollectRequest.status).where(CollectRequest.id == rid))).scalar_one_or_none()
        await db.commit()                                     # 만료 바꾸기는 남긴다
        if cur is None:
            raise RequestError(404, "그런 요청이 없습니다")
        raise RequestError(409, f"대기 중인 요청만 취소합니다 — 지금 「{STATUS_LABEL.get(cur, cur)}」")
    db.add(AuditEvent(user_id=_uid(user.get("id")), client_id=user.get("client_id") or "", event_type="collect.cancel",
                      payload={"request_id": str(rid)}))
    await db.commit()
    return await _view(db, rid, catalog=catalog, now=now)


async def listing(db: AsyncSession, *, catalog: dict, now: datetime | None = None, limit: int = 20) -> dict:
    """요청 목록(새것 먼저) · 작업자 상태 · 막는 때 — 화면이 한 번에 그린다. 읽기만 한다(만료는 보이기로만)."""
    now = _now(now)
    wv = worker_view(await _latest_worker(db), now=now)
    rows = (await db.execute(
        select(CollectRequest, User.name).outerjoin(User, User.id == CollectRequest.requested_by)
        .order_by(CollectRequest.requested_at.desc(), CollectRequest.id).limit(limit))).all()
    return {"requests": [request_view(r, catalog=catalog, worker=wv, now=now, requester=n) for r, n in rows],
            "worker": wv, "rules": rules(catalog, now=now), "checked_at": _iso(now)}


async def worker_status(db: AsyncSession, *, now: datetime | None = None) -> dict:
    return worker_view(await _latest_worker(db), now=_now(now))


# ── PC 작업자 쪽 ──────────────────────────────────────────────────────────
async def heartbeat(db: AsyncSession, *, name: str, pid: int | None, started_at: datetime, state: str,
                    note: str = "", allow_upload: bool = False, request_id=None, now: datetime | None = None) -> None:
    """작업자 신호 — 이름(PC)마다 한 줄을 고친다."""
    if state not in WORKER_STATES:
        raise ValueError(f"작업자 상태가 아니다 — {state}")
    vals = {"name": name[:64], "pid": pid, "started_at": started_at, "seen_at": _now(now), "state": state,
            "note": (note or "")[:300], "allow_upload": bool(allow_upload), "request_id": _uid(request_id)}
    await db.execute(pg_insert(CollectWorker).values(**vals).on_conflict_do_update(
        index_elements=["name"], set_={k: v for k, v in vals.items() if k != "name"}))
    await db.commit()


async def expire_stale(db: AsyncSession, *, now: datetime | None = None) -> int:
    n = await _expire(db, _now(now))
    await db.commit()
    return n


async def queued(db: AsyncSession) -> list[CollectRequest]:
    """대기 줄 — 먼저 온 차례(FIFO)."""
    return list((await db.execute(select(CollectRequest).where(CollectRequest.status == QUEUED)
                                  .order_by(CollectRequest.requested_at, CollectRequest.id))).scalars())


async def running_of(db: AsyncSession, *, worker: str) -> list[CollectRequest]:
    return list((await db.execute(select(CollectRequest).where(
        CollectRequest.status == RUNNING, CollectRequest.worker == worker))).scalars())


async def claim(db: AsyncSession, *, request_id, worker: str, now: datetime | None = None) -> bool:
    """가져가기 — 대기 줄일 때만 「도는 중」 으로(조건 UPDATE · 두 작업자가 같은 줄을 가져가지 못한다)."""
    got = (await db.execute(update(CollectRequest)
                            .where(CollectRequest.id == _uid(request_id), CollectRequest.status == QUEUED)
                            .values(status=RUNNING, started_at=_now(now), worker=worker[:64])
                            .returning(CollectRequest.id))).scalar_one_or_none()
    await db.commit()
    return got is not None


async def finish(db: AsyncSession, *, request_id, status: str, exit_code: int | None, result: str,
                 log_path: str = "", now: datetime | None = None) -> bool:
    """끝 적기 — 도는 중일 때만(두 번 적지 않는다)."""
    if status not in FINISHED:
        raise ValueError(f"끝 상태가 아니다 — {status}")
    got = (await db.execute(update(CollectRequest)
                            .where(CollectRequest.id == _uid(request_id), CollectRequest.status == RUNNING)
                            .values(status=status, finished_at=_now(now), exit_code=exit_code,
                                    result=(result or "")[:300], log_path=(log_path or "")[:200])
                            .returning(CollectRequest.id))).scalar_one_or_none()
    await db.commit()
    return got is not None


async def requeue(db: AsyncSession, *, request_id, note: str) -> bool:
    """도는 중 → 대기 — 러너가 「지금은 돌 수 없다」(막힘)로 돌아왔을 때. 실패가 아니라 다시 기다린다."""
    got = (await db.execute(update(CollectRequest)
                            .where(CollectRequest.id == _uid(request_id), CollectRequest.status == RUNNING)
                            .values(status=QUEUED, started_at=None, worker="", result=(note or "")[:300])
                            .returning(CollectRequest.id))).scalar_one_or_none()
    await db.commit()
    return got is not None


async def reject(db: AsyncSession, *, request_id, why: str, now: datetime | None = None) -> bool:
    """거절 — 작업자가 받지 않는 대기 요청(기다려도 바뀌지 않는 까닭만 · 시간 때문에 못 도는 것은 거절이 아니라 기다림)."""
    got = (await db.execute(update(CollectRequest)
                            .where(CollectRequest.id == _uid(request_id), CollectRequest.status == QUEUED)
                            .values(status=REJECTED, finished_at=_now(now), result=(why or "")[:300])
                            .returning(CollectRequest.id))).scalar_one_or_none()
    await db.commit()
    return got is not None
