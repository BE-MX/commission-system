"""方舟智能获客 ORM 模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects import mysql

from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class AuditMixin:
    created_by = Column(USER_ID, nullable=True, comment="创建人用户ID")
    updated_by = Column(USER_ID, nullable=True, comment="最后更新人用户ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")


class AcquisitionProfile(AuditMixin, Base):
    __tablename__ = "ark_sales_target_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_key = Column(String(64), nullable=False, default="default", unique=True, comment="画像业务键")
    company_name = Column(String(255), nullable=False, comment="本公司名称")
    company_website = Column(String(512), nullable=True, comment="本公司官网")
    products = Column(JSON, nullable=False, comment="产品能力列表")
    advantages = Column(JSON, nullable=False, comment="竞争优势列表")
    target_countries = Column(JSON, nullable=False, comment="目标国家列表")
    target_industries = Column(JSON, nullable=False, comment="目标行业列表")
    target_roles = Column(JSON, nullable=False, comment="目标联系人角色列表")
    exclusions = Column(JSON, nullable=False, comment="排除条件列表")
    default_language = Column(String(16), nullable=False, default="en", comment="默认开发语言")
    status = Column(String(16), nullable=False, default="active", comment="画像状态 active/inactive")

    __table_args__ = (
        Index("idx_sales_profile_status", "status"),
        {"comment": "智能获客-目标客户模型"},
    )


class SearchJob(AuditMixin, Base):
    __tablename__ = "ark_sales_search_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_id = Column(BigInteger, ForeignKey("ark_sales_target_profiles.id", ondelete="RESTRICT"), nullable=False, comment="目标客户模型ID")
    name = Column(String(255), nullable=False, comment="搜索任务名称")
    status = Column(String(16), nullable=False, default="pending", comment="pending/running/completed/failed")
    adapter = Column(String(64), nullable=False, default="agent", comment="搜索适配器 agent/apollo/import")
    target_count = Column(Integer, nullable=False, default=20, comment="目标公司数量")
    criteria = Column(JSON, nullable=False, comment="用户补充搜索条件")
    profile_snapshot = Column(JSON, nullable=False, comment="创建任务时画像快照")
    idempotency_key = Column(String(64), nullable=True, unique=True, comment="创建任务幂等键")
    ingestion_receipts = Column(JSON, nullable=False, default=dict, comment="Agent批次幂等回执")
    result_count = Column(Integer, nullable=False, default=0, comment="原始候选数")
    created_count = Column(Integer, nullable=False, default=0, comment="新建公司数")
    deduplicated_count = Column(Integer, nullable=False, default=0, comment="去重公司数")
    error_code = Column(String(64), nullable=True, comment="失败代码")
    error_message = Column(Text, nullable=True, comment="可行动失败原因")
    claimed_by = Column(String(128), nullable=True, comment="Agent标识")
    lease_token_hash = Column(String(64), nullable=True, comment="Agent租约令牌SHA-256")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约过期时间")
    attempt_count = Column(Integer, nullable=False, default=0, comment="执行次数")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")

    profile = relationship("AcquisitionProfile", lazy="noload")
    results = relationship("SearchResult", back_populates="job", lazy="noload")

    __table_args__ = (
        Index("idx_sales_job_claim", "status", "lease_expires_at", "created_at"),
        {"comment": "智能获客-Agent搜索任务"},
    )


class LeadCompany(AuditMixin, Base):
    __tablename__ = "ark_sales_companies"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    normalized_domain = Column(String(253), nullable=False, unique=True, comment="归一化官网域名")
    name = Column(String(255), nullable=False, comment="公司名称")
    website = Column(String(512), nullable=False, comment="公司官网")
    country = Column(String(128), nullable=True, comment="国家或地区")
    industry = Column(String(255), nullable=True, comment="行业")
    description = Column(Text, nullable=True, comment="公司简介")
    status = Column(String(16), nullable=False, default="candidate", comment="candidate/approved/rejected")
    match_score = Column(Float, nullable=False, default=0, comment="目标画像匹配分0-100")
    score_reasons = Column(JSON, nullable=False, default=list, comment="可解释评分理由")
    owner_user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="确认后的负责人用户ID",
    )
    approved_at = Column(DateTime, nullable=True, comment="确认进入客户池时间")

    results = relationship("SearchResult", back_populates="company", lazy="noload")
    contacts = relationship("LeadContact", back_populates="company", lazy="noload")
    research_runs = relationship("ResearchRun", back_populates="company", lazy="noload")

    __table_args__ = (
        Index("idx_sales_company_status_score", "status", "match_score"),
        {"comment": "智能获客-候选公司主档"},
    )


class SearchResult(AuditMixin, Base):
    __tablename__ = "ark_sales_search_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    job_id = Column(BigInteger, ForeignKey("ark_sales_search_jobs.id", ondelete="CASCADE"), nullable=False, comment="搜索任务ID")
    company_id = Column(BigInteger, ForeignKey("ark_sales_companies.id", ondelete="RESTRICT"), nullable=False, comment="候选公司ID")
    request_key = Column(String(64), nullable=False, comment="Agent提交批次键")
    source_provider = Column(String(64), nullable=False, default="agent", comment="来源适配器")
    source_url = Column(String(1024), nullable=False, comment="发现证据URL")
    captured_at = Column(DateTime, nullable=False, comment="来源采集时间")
    raw_payload = Column(JSON, nullable=True, comment="原始候选数据快照")
    rank = Column(Integer, nullable=True, comment="在本次搜索中的排名")
    score = Column(Float, nullable=False, default=0, comment="本次搜索匹配分")
    status = Column(String(16), nullable=False, default="active", comment="结果状态 active/ignored")

    job = relationship("SearchJob", back_populates="results", lazy="noload")
    company = relationship("LeadCompany", back_populates="results", lazy="noload")

    __table_args__ = (
        UniqueConstraint("job_id", "company_id", name="uq_sales_result_job_company"),
        Index("idx_sales_result_job_rank", "job_id", "rank"),
        Index("idx_sales_result_company_created", "company_id", "created_at"),
        {"comment": "智能获客-搜索任务结果与来源快照"},
    )


class LeadContact(AuditMixin, Base):
    __tablename__ = "ark_sales_contacts"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    company_id = Column(BigInteger, ForeignKey("ark_sales_companies.id", ondelete="CASCADE"), nullable=False, comment="候选公司ID")
    identity_key = Column(String(64), nullable=False, comment="公司范围内联系人身份哈希")
    name = Column(String(255), nullable=True, comment="联系人姓名")
    role = Column(String(255), nullable=True, comment="联系人职位")
    email = Column(String(320), nullable=True, comment="原始邮箱")
    email_normalized = Column(String(320), nullable=True, comment="归一化邮箱")
    email_status = Column(String(16), nullable=False, default="unknown", comment="unknown/valid/risky/invalid")
    verified_at = Column(DateTime, nullable=True, comment="邮箱验证时间")
    source_provider = Column(String(64), nullable=False, default="agent", comment="来源适配器")
    source_url = Column(String(1024), nullable=False, comment="联系人证据URL")
    captured_at = Column(DateTime, nullable=False, comment="来源采集时间")
    confidence = Column(Float, nullable=True, comment="来源置信度0-1")
    status = Column(String(16), nullable=False, default="active", comment="联系人状态 active/inactive")

    company = relationship("LeadCompany", back_populates="contacts", lazy="noload")

    __table_args__ = (
        UniqueConstraint("company_id", "identity_key", name="uq_sales_contact_identity"),
        Index("idx_sales_contact_company_status", "company_id", "status"),
        Index("idx_sales_contact_email", "email_normalized"),
        {"comment": "智能获客-联系人与邮箱验证"},
    )


class ResearchRun(AuditMixin, Base):
    __tablename__ = "ark_sales_research_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    company_id = Column(BigInteger, ForeignKey("ark_sales_companies.id", ondelete="CASCADE"), nullable=False, comment="候选公司ID")
    status = Column(String(16), nullable=False, default="pending", comment="pending/running/completed/failed")
    summary = Column(Text, nullable=True, comment="企业研究摘要")
    outreach_angles = Column(JSON, nullable=False, default=list, comment="建议触达角度")
    risks = Column(JSON, nullable=False, default=list, comment="风险与待核验项")
    provider = Column(String(64), nullable=False, default="agent", comment="研究执行方")
    model = Column(String(128), nullable=True, comment="模型快照")
    idempotency_key = Column(String(64), nullable=True, comment="公司范围内研究幂等键")
    error_message = Column(Text, nullable=True, comment="失败原因")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")

    company = relationship("LeadCompany", back_populates="research_runs", lazy="noload")
    facts = relationship("ResearchFact", back_populates="run", lazy="noload")

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_sales_research_company_idem"),
        Index("idx_sales_research_company_status", "company_id", "status", "created_at"),
        {"comment": "智能获客-Agent企业研究执行"},
    )


class ResearchFact(AuditMixin, Base):
    __tablename__ = "ark_sales_research_facts"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    run_id = Column(BigInteger, ForeignKey("ark_sales_research_runs.id", ondelete="CASCADE"), nullable=False, comment="研究执行ID")
    fact_type = Column(String(64), nullable=False, default="general", comment="事实类型")
    claim = Column(Text, nullable=False, comment="结构化事实陈述")
    fact_hash = Column(String(64), nullable=False, comment="事实内容哈希")
    source_url = Column(String(1024), nullable=False, comment="事实来源URL")
    source_url_hash = Column(String(64), nullable=False, comment="来源URL哈希")
    captured_at = Column(DateTime, nullable=False, comment="来源采集时间")
    confidence = Column(Float, nullable=False, comment="置信度0-1")
    sort_order = Column(Integer, nullable=False, default=0, comment="展示顺序")
    status = Column(String(16), nullable=False, default="active", comment="事实状态 active/disputed")

    run = relationship("ResearchRun", back_populates="facts", lazy="noload")

    __table_args__ = (
        UniqueConstraint("run_id", "fact_hash", "source_url_hash", name="uq_sales_fact_source"),
        Index("idx_sales_fact_run_sort", "run_id", "sort_order"),
        {"comment": "智能获客-可追溯企业研究事实"},
    )
