"""리밸런싱 정책 · 현금흐름 예산 · 일별 계획 통합."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012_rebalance_policy'
down_revision = '320128e72164'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rebalance_plans', sa.Column('drift_check_mode', sa.String(12), nullable=False, server_default='always'))
    op.add_column('rebalance_plans', sa.Column('exclude_unplanned', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('rebalance_plans', 'exclude_unplanned', server_default=sa.true())
    op.add_column('cashflow_events', sa.Column('remaining_budget', sa.Float(), nullable=False, server_default='0'))
    op.add_column('rebalance_runs', sa.Column('triggers', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.add_column('rebalance_runs', sa.Column('plan_kind', sa.String(12), nullable=False, server_default='full'))
    op.add_column('rebalance_runs', sa.Column('decision_date', sa.Date(), nullable=True))
    op.add_column('rebalance_runs', sa.Column('context', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.execute("UPDATE rebalance_runs SET triggers = jsonb_build_array(trigger)")
    op.create_index('uq_rebalance_plan_day', 'rebalance_runs', ['plan_id', 'decision_date'], unique=True,
                    postgresql_where=sa.text("trigger <> 'MANUAL'"))


def downgrade():
    op.drop_index('uq_rebalance_plan_day', table_name='rebalance_runs')
    for col in ('context', 'decision_date', 'plan_kind', 'triggers'):
        op.drop_column('rebalance_runs', col)
    op.drop_column('cashflow_events', 'remaining_budget')
    op.drop_column('rebalance_plans', 'exclude_unplanned')
    op.drop_column('rebalance_plans', 'drift_check_mode')
