"""알림 비밀 암호화(0044)와 Paper↔KIS 대사(0045)의 갈래를 하나로 잇는다.

두 리비전이 모두 0043_regime_targets 에서 갈라져 head 가 둘이 되었고
`alembic upgrade head` 가 "Multiple head revisions" 로 실패했다(2026-11-07 확인).
스키마는 바꾸지 않는다 — 두 갈래의 적용 순서에 의존성이 없다(서로 다른 표).
이미 `upgrade heads` 로 두 갈래를 적용한 DB 는 이 리비전만 기록하고 지나간다.
"""

revision = "0046_merge_notif_paper_kis"
down_revision = ("0044_notification_secrets", "0045_paper_kis_track")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
