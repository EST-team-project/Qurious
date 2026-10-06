"""main의 주문 추적 이력과 리밸런싱 정책 이력을 연결한다.

이미 적용된 두 revision은 그대로 유지한다. 어느 갈래에서 시작하든
나머지 변경을 먼저 적용한 뒤 하나의 head(0014)에 도달한다.
"""

revision = "0014"
down_revision = ("0013", "0012_rebalance_policy")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
