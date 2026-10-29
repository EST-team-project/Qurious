"""동의 · 철회 기록 표 — 가입 필수 동의와 알림 연동 선택 동의를 행으로 쌓는다(고치지 않는다)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_user_consents"
down_revision = "0031_broker_secrets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("user_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_key", sa.String(40), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("terms_version", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("action in ('grant', 'withdraw')", name="ck_user_consents_action"))
    op.create_index("ix_user_consents_user_key_created", "user_consents",
                    ["user_id", "consent_key", "created_at"])


def downgrade():
    op.drop_index("ix_user_consents_user_key_created", table_name="user_consents")
    op.drop_table("user_consents")
