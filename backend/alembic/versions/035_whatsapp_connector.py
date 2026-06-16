"""add whatsapp connector tables

Revision ID: 035_whatsapp_connector
Revises: 034_customer_radar
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers
revision = "035_whatsapp_connector"
down_revision = "034_customer_radar"
branch_labels = None
depends_on = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_whatsapp_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_uid", sa.String(80), nullable=False),
        sa.Column("ark_user_id", _UINT, nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="binding"),
        sa.Column("connector_status", sa.String(60), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["ark_user_id"], ["ark_users.id"]),
        sa.UniqueConstraint("account_uid", name="uk_wa_account_uid"),
    )
    op.create_index("idx_wa_account_user_status", "ark_whatsapp_accounts", ["ark_user_id", "status"])
    op.create_index("idx_wa_account_phone", "ark_whatsapp_accounts", ["phone_number"])

    op.create_table(
        "ark_whatsapp_bind_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bind_session_uid", sa.String(80), nullable=False),
        sa.Column("account_uid", sa.String(80), nullable=True),
        sa.Column("ark_user_id", _UINT, nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("qr_code_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["ark_user_id"], ["ark_users.id"]),
        sa.UniqueConstraint("bind_session_uid", name="uk_wa_bind_session_uid"),
    )
    op.create_index("idx_wa_bind_user_status", "ark_whatsapp_bind_sessions", ["ark_user_id", "status"])

    op.create_table(
        "ark_whatsapp_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_uid", sa.String(120), nullable=False),
        sa.Column("account_uid", sa.String(80), nullable=False),
        sa.Column("chat_id", sa.String(160), nullable=False),
        sa.Column("contact_phone", sa.String(80), nullable=True),
        sa.Column("contact_name", sa.String(160), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_message_preview", sa.String(500), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("conversation_uid", name="uk_wa_conversation_uid"),
        sa.UniqueConstraint("account_uid", "chat_id", name="uk_wa_conv_account_chat"),
    )
    op.create_index("idx_wa_conv_account_time", "ark_whatsapp_conversations", ["account_uid", "last_message_at"])

    op.create_table(
        "ark_whatsapp_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("message_uid", sa.String(160), nullable=False),
        sa.Column("account_uid", sa.String(80), nullable=False),
        sa.Column("conversation_uid", sa.String(120), nullable=True),
        sa.Column("external_message_id", sa.String(180), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("sender_phone", sa.String(80), nullable=True),
        sa.Column("content_type", sa.String(40), nullable=False, server_default="text"),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_preview", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("raw_payload_hash", sa.String(80), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("message_uid", name="uk_wa_message_uid"),
        sa.UniqueConstraint("account_uid", "external_message_id", name="uk_wa_msg_account_external"),
    )
    op.create_index("idx_wa_msg_account_time", "ark_whatsapp_messages", ["account_uid", "sent_at"])
    op.create_index("idx_wa_msg_conversation_time", "ark_whatsapp_messages", ["conversation_uid", "sent_at"])

    op.create_table(
        "ark_whatsapp_attachments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("message_uid", sa.String(160), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(120), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_wa_attach_message", "ark_whatsapp_attachments", ["message_uid"])

    op.create_table(
        "ark_whatsapp_pull_cursors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_uid", sa.String(80), nullable=False),
        sa.Column("resource", sa.String(40), nullable=False),
        sa.Column("cursor_value", sa.String(500), nullable=True),
        sa.Column("last_pulled_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("account_uid", "resource", name="uk_wa_cursor_account_resource"),
    )

    op.create_table(
        "ark_whatsapp_audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_uid", sa.String(80), nullable=True),
        sa.Column("ark_user_id", _UINT, nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("result", sa.String(30), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["ark_user_id"], ["ark_users.id"]),
    )
    op.create_index("idx_wa_audit_account_time", "ark_whatsapp_audit_logs", ["account_uid", "created_at"])


def downgrade() -> None:
    op.drop_table("ark_whatsapp_audit_logs")
    op.drop_table("ark_whatsapp_pull_cursors")
    op.drop_table("ark_whatsapp_attachments")
    op.drop_table("ark_whatsapp_messages")
    op.drop_table("ark_whatsapp_conversations")
    op.drop_table("ark_whatsapp_bind_sessions")
    op.drop_table("ark_whatsapp_accounts")
