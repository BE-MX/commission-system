"""Add metadata-only WhatsApp reply request ownership and quota guard.

Revision ID: 141_whatsapp_reply_requests
Revises: 140_domestic_order_kinds
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "141_whatsapp_reply_requests"
down_revision = "140_domestic_order_kinds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_whatsapp_reply_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), sa.ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql"), sa.ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False, comment="扩展本地随机请求标识"),
        sa.Column("payload_hash", sa.String(64), nullable=False, comment="请求载荷摘要，不存正文"),
        sa.Column("owner_id", sa.String(36), nullable=False, comment="执行进程随机标识"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False),
        sa.Column("source_revisions", sa.JSON(), nullable=False, comment="授权知识文档及修订标识"),
        sa.Column("timings_ms", sa.JSON(), nullable=False, comment="阶段耗时毫秒数"),
        sa.Column("error_code", sa.String(64), comment="受限错误码，不存异常正文"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=False, comment="并发占位截止北京时间，不允许接管重跑"),
        sa.Column("finished_at", sa.DateTime(), comment="完成北京时间"),
        sa.UniqueConstraint("device_id", "request_id", name="uq_war_device_request"),
        sa.CheckConstraint("input_chars >= 0", name="ck_war_nonnegative_chars"),
    )
    op.create_index("idx_war_user_created", "ark_whatsapp_reply_requests", ["user_id", "created_at"])
    op.create_index("idx_war_user_lease", "ark_whatsapp_reply_requests", ["user_id", "status", "lease_until"])


def downgrade():
    # Drops only duplicate/cost metadata; never business conversations (not stored).
    op.drop_table("ark_whatsapp_reply_requests")
