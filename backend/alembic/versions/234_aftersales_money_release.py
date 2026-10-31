"""Project audited partial aftersales releases without overwriting applications."""
from alembic import op
import sqlalchemy as sa

revision = "234_aftersales_money_release"
down_revision = "233_local_aftersales"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_settlement_applications", sa.Column("released_amount", sa.Numeric(14, 2),
        nullable=False, server_default="0", comment="售后累计释放占用金额，保留原占用事实"))
    op.add_column("ark_settlement_applications", sa.Column("released_bank_charge", sa.Numeric(14, 2),
        nullable=False, server_default="0", comment="售后累计释放客户附加费用"))


def downgrade():
    raise RuntimeError("Aftersales money releases cannot be discarded; use a corrective migration")
