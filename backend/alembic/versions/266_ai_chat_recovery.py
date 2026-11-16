"""Chat generation recovery, answer versions and role quotas.

Revision ID: 266_ai_chat_recovery
Revises: 265_universal_ai_chat
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "266_ai_chat_recovery"
down_revision = "265_universal_ai_chat"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ark_ai_chat_messages") as batch:
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("finish_reason", sa.String(32), nullable=True))
        batch.add_column(sa.Column("first_token_ms", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("selected_answer_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("continuation_of_message_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key("fk_ai_chat_selected_answer_session", "ark_ai_chat_messages",
                                 ["session_id", "selected_answer_id"], ["session_id", "id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_ai_chat_continue_session", "ark_ai_chat_messages",
                                 ["session_id", "continuation_of_message_id"], ["session_id", "id"], ondelete="RESTRICT")
        batch.create_index("idx_ai_chat_generation_lease", ["status", "lease_expires_at"])
    user_id = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    op.create_table("ark_ai_chat_role_limits",
        sa.Column("role_id", user_id, sa.ForeignKey("ark_roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("updated_by", user_id, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("daily_limit >= 0 AND daily_limit <= 10000", name="ck_ai_chat_role_limit"))


def downgrade():
    raise RuntimeError("Preserve chat recovery and answer history; use a reviewed forward migration")
