"""알림 설정의 비밀 9칸(토큰 · 웹훅 · SMTP 비밀번호 · 카카오 · 문자 키)을 키 파일 기반 암호문으로 전환한다.

0031(증권사 자격증명)과 같은 계약이다: 전체 성공 또는 전체 롤백 · 평문 호환 없음 · 자동 downgrade 금지.
배포 순서(옛 이미지가 암호문을 평문으로 읽거나 새 이미지가 평문을 읽는 구간이 없게)는 docs/phase-3/05-deployment/알림-비밀값-암호화-운영.md.
"""
from alembic import op
import sqlalchemy as sa

revision = "0044_notification_secrets"
down_revision = "0043_regime_targets"
branch_labels = None
depends_on = None


def upgrade():
    from app.lib.notification_secrets import FIELDS, reencrypt
    bind = op.get_bind()
    # 사전 점검 — 가림값("****")이 저장돼 있으면 그것을 비밀로 착각해 암호화하게 된다. keep_secret 이 막으므로 없어야 한다
    for field in FIELDS:
        masked = bind.execute(sa.text(f"SELECT count(*) FROM notification_settings WHERE {field} = '****'")).scalar()
        if masked:
            raise RuntimeError(f"notification_settings.{field} 에 가림값 '****' 가 {masked}건 저장돼 있습니다. 원인을 확인한 뒤 다시 실행하세요.")
    for field in FIELDS:  # 암호문(약 1.4배 + 접두어)이 원문보다 길어 Text 로
        op.alter_column("notification_settings", field, type_=sa.Text(), existing_nullable=False)
    reencrypt(bind, allow_legacy=True)
    for field in FIELDS:
        op.create_check_constraint("ck_notification_encrypted_" + field, "notification_settings",
                                   f"{field} = '' OR {field} LIKE 'qnc1:%'")


def downgrade():
    # 암호문을 평문으로 되돌리거나 짧은 칸에 자르지 않는다 — 키와 암호화 백업을 보존하고 같은 계약의 코드로 전진 수정한다.
    raise RuntimeError("알림 비밀값 암호화는 자동 downgrade하지 않습니다. 키와 암호화 백업을 보존하고 전진 수정하세요.")
