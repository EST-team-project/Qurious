"""증권사 키·비밀키·계좌번호를 키 파일 기반 암호문으로 전환한다."""
from alembic import op
import sqlalchemy as sa

revision = "0031_broker_secrets"
down_revision = "0030_strategy_runtime"
branch_labels = None
depends_on = None


def upgrade():
    from app.lib.broker_secrets import reencrypt
    for field in ("app_key", "app_secret", "account_no"):
        op.alter_column("broker_settings", field, type_=sa.Text(), existing_nullable=False)
    reencrypt(op.get_bind(), allow_legacy=True)
    for field in ("app_key", "app_secret", "account_no"):
        op.create_check_constraint("ck_broker_encrypted_" + field, "broker_settings", f"{field} = '' OR {field} LIKE 'qbc1:%'")


def downgrade():
    # 암호문을 평문으로 되돌리거나 기존 짧은 칸에서 자르지 않는다.
    raise RuntimeError("자격증명 암호화는 자동 downgrade하지 않습니다. 키와 암호화 백업을 보존하고 전진 수정하세요.")
