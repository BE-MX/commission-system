"""add consecutive_errors to shipment_tracking

Revision ID: 017
Revises: 016
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016_add_proxy_url"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shipment_tracking",
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("shipment_tracking", "consecutive_errors")
