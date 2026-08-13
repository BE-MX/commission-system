"""Add private knowledge images and governed AI optimization.

Revision ID: 112_knowledge_editor_ai
Revises: 111_runtime_observability
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "112_knowledge_editor_ai"
down_revision = "111_runtime_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_knowledge_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["library_id"], ["ark_knowledge_libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="企业知识库私有图片",
    )
    op.create_index("idx_kn_asset_library_created", "ark_knowledge_assets", ["library_id", "created_at"])
    op.create_index("idx_kn_asset_expiry", "ark_knowledge_assets", ["status", "expires_at"])

    op.create_table(
        "ark_knowledge_revision_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["ark_knowledge_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ark_knowledge_revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision_id", "asset_id", name="uq_kn_rev_asset"),
        comment="知识修订图片冻结引用",
    )
    op.create_index("idx_kn_rev_asset_asset", "ark_knowledge_revision_assets", ["asset_id", "revision_id"])

    op.create_table(
        "ark_knowledge_ai_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("preset_id", sa.Integer(), nullable=False),
        sa.Column("format_prompt", sa.Text(), nullable=True),
        sa.Column("enhance_prompt", sa.Text(), nullable=True),
        sa.Column("retrieval_limit", sa.Integer(), nullable=False),
        sa.Column("context_char_limit", sa.Integer(), nullable=False),
        sa.Column("allow_cross_library", sa.Boolean(), nullable=False),
        sa.Column("require_citations", sa.Boolean(), nullable=False),
        sa.Column("max_document_chars", sa.Integer(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("max_concurrent_per_user", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["preset_id"], ["ark_ai_presets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库 AI 优化配置",
    )
    op.create_index("idx_kn_ai_profile_enabled", "ark_knowledge_ai_profiles", ["is_enabled", "deleted_at"])

    op.create_table(
        "ark_knowledge_ai_profile_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["profile_id"], ["ark_knowledge_ai_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="知识库 AI 优化配置变更审计",
    )
    op.create_index("idx_kn_ai_profile_log", "ark_knowledge_ai_profile_logs", ["profile_id", "created_at"])

    for table_name, comment in (
        ("ark_knowledge_ai_profile_sources", "AI 优化配置允许的来源知识库"),
        ("ark_knowledge_ai_profile_targets", "AI 优化配置适用的目标知识库"),
    ):
        op.create_table(
            table_name,
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("profile_id", sa.BigInteger(), nullable=False),
            sa.Column("library_id", sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(["library_id"], ["ark_knowledge_libraries.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["profile_id"], ["ark_knowledge_ai_profiles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("profile_id", "library_id", name=f"uq_{'kn_ai_src' if table_name.endswith('sources') else 'kn_ai_tgt'}"),
            comment=comment,
        )
        op.create_index(
            f"idx_{'kn_ai_src' if table_name.endswith('sources') else 'kn_ai_tgt'}_library",
            table_name,
            ["library_id", "profile_id"],
        )

    op.create_table(
        "ark_knowledge_ai_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("base_revision_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("comparison_json", sa.JSON(), nullable=True),
        sa.Column("ai_call_log_id", sa.BigInteger(), nullable=True),
        sa.Column("verification_ai_call_log_id", sa.BigInteger(), nullable=True, comment="独立语义审计 AI 调用日志"),
        sa.Column("applied_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["ai_call_log_id"], ["ark_ai_call_logs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["verification_ai_call_log_id"], ["ark_ai_call_logs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["applied_revision_id"], ["ark_knowledge_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_revision_id"], ["ark_knowledge_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["ark_knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["ark_knowledge_ai_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_kn_ai_job_owner_idem"),
        comment="知识文档 AI 优化任务",
    )
    op.create_index("idx_kn_ai_job_claim", "ark_knowledge_ai_jobs", ["status", "lease_expires_at", "created_at"])
    op.create_index("idx_kn_ai_job_doc_created", "ark_knowledge_ai_jobs", ["document_id", "created_at"])
    op.create_index("idx_kn_ai_job_owner_created", "ark_knowledge_ai_jobs", ["owner_user_id", "created_at", "status"])

    op.create_table(
        "ark_knowledge_ai_job_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_id", sa.BigInteger(), nullable=False),
        sa.Column("title_snapshot", sa.String(length=256), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["ark_knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["ark_knowledge_ai_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["library_id"], ["ark_knowledge_libraries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_id"], ["ark_knowledge_revisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "revision_id", name="uq_kn_ai_job_source"),
        comment="AI 优化任务冻结来源修订",
    )
    op.create_index("idx_kn_ai_job_source_pos", "ark_knowledge_ai_job_sources", ["job_id", "position"])


def downgrade() -> None:
    op.drop_index("idx_kn_ai_job_source_pos", table_name="ark_knowledge_ai_job_sources")
    op.drop_table("ark_knowledge_ai_job_sources")
    op.drop_index("idx_kn_ai_job_owner_created", table_name="ark_knowledge_ai_jobs")
    op.drop_index("idx_kn_ai_job_doc_created", table_name="ark_knowledge_ai_jobs")
    op.drop_index("idx_kn_ai_job_claim", table_name="ark_knowledge_ai_jobs")
    op.drop_table("ark_knowledge_ai_jobs")
    op.drop_index("idx_kn_ai_tgt_library", table_name="ark_knowledge_ai_profile_targets")
    op.drop_table("ark_knowledge_ai_profile_targets")
    op.drop_index("idx_kn_ai_src_library", table_name="ark_knowledge_ai_profile_sources")
    op.drop_table("ark_knowledge_ai_profile_sources")
    op.drop_index("idx_kn_ai_profile_enabled", table_name="ark_knowledge_ai_profiles")
    op.drop_index("idx_kn_ai_profile_log", table_name="ark_knowledge_ai_profile_logs")
    op.drop_table("ark_knowledge_ai_profile_logs")
    op.drop_table("ark_knowledge_ai_profiles")
    op.drop_index("idx_kn_rev_asset_asset", table_name="ark_knowledge_revision_assets")
    op.drop_table("ark_knowledge_revision_assets")
    op.drop_index("idx_kn_asset_expiry", table_name="ark_knowledge_assets")
    op.drop_index("idx_kn_asset_library_created", table_name="ark_knowledge_assets")
    op.drop_table("ark_knowledge_assets")
