"""작업을 발행하기 전에 소유자를 저장하고, 결과/취소 전에 접근을 검사한다."""
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.task import TaskOwnership

logger = logging.getLogger(__name__)


def is_admin(user: dict) -> bool:
    return "admin" in user.get("roles", [])


async def enqueue_owned_task(db: AsyncSession, user: dict, task, **kwargs) -> str:
    """소유자 저장 실패 시 발행하지 않는다. 큐 응답 불명 시 자동 재발행하지 않는다."""
    task_id = str(uuid.uuid4())
    db.add(TaskOwnership(task_id=task_id, user_id=uuid.UUID(str(user["id"]))))
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("작업 소유자 저장 실패 task_id=%s", task_id)
        raise HTTPException(503, "작업을 등록하지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from None

    def publish():
        # 인증 주체는 kwargs가 아니라 위 DB 행에만 쓴다. 모든 HTTP 발행 경로가 공유한다.
        task.apply_async(kwargs=kwargs, task_id=task_id, retry=False)

    try:
        await run_in_threadpool(publish)
    except Exception:
        # 브로커가 받은 뒤 연결이 끊겼을 수도 있어 소유자 기록은 지우지 않는다.
        logger.exception("작업 큐 전달 확인 실패 task_id=%s", task_id)
        raise HTTPException(503, "작업 전달을 확인하지 못했습니다. 중복 실행을 피하려면 관리자에게 확인해 주세요.") from None
    return task_id


async def require_task_access(db: AsyncSession, user: dict, task_id: str) -> None:
    try:
        ownership = await db.get(TaskOwnership, task_id)
    except SQLAlchemyError:
        logger.exception("작업 소유자 조회 실패 task_id=%s", task_id)
        raise HTTPException(503, "작업 권한을 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from None

    # 기존/시스템 작업은 소유자를 추측하지 않는다. 관리자만 별도 접근한다.
    if is_admin(user):
        return
    if ownership is None or str(ownership.user_id) != str(user["id"]):
        # 남의 작업과 존재하지 않는 작업을 구별해 알려 주지 않는다.
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
