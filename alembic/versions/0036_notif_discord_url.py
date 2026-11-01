"""알림 설정에 사용자별 디스코드 웹훅 주소 칸.

- notification_settings.discord_webhook_url : 사용자가 알림 설정 화면에서 넣는 디스코드 웹훅 주소 (문자열 300자, 기본 '')
  비어 있으면 서버 공용 주소(.env DISCORD_WEBHOOK_URL)로 나간다.

Revision ID: 0036_notif_discord_url
Revises: 0035_notification_prefs
"""
from alembic import op
import sqlalchemy as sa


revision = "0036_notif_discord_url"
down_revision = "0035_notification_prefs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_settings",
        sa.Column("discord_webhook_url", sa.String(length=300), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("notification_settings", "discord_webhook_url")
