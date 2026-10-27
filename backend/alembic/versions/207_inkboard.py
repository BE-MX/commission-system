"""Personal Kindle dashboard; additive tables only, preserve data on downgrade."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "207_inkboard"
down_revision = "206_domestic_shipment_cancel"
branch_labels = None
depends_on = None


def upgrade():
    ident = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    user_id = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    op.create_table("ark_ink_devices",
        sa.Column("id", ident, primary_key=True, autoincrement=True),
        sa.Column("owner_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_received_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Index("ix_ark_ink_devices_owner_id", "owner_id"))
    op.create_table("ark_ink_notes",
        sa.Column("id", ident, primary_key=True, autoincrement=True),
        sa.Column("owner_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.Index("ix_ark_ink_notes_owner_id", "owner_id"))
    op.create_table("ark_ink_messages",
        sa.Column("id", ident, primary_key=True, autoincrement=True),
        sa.Column("owner_id", user_id, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime()),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_ink_message_request"),
        sa.Index("ix_ink_message_owner_id", "owner_id", "id"))
    op.create_table("ark_ink_receipts",
        sa.Column("device_id", ident, sa.ForeignKey("ark_ink_devices.id"), primary_key=True),
        sa.Column("message_id", ident, sa.ForeignKey("ark_ink_messages.id"), primary_key=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime()))


def downgrade():
    raise RuntimeError("Kindle notes, messages and receipts are preserved; downgrade requires a separate data plan")
