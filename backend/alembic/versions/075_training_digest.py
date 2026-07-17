"""training: digest tables for training knowledge sharing

Revision ID: 075_training_digest
Revises: 074_invoice_price_kind_key
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "075_training_digest"
down_revision = "074_invoice_price_kind_key"
branch_labels = None
depends_on = None


USER_ID = mysql.INTEGER(unsigned=True)
BIG_ID = mysql.BIGINT(unsigned=True)


def upgrade():
    op.create_table(
        "ark_training_digests",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("digest_type", sa.String(24), nullable=False, server_default="training",
                  comment="速递类型，扩展位：training=培训，将来可加 expo/meeting/review"),
        sa.Column("title", sa.String(200), nullable=False, comment="培训名称/标题"),
        sa.Column("org", sa.String(120), comment="主办机构/平台"),
        sa.Column("lecturer", sa.String(120), comment="讲师"),
        sa.Column("trained_at", sa.Date(), nullable=False, comment="培训日期"),
        sa.Column("attendees_json", sa.JSON(), comment="参训人姓名列表 [str]"),
        sa.Column("tags_json", sa.JSON(), comment="标签 [str]：平台类(TikTok/亚马逊…)+主题类(投流/选品/AI工具…)"),
        sa.Column("summary", sa.String(200), comment="一句话总结（模板★区，发布时必填）"),
        sa.Column("sections_json", sa.JSON(), comment="结构化分区内容，schema 见 app/training/schemas.py TEMPLATE_SECTIONS"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", comment="draft=草稿 published=已发布"),
        sa.Column("read_minutes", mysql.INTEGER(unsigned=True), nullable=False, server_default="0",
                  comment="预计阅读分钟，发布时按正文字数估算"),
        sa.Column("view_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0", comment="浏览次数"),
        sa.Column("useful_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0",
                  comment="「有用」计数，与 feedback 表联动"),
        sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="创建人（参训发布人）"),
        sa.Column("published_at", sa.DateTime(), comment="首次发布时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), comment="最后编辑时间，service 层维护"),
        comment="培训速递主表",
    )
    op.create_index("ix_training_digest_status", "ark_training_digests", ["status", "trained_at"])
    op.create_index("ix_training_digest_creator", "ark_training_digests", ["created_by"])

    op.create_table(
        "ark_training_digest_files",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("digest_id", BIG_ID, sa.ForeignKey("ark_training_digests.id"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False, comment="原始文件名（展示与下载命名用）"),
        sa.Column("storage_path", sa.String(500), nullable=False, comment="相对 REPO_ROOT/uploads 的存储路径"),
        sa.Column("file_size", mysql.BIGINT(unsigned=True), nullable=False, server_default="0", comment="字节数"),
        sa.Column("mime_type", sa.String(100), comment="MIME 类型"),
        sa.Column("uploaded_by", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        comment="培训速递原始资料附件；删除主表行时 service 层负责删行+清盘（不依赖 CASCADE）",
    )
    op.create_index("ix_training_file_digest", "ark_training_digest_files", ["digest_id"])

    op.create_table(
        "ark_training_digest_feedback",
        sa.Column("id", BIG_ID, primary_key=True, autoincrement=True),
        sa.Column("digest_id", BIG_ID, sa.ForeignKey("ark_training_digests.id"), nullable=False),
        sa.Column("user_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="useful", comment="反馈类型，V1 仅 useful"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("digest_id", "user_id", "kind", name="uq_training_feedback"),
        comment="培训速递轻反馈（有用），唯一约束防重复",
    )


def downgrade():
    op.drop_table("ark_training_digest_feedback")
    op.drop_table("ark_training_digest_files")
    op.drop_table("ark_training_digests")
