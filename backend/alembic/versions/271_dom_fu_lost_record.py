"""Persist the lost-customer recording exception without granting ongoing responsibility."""

from alembic import context, op
import sqlalchemy as sa

revision = "271_dom_fu_lost_record"
down_revision = "270_dom_fu_guided"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_followups", sa.Column(
        "recorded_outside_scope", sa.Boolean(), nullable=False, server_default="0",
        comment="凭流失客户例外录入的记录，不授予历史补录资格或续期公海跟进钟",
    ))


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Cannot verify the absence of out-of-scope records in offline mode")
    if op.get_bind().scalar(sa.text(
        "SELECT id FROM ark_domestic_followups WHERE recorded_outside_scope = 1 LIMIT 1"
    )) is not None:
        raise RuntimeError("Cannot drop the permission boundary of out-of-scope follow-up records")
    op.drop_column("ark_domestic_followups", "recorded_outside_scope")
