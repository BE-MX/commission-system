"""fix asset tags primary key

Revision ID: 023_fix_asset_tags_pk
Revises: 022_add_color_module
Create Date: 2026-05-22 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '023_fix_asset_tags_pk'
down_revision: Union[str, None] = '022_add_color_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'mysql':
        op.execute(
            "ALTER TABLE ark_asset_tags "
            "DROP PRIMARY KEY, "
            "ADD PRIMARY KEY (asset_id, dimension_id, tag_value_id)"
        )
    # SQLite 测试不走 Alembic，跳过


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'mysql':
        op.execute(
            "ALTER TABLE ark_asset_tags "
            "DROP PRIMARY KEY, "
            "ADD PRIMARY KEY (asset_id)"
        )
