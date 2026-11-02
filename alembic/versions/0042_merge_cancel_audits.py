"""#489의 기존 감사 병합 이력과 개인 KIS 취소 이력을 잇는다."""
revision = "0042_merge_cancel_audits"
down_revision = ("0041_broker_cancel", "0040_merge_paper_snapshot_audits")
branch_labels = depends_on = None


def upgrade():
    pass


def downgrade():
    pass
