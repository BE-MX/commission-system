"""Add an explicit manual deal status for customer follow-up.

Revision ID: 258_followup_deal_override
Revises: 257_project_radar
"""
from alembic import context, op
import sqlalchemy as sa

revision = "258_followup_deal_override"
down_revision = "257_project_radar"
branch_labels = None
depends_on = None

_TABLE = "ark_dom_followup_customer_profiles"


def upgrade():
    op.add_column(_TABLE, sa.Column(
        "deal_override_status", sa.String(16), comment="手动设置的跟进成交状态，NULL时按原口径判定",
    ))


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Deal status downgrade requires a live data-preservation check")
    if op.get_bind().scalar(sa.text(f"SELECT 1 FROM {_TABLE} WHERE deal_override_status IS NOT NULL LIMIT 1")):
        raise RuntimeError("Manual deal statuses exist; preserve them before downgrade")
    op.drop_column(_TABLE, "deal_override_status")
