"""Receipt recovery evidence and shared background index. Preserve legacy uncertainty."""
from alembic import op
import sqlalchemy as sa

revision = "175_receipt_recovery"
down_revision = "174_domestic_decision"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_receipts", sa.Column("send_phase", sa.String(16), nullable=True))
    op.add_column("ark_receipts", sa.Column("recovery_kind", sa.String(24), nullable=True))
    op.add_column("ark_receipts", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("ark_receipts", sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_ark_receipts_recovery_kind", "ark_receipts", ["recovery_kind"])
    op.create_index("ix_ark_receipts_next_attempt_at", "ark_receipts", ["next_attempt_at"])
    op.create_table("ark_receipt_attempts",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("receipt_id", sa.BigInteger(), sa.ForeignKey("ark_receipts.id"), nullable=False),
        sa.Column("payload_hash", sa.String(64)), sa.Column("remote_id", sa.String(64)),
        sa.Column("remote_no", sa.String(64)), sa.Column("handled_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_ark_receipt_attempts_receipt_id", "ark_receipt_attempts", ["receipt_id"])
    op.create_table("ark_receipt_index_states",
        sa.Column("source", sa.String(64), primary_key=True), sa.Column("snapshot", sa.JSON()),
        sa.Column("lease_token", sa.String(64)), sa.Column("lease_until", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()))


def downgrade():
    raise RuntimeError("回款恢复证据不可删除；请向前修复")
