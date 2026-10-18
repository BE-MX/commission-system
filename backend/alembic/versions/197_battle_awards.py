"""Add award rules without changing existing battle reports or business mirrors."""
from alembic import op
import sqlalchemy as sa

revision = "197_battle_awards"
down_revision = "196_domestic_commission"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_battle_reports", sa.Column("award_kind", sa.String(24), nullable=False, server_default="gmv"))
    op.add_column("ark_battle_reports", sa.Column("award_rules", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Award baselines and audit facts must be preserved; roll back application code only")
