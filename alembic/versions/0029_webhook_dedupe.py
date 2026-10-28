"""TradingView 웹훅 — 알림 단위 중복 키 · 중복 횟수 · 지연 초 · 상태 칸 넓힘(설계 3.6 #4 · #5)."""
from alembic import op
import sqlalchemy as sa

revision = "0029_webhook_dedupe"
down_revision = "0028_execution_control"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("webhook_signals", sa.Column("dedup_key", sa.String(64), nullable=True))
    op.add_column("webhook_signals", sa.Column("dup_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("webhook_signals", sa.Column("delay_sec", sa.Float(), nullable=True))
    # rejected_format(15자) 같은 새 상태가 들어가도록 12 → 16
    op.alter_column("webhook_signals", "status", existing_type=sa.String(12), type_=sa.String(16),
                    existing_nullable=False)
    # dedup_key 가 NULL 인 줄(알림만 오는 신호 · 옛 줄)은 여러 개여도 된다 — PG 의 유일 제약은 NULL 을 서로 다르게 본다
    op.create_index("uq_webhook_signals_user_dedup", "webhook_signals", ["user_id", "dedup_key"], unique=True)


def downgrade():
    op.drop_index("uq_webhook_signals_user_dedup", table_name="webhook_signals")
    # 16자 상태가 이미 들어 있으면 줄이기 전에 잘라 낸다
    op.execute("UPDATE webhook_signals SET status = LEFT(status, 12)")
    op.alter_column("webhook_signals", "status", existing_type=sa.String(16), type_=sa.String(12),
                    existing_nullable=False)
    op.drop_column("webhook_signals", "delay_sec")
    op.drop_column("webhook_signals", "dup_count")
    op.drop_column("webhook_signals", "dedup_key")
