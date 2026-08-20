"""track public-pool duplicates found during lead discovery

Revision ID: 117_sales_pool_dedupe
Revises: 116_domestic_order_opt
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "117_sales_pool_dedupe"
down_revision = "116_domestic_order_opt"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("ark_sales_search_jobs", "public_pool_deduplicated_count"):
        op.add_column("ark_sales_search_jobs", sa.Column(
            "public_pool_deduplicated_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="命中OKKI公海客户而拦截的候选数",
        ))


def downgrade() -> None:
    if _has_column("ark_sales_search_jobs", "public_pool_deduplicated_count"):
        op.drop_column("ark_sales_search_jobs", "public_pool_deduplicated_count")
