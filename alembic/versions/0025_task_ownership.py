"""Celery 작업 조회·취소의 사용자 경계 (#200)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025_task_ownership"
down_revision = "0024_stop_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_ownership",
        sa.Column("task_id", sa.String(36), primary_key=True, comment="큐 발행 전에 생성한 작업 UUID"),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
                  comment="요청 사용자 — 결과 조회·취소의 권한 기준"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_ownership_user_id", "task_ownership", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_task_ownership_user_id", table_name="task_ownership")
    op.drop_table("task_ownership")
