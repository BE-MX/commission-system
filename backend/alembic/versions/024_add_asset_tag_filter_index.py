"""add covering index for asset tag filtering

Revision ID: 024_add_asset_tag_filter_index
Revises: 023_fix_asset_tags_pk
Create Date: 2026-05-25 19:30:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "024_add_asset_tag_filter_index"
down_revision: Union[str, None] = "023_fix_asset_tags_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_asset_tag_dim_val_asset",
        "ark_asset_tags",
        ["dimension_id", "tag_value_id", "asset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_asset_tag_dim_val_asset", table_name="ark_asset_tags")
