"""SQLAlchemy models for the native knowledge base."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.ai.models import AiCallLog, AiPreset  # noqa: F401 -- register FK targets
from app.core.database import Base


def bj_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


class KnowledgeLibrary(Base):
    __tablename__ = "ark_knowledge_libraries"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(128), nullable=False, comment="知识库名称")
    description = Column(String(512), nullable=True, comment="用途说明")
    category = Column(String(16), nullable=False, comment="company/department/personal")
    status = Column(String(16), nullable=False, default="active", comment="active/archived")
    created_by = Column(Integer, nullable=False, comment="创建人用户ID")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")


class KnowledgeLibraryMember(Base):
    __tablename__ = "ark_knowledge_library_members"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    library_id = Column(BigInteger, ForeignKey("ark_knowledge_libraries.id", ondelete="CASCADE"), nullable=False, comment="知识库ID")
    user_id = Column(Integer, nullable=False, comment="方舟用户ID")
    role = Column(String(16), nullable=False, comment="viewer/editor/reviewer/admin")
    created_by = Column(Integer, nullable=False, comment="配置人用户ID")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("library_id", "user_id", name="uq_knowledge_member_library_user"),
        Index("idx_knowledge_member_user", "user_id", "library_id"),
    )


class KnowledgeDocument(Base):
    __tablename__ = "ark_knowledge_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    library_id = Column(BigInteger, ForeignKey("ark_knowledge_libraries.id", ondelete="CASCADE"), nullable=False, comment="知识库ID")
    parent_id = Column(BigInteger, ForeignKey("ark_knowledge_documents.id", ondelete="RESTRICT"), nullable=True, comment="父目录ID")
    node_type = Column(String(16), nullable=False, default="document", comment="folder/document")
    title = Column(String(256), nullable=False, comment="节点标题")
    sort_order = Column(Integer, nullable=False, default=0, comment="同级排序")
    status = Column(String(16), nullable=False, default="draft", comment="draft/pending/published")
    draft_revision_id = Column(BigInteger, nullable=True, comment="当前草稿修订ID")
    published_revision_id = Column(BigInteger, nullable=True, comment="线上发布修订ID")
    pending_approval_id = Column(BigInteger, nullable=True, comment="当前待审请求ID")
    created_by = Column(Integer, nullable=False, comment="创建人用户ID")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        Index("idx_knowledge_document_tree", "library_id", "parent_id", "sort_order"),
    )


class KnowledgeRevision(Base):
    __tablename__ = "ark_knowledge_revisions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    document_id = Column(BigInteger, ForeignKey("ark_knowledge_documents.id", ondelete="CASCADE"), nullable=False, comment="文档ID")
    version_no = Column(Integer, nullable=False, comment="文档内自增版本号")
    title = Column(String(256), nullable=False, comment="标题快照")
    content_json = Column(JSON, nullable=False, comment="Tiptap JSON事实源")
    content_text = Column(Text, nullable=False, comment="搜索与Agent纯文本")
    created_by = Column(Integer, nullable=False, comment="作者用户ID")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_knowledge_revision_document_version"),
        Index("idx_knowledge_revision_document", "document_id", "created_at"),
    )


class KnowledgeApprovalRequest(Base):
    __tablename__ = "ark_knowledge_approval_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    document_id = Column(BigInteger, ForeignKey("ark_knowledge_documents.id", ondelete="CASCADE"), nullable=False, comment="文档ID")
    revision_id = Column(BigInteger, ForeignKey("ark_knowledge_revisions.id", ondelete="RESTRICT"), nullable=False, comment="冻结待审修订ID")
    status = Column(String(16), nullable=False, default="pending", comment="pending/approved/rejected/cancelled")
    pending_slot = Column(Integer, nullable=True, default=1, comment="待审唯一槽位，终态为NULL")
    submitted_by = Column(Integer, nullable=False, comment="提交人用户ID")
    reviewed_by = Column(Integer, nullable=True, comment="审核人用户ID")
    remark = Column(String(512), nullable=True, comment="审批意见或驳回原因")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="提交时间")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")

    __table_args__ = (
        UniqueConstraint("document_id", "pending_slot", name="uq_knowledge_approval_pending"),
        Index("idx_knowledge_approval_status", "status", "created_at"),
    )


class KnowledgeAuditLog(Base):
    __tablename__ = "ark_knowledge_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    library_id = Column(BigInteger, nullable=False, comment="知识库ID快照")
    actor_user_id = Column(Integer, nullable=False, comment="操作人用户ID")
    action = Column(String(32), nullable=False, comment="动作代码")
    object_type = Column(String(16), nullable=False, comment="对象类型")
    object_id = Column(BigInteger, nullable=True, comment="对象ID")
    revision_id = Column(BigInteger, nullable=True, comment="关联修订ID")
    detail = Column(JSON, nullable=True, comment="结构化附加信息")
    created_at = Column(DateTime, nullable=False, default=bj_now, comment="发生时间")

    __table_args__ = (Index("idx_knowledge_audit_library_time", "library_id", "created_at"),)


class KnowledgeAsset(Base):
    __tablename__ = "ark_knowledge_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    library_id = Column(BigInteger, ForeignKey("ark_knowledge_libraries.id", ondelete="CASCADE"), nullable=False)
    storage_path = Column(String(512), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="temporary", comment="temporary/attached")
    created_by = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=bj_now)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_kn_asset_library_created", "library_id", "created_at"),
        Index("idx_kn_asset_expiry", "status", "expires_at"),
    )


class KnowledgeRevisionAsset(Base):
    __tablename__ = "ark_knowledge_revision_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    revision_id = Column(BigInteger, ForeignKey("ark_knowledge_revisions.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(BigInteger, ForeignKey("ark_knowledge_assets.id", ondelete="RESTRICT"), nullable=False)
    position = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("revision_id", "asset_id", name="uq_kn_rev_asset"),
        Index("idx_kn_rev_asset_asset", "asset_id", "revision_id"),
    )


class KnowledgeAiProfile(Base):
    __tablename__ = "ark_knowledge_ai_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(String(512), nullable=True)
    preset_id = Column(Integer, ForeignKey("ark_ai_presets.id", ondelete="RESTRICT"), nullable=False)
    format_prompt = Column(Text, nullable=True)
    enhance_prompt = Column(Text, nullable=True)
    retrieval_limit = Column(Integer, nullable=False, default=5)
    context_char_limit = Column(Integer, nullable=False, default=30000)
    allow_cross_library = Column(Boolean, nullable=False, default=False)
    require_citations = Column(Boolean, nullable=False, default=True)
    max_document_chars = Column(Integer, nullable=False, default=30000)
    daily_limit = Column(Integer, nullable=False, default=20)
    max_concurrent_per_user = Column(Integer, nullable=False, default=2)
    config_version = Column(Integer, nullable=False, default=1)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=bj_now)
    updated_at = Column(DateTime, nullable=False, default=bj_now, onupdate=bj_now)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("idx_kn_ai_profile_enabled", "is_enabled", "deleted_at"),)


class KnowledgeAiProfileSource(Base):
    __tablename__ = "ark_knowledge_ai_profile_sources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("ark_knowledge_ai_profiles.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(BigInteger, ForeignKey("ark_knowledge_libraries.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "library_id", name="uq_kn_ai_src"),
        Index("idx_kn_ai_src_library", "library_id", "profile_id"),
    )


class KnowledgeAiProfileLog(Base):
    __tablename__ = "ark_knowledge_ai_profile_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("ark_knowledge_ai_profiles.id", ondelete="CASCADE"), nullable=False)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(16), nullable=False)
    config_version = Column(Integer, nullable=False)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=bj_now)

    __table_args__ = (Index("idx_kn_ai_profile_log", "profile_id", "created_at"),)


class KnowledgeAiProfileTarget(Base):
    __tablename__ = "ark_knowledge_ai_profile_targets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("ark_knowledge_ai_profiles.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(BigInteger, ForeignKey("ark_knowledge_libraries.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "library_id", name="uq_kn_ai_tgt"),
        Index("idx_kn_ai_tgt_library", "library_id", "profile_id"),
    )


class KnowledgeAiJob(Base):
    __tablename__ = "ark_knowledge_ai_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id = Column(BigInteger, ForeignKey("ark_knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    base_revision_id = Column(BigInteger, ForeignKey("ark_knowledge_revisions.id", ondelete="RESTRICT"), nullable=False)
    owner_user_id = Column(Integer, nullable=False)
    profile_id = Column(BigInteger, ForeignKey("ark_knowledge_ai_profiles.id", ondelete="RESTRICT"), nullable=False)
    mode = Column(String(16), nullable=False, comment="format/enhance")
    status = Column(String(16), nullable=False, default="queued")
    idempotency_key = Column(String(64), nullable=False)
    config_snapshot = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=True)
    comparison_json = Column(JSON, nullable=True)
    ai_call_log_id = Column(BigInteger, ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), nullable=True)
    applied_revision_id = Column(BigInteger, ForeignKey("ark_knowledge_revisions.id", ondelete="RESTRICT"), nullable=True)
    claimed_by = Column(String(128), nullable=True)
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    claim_count = Column(Integer, nullable=False, default=0)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=bj_now)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_kn_ai_job_owner_idem"),
        Index("idx_kn_ai_job_claim", "status", "lease_expires_at", "created_at"),
        Index("idx_kn_ai_job_doc_created", "document_id", "created_at"),
        Index("idx_kn_ai_job_owner_created", "owner_user_id", "created_at", "status"),
    )


class KnowledgeAiJobSource(Base):
    __tablename__ = "ark_knowledge_ai_job_sources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, ForeignKey("ark_knowledge_ai_jobs.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(BigInteger, nullable=False)
    document_id = Column(BigInteger, nullable=False)
    revision_id = Column(BigInteger, ForeignKey("ark_knowledge_revisions.id", ondelete="RESTRICT"), nullable=False)
    title_snapshot = Column(String(256), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    position = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "revision_id", name="uq_kn_ai_job_source"),
        Index("idx_kn_ai_job_source_pos", "job_id", "position"),
    )
