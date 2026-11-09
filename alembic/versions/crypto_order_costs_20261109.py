"""Add crypto paper-trading cost fields."""
from alembic import op
import sqlalchemy as sa

revision = "crypto_order_costs_20261109"
down_revision = "0046_merge_notif_paper_kis"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crypto_orders", sa.Column("reference_price", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("commission", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("fee_rate", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("slippage_bps", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("slippage_amount", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("net_amount", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("cost_basis", sa.String(20), nullable=False, default="none", server_default="none"))
    op.add_column("crypto_orders", sa.Column("allocated_cost_basis", sa.Float(), nullable=True))
    op.add_column("crypto_orders", sa.Column("realized_pnl", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("crypto_orders", "realized_pnl")
    op.drop_column("crypto_orders", "allocated_cost_basis")
    op.drop_column("crypto_orders", "cost_basis")
    op.drop_column("crypto_orders", "net_amount")
    op.drop_column("crypto_orders", "slippage_amount")
    op.drop_column("crypto_orders", "slippage_bps")
    op.drop_column("crypto_orders", "fee_rate")
    op.drop_column("crypto_orders", "commission")
    op.drop_column("crypto_orders", "reference_price")
