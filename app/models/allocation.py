"""사용자별 마지막으로 완료된 배분 결과. 실행 플랜과 분리된 저장본."""
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UpdatedAtMixin


class AllocationResult(Base, UpdatedAtMixin):
    __tablename__ = "allocation_results"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
