"""Add bounded, explicitly selected inquiry memory for sales reply assistance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "143_whatsapp_reply_inquiries"
down_revision = "142_domestic_prod_customer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_whatsapp_reply_inquiries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), sa.ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"), sa.ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("last_commit_request", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_wri_revision"),
    )
    op.create_index("idx_wri_owner_device", "ark_whatsapp_reply_inquiries", ["user_id", "device_id"])
    op.create_index("idx_wri_expiry", "ark_whatsapp_reply_inquiries", ["expires_at"])


def downgrade():
    # Inquiry notes are business data. Destructive rollback requires a separate
    # reviewed export/retention procedure; an application rollback keeps the table.
    raise RuntimeError("Inquiry data must be preserved; use a reviewed forward migration")
