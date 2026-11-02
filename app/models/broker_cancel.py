"""취소 요청도 전송 전에 기록한다. 응답 유실을 새 취소 요청으로 재시도하지 않는다."""
import uuid
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin


class BrokerCancelRequest(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "broker_cancel_requests"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("live_orders.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    cancel_order_no: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")

