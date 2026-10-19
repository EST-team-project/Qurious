"""HTTP 요청으로 발행한 Celery 작업의 소유자. 결과 만료와 독립적으로 보관한다."""
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class TaskOwnership(Base, CreatedAtMixin):
    __tablename__ = "task_ownership"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="큐 발행 전에 생성한 작업 UUID")
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="요청 사용자 — 결과 조회·취소의 권한 기준",
    )
