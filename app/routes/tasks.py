"""Celery 태스크 상태 조회 API.

클라이언트는 /api/chat/async 등 비동기 엔드포인트에서 task_id 를 받은 뒤
이 엔드포인트를 폴링하여 진행 상태와 최종 결과를 확인한다.

상태 흐름: pending → running → success | error
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from celery.result import AsyncResult
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.celery_app import celery_app
from app.database.postgres import get_pg_session
from app.lib.jwt_auth import get_current_user_any
from app.services.task_access import is_admin, require_task_access

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

_STATE_MAP = {
    "PENDING":  "pending",
    "RECEIVED": "pending",
    "STARTED":  "running",
    "RETRY":    "running",
    "SUCCESS":  "success",
    "FAILURE":  "error",
    "REVOKED":  "error",
}


@router.get("/tasks/{task_id}", summary="태스크 상태 조회")
async def get_task_status(
    task_id: str,
    user=Depends(get_current_user_any),
    db: AsyncSession = Depends(get_pg_session),
):
    """
    task_id 로 Celery 태스크의 진행 상태와 결과를 반환한다.

    - **pending** : 큐 대기 중
    - **running** : 워커 실행 중
    - **success** : 완료 – result 필드에 반환값 포함
    - **error**   : 실패·취소 – error 필드에 사용자 안내(내부 예외 제외)
    """
    await require_task_access(db, user, task_id)
    try:
        return await run_in_threadpool(_read_status, task_id)
    except Exception:
        logger.exception("작업 상태 조회 실패 task_id=%s", task_id)
        raise HTTPException(503, "작업 상태를 불러오지 못했습니다. 잠시 뒤 다시 확인해 주세요.") from None


def _read_status(task_id: str) -> dict:
    # Redis I/O는 이벤트 루프 밖에서 수행하고 상태·결과를 같은 스냅샷으로 읽는다.
    meta = AsyncResult(task_id, app=celery_app).backend.get_task_meta(task_id)
    raw_state = meta["status"]
    base = {"task_id": task_id, "state": _STATE_MAP.get(raw_state, raw_state.lower())}
    if raw_state == "SUCCESS":
        return {**base, "result": meta.get("result")}
    if raw_state == "FAILURE":
        logger.warning("작업 실행 실패 task_id=%s: %s", task_id, meta.get("result"))
        return {**base, "result": None, "error": "작업을 완료하지 못했습니다. 관리자에게 작업 번호를 알려 주세요."}
    if raw_state == "REVOKED":
        return {**base, "result": None, "error": "작업이 취소되었습니다."}
    return {**base, "result": None}


@router.delete("/tasks/{task_id}", summary="태스크 취소")
async def revoke_task(
    task_id: str,
    terminate: bool = False,
    user=Depends(get_current_user_any),
    db: AsyncSession = Depends(get_pg_session),
):
    """실행 중이거나 대기 중인 태스크를 취소한다.

    - **terminate=false** (기본): 워커가 태스크를 시작하기 전에만 취소
    - **terminate=true**: 관리자만 실행 중인 워커 프로세스 강제 종료 (SIGTERM)
    응답의 revoked는 취소 요청 전송을 뜻하며 실제 취소 확정은 상태 조회로 확인한다.
    """
    await require_task_access(db, user, task_id)
    if terminate and not is_admin(user):
        raise HTTPException(403, "강제 종료는 관리자만 요청할 수 있습니다.")
    try:
        await run_in_threadpool(celery_app.control.revoke, task_id, terminate=terminate)
    except Exception:
        logger.exception("작업 취소 요청 실패 task_id=%s", task_id)
        raise HTTPException(503, "취소 요청을 확인하지 못했습니다. 작업 상태를 다시 확인해 주세요.") from None
    return {"task_id": task_id, "revoked": True, "terminate": terminate}
