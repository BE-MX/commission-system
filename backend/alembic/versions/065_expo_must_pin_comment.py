"""expo must_recommend 语义改为主推置顶，同步列注释（仅 comment，metadata-only 无锁）

Revision ID: 065_expo_must_pin_comment
Revises: 064_commission_my_page_code
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op

revision = "065_expo_must_pin_comment"
down_revision = "064_commission_my_page_code"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "ark_expo_wigs",
        "must_recommend",
        existing_type=sa.SmallInteger(),
        existing_nullable=False,
        existing_server_default="0",
        comment="1=主推(置顶推荐列表最前,仍按性别过滤);0=否",
    )


def downgrade():
    op.alter_column(
        "ark_expo_wigs",
        "must_recommend",
        existing_type=sa.SmallInteger(),
        existing_nullable=False,
        existing_server_default="0",
        comment="1=必推(不论脸型都保证进前6推荐);0=否",
    )
