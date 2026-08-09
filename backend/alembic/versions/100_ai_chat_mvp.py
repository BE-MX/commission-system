"""Add Customer AI Chat MVP persistence schema.

Revision ID: 100_ai_chat_mvp
Revises: 099_sales_automation
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "100_ai_chat_mvp"
down_revision = "099_sales_automation"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_ai_chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "owner_user_id",
            USER_ID,
            sa.ForeignKey("ark_users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="会话所有者",
        ),
        sa.Column("title", sa.String(200), nullable=False, comment="会话标题"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="AI 方案对话会话",
    )
    op.create_index(
        "idx_ai_chat_session_owner_updated",
        "ark_ai_chat_sessions",
        ["owner_user_id", "updated_at"],
    )

    op.create_table(
        "ark_ai_chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_chat_sessions.id", ondelete="RESTRICT"),
            nullable=False,
            comment="所属会话",
        ),
        sa.Column("role", sa.String(16), nullable=False, comment="消息角色"),
        sa.Column(
            "request_id", sa.String(64), nullable=True, comment="会话内客户端幂等键"
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="Markdown 消息正文",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="completed",
            comment="消息状态",
        ),
        sa.Column("error_message", sa.Text(), nullable=True, comment="可行动失败信息"),
        sa.Column(
            "retry_of_message_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_chat_messages.id", ondelete="RESTRICT"),
            nullable=True,
            comment="被重试的消息",
        ),
        sa.Column(
            "ai_call_log_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"),
            nullable=True,
            comment="共享 AI 调用日志",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "request_id",
            name="uq_ai_chat_message_session_request",
        ),
        comment="AI 方案对话消息",
    )
    op.create_index(
        "idx_ai_chat_message_session_created",
        "ark_ai_chat_messages",
        ["session_id", "created_at"],
    )

    op.create_table(
        "ark_ai_chat_attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_chat_sessions.id", ondelete="RESTRICT"),
            nullable=False,
            comment="所属会话",
        ),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_chat_messages.id", ondelete="RESTRICT"),
            nullable=True,
            comment="发送后绑定的用户消息",
        ),
        sa.Column("original_name", sa.String(255), nullable=False, comment="原始文件名"),
        sa.Column("mime_type", sa.String(128), nullable=False, comment="MIME 类型"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, comment="文件字节数"),
        sa.Column(
            "storage_path",
            sa.String(512),
            nullable=False,
            comment="私有根目录下相对路径",
        ),
        sa.Column(
            "attachment_type",
            sa.String(16),
            nullable=False,
            comment="附件类型 image/document",
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True, comment="文档抽取正文"),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="draft",
            comment="附件状态",
        ),
        sa.Column(
            "created_by",
            USER_ID,
            sa.ForeignKey("ark_users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="上传人",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="AI 方案对话私有附件",
    )
    op.create_index(
        "idx_ai_chat_attachment_session_created",
        "ark_ai_chat_attachments",
        ["session_id", "created_at"],
    )
    op.create_index(
        "idx_ai_chat_attachment_draft_status",
        "ark_ai_chat_attachments",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_ai_chat_attachment_draft_status",
        table_name="ark_ai_chat_attachments",
    )
    op.drop_index(
        "idx_ai_chat_attachment_session_created",
        table_name="ark_ai_chat_attachments",
    )
    op.drop_table("ark_ai_chat_attachments")
    op.drop_index(
        "idx_ai_chat_message_session_created", table_name="ark_ai_chat_messages"
    )
    op.drop_table("ark_ai_chat_messages")
    op.drop_index(
        "idx_ai_chat_session_owner_updated", table_name="ark_ai_chat_sessions"
    )
    op.drop_table("ark_ai_chat_sessions")
