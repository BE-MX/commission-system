"""Store automatic fee estimates on portal quotes.

Additive nullable column: existing quotes keep NULL and their stored evidence
hashes remain valid because the estimate is hashed only when present.
"""
from alembic import op
import sqlalchemy as sa

revision = "200_portal_quote_fee_estimate"
down_revision = "199_portal_catalog_families"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_order_portal_quotes", sa.Column(
        "fee_estimate_json", sa.JSON(), nullable=True,
        comment="按重量运费与付款方式手续费的自动计算结果，空表示未启用"))


def downgrade():
    raise RuntimeError("Quote evidence must be preserved; disable automatic fees instead of downgrading")
