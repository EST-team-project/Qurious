"""알림 사건별 설정(preferences) · 알림 이력 보고 원본(payload).

- notification_settings.preferences : 사건별 on/silent/off · 조용한 시간 (JSONB, 기본 {})
- notification_log.payload          : 보낸(또는 보관한) 보고 원본 (JSONB, NULL 허용)
- notification_log.delivery_status  : 'held'(보관) · 'digesting'(묶음 발송 중) · 'digested'(묶음으로 나감) 값이 새로 쓰인다(칸 길이 20자 안)

Revision ID: 0035_notification_prefs
Revises: 0034_backtest_account_isolation
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0035_notification_prefs"
down_revision = "0034_backtest_account_isolation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_settings",
        sa.Column("preferences", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("notification_log", sa.Column("payload", postgresql.JSONB(), nullable=True))
    # 보관 행을 풀 때 상태로 찾으므로 부분 인덱스(보관 중인 행만)
    op.create_index(
        "ix_notification_log_held", "notification_log", ["user_id"],
        postgresql_where=sa.text("delivery_status = 'held'"),
    )


def downgrade():
    op.drop_index("ix_notification_log_held", table_name="notification_log")
    op.drop_column("notification_log", "payload")
    op.drop_column("notification_settings", "preferences")
