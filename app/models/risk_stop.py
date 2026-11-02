"""보유 회차별 손절 근거. 전량 청산 뒤 새 진입은 다른 키를 사용한다."""
import uuid
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, CreatedAtMixin


class RiskStop(Base, CreatedAtMixin):
    __tablename__ = "execution_risk_stops"
    position_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    basis: Mapped[dict] = mapped_column(JSONB, nullable=False)
