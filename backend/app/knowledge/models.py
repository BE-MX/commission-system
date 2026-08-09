"""SQLAlchemy models for the native knowledge base."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.core.database import Base


def bj_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


class KnowledgeLibrary(Base):
    __tablename__ = "ark_knowledge_libraries"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(128), nullable=False, comment="知识库名称")
    description = Column(String(512), nullable=True, comment="用途说明")
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
    status = Column(String(16), nullable=False, default="pending", comment="pending/approved/rejected")
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
