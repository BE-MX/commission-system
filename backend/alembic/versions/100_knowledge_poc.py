"""Native knowledge base POC.

Revision ID: 100_knowledge_poc
Revises: 099_sales_automation
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "100_knowledge_poc"
down_revision = "099_sales_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_knowledge_libraries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="企业知识库",
    )
    op.create_table(
        "ark_knowledge_library_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["ark_knowledge_libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_id", "user_id", name="uq_knowledge_member_library_user"),
        comment="知识库成员ACL",
    )
    op.create_index("idx_knowledge_member_user", "ark_knowledge_library_members", ["user_id", "library_id"])
    op.create_table(
        "ark_knowledge_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("node_type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("draft_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("published_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("pending_approval_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["library_id"], ["ark_knowledge_libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["ark_knowledge_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库目录与文档",
    )
    op.create_index("idx_knowledge_document_tree", "ark_knowledge_documents", ["library_id", "parent_id", "sort_order"])
    op.create_table(
        "ark_knowledge_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["ark_knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_no", name="uq_knowledge_revision_document_version"),
        comment="不可变知识文档修订",
    )
    op.create_index("idx_knowledge_revision_document", "ark_knowledge_revisions", ["document_id", "created_at"])
    op.create_table(
        "ark_knowledge_approval_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pending_slot", sa.Integer(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("remark", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["ark_knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["ark_knowledge_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "pending_slot", name="uq_knowledge_approval_pending"),
        comment="知识文档审批请求",
    )
    op.create_index("idx_knowledge_approval_status", "ark_knowledge_approval_requests", ["status", "created_at"])
    op.create_table(
        "ark_knowledge_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(16), nullable=False),
        sa.Column("object_id", sa.BigInteger(), nullable=True),
        sa.Column("revision_id", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库安全审计日志",
    )
    op.create_index("idx_knowledge_audit_library_time", "ark_knowledge_audit_logs", ["library_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_knowledge_audit_library_time", table_name="ark_knowledge_audit_logs")
    op.drop_table("ark_knowledge_audit_logs")
    op.drop_index("idx_knowledge_approval_status", table_name="ark_knowledge_approval_requests")
    op.drop_table("ark_knowledge_approval_requests")
    op.drop_index("idx_knowledge_revision_document", table_name="ark_knowledge_revisions")
    op.drop_table("ark_knowledge_revisions")
    op.drop_index("idx_knowledge_document_tree", table_name="ark_knowledge_documents")
    op.drop_table("ark_knowledge_documents")
    op.drop_index("idx_knowledge_member_user", table_name="ark_knowledge_library_members")
    op.drop_table("ark_knowledge_library_members")
    op.drop_table("ark_knowledge_libraries")
