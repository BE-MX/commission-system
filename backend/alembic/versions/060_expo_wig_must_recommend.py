"""expo wig must_recommend flag (必推：不论脸型都保证进前 6 推荐)

Revision ID: 060_expo_wig_must_recommend
Revises: 059_aftersales_notify_user
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

revision = "060_expo_wig_must_recommend"
down_revision = "059_aftersales_notify_user"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_expo_wigs",
        sa.Column(
            "must_recommend",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
            comment="1=必推(不论脸型都保证进前6推荐);0=否",
        ),
    )


def downgrade():
    op.drop_column("ark_expo_wigs", "must_recommend")
