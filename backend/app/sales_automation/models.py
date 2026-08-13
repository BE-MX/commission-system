"""方舟智能获客 ORM 模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    DECIMAL,
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


class ResearchSubject(AuditMixin, Base):
    """统一研究主体；OKKI 公海客户不要求先拥有官网域名。"""

    __tablename__ = "ark_sales_research_subjects"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    subject_type = Column(String(32), nullable=False, comment="研究主体类型 okki_customer/lead_company")
    external_key = Column(String(160), nullable=False, unique=True, comment="跨来源稳定身份键")
    source_system = Column(String(32), nullable=False, default="okki", comment="来源系统")
    source_customer_id = Column(String(64), nullable=True, comment="来源客户ID，不建立跨库外键")
    linked_company_id = Column(
        BigInteger,
        ForeignKey("ark_sales_companies.id", ondelete="SET NULL"),
        nullable=True,
        comment="识别出官网后关联的智能获客公司ID",
    )
    display_name = Column(String(255), nullable=False, comment="客户或公司显示名称")
    country = Column(String(128), nullable=True, comment="国家或地区")
    primary_email = Column(String(320), nullable=True, comment="来源主邮箱")
    email_domain_type = Column(String(16), nullable=False, default="unknown", comment="corporate/free/unknown")
    primary_phone = Column(String(64), nullable=True, comment="来源主电话或WhatsApp")
    website = Column(String(512), nullable=True, comment="来源或核验后的官网")
    seed_tier = Column(String(16), nullable=False, comment="初筛档位 T1/T2/T3")
    eligibility_status = Column(String(16), nullable=False, default="eligible", comment="eligible/cooldown/blocked")
    completeness_score = Column(Float, nullable=False, default=0, comment="来源信息完整度0-100")
    order_count = Column(Integer, nullable=False, default=0, comment="历史有效订单数")
    order_amount_usd = Column(DECIMAL(15, 2), nullable=False, default=0, comment="历史订单金额USD")
    last_order_at = Column(DateTime, nullable=True, comment="最近历史订单日期")
    contact_snapshot = Column(JSON, nullable=False, default=dict, comment="来源联系人摘要")
    source_snapshot = Column(JSON, nullable=False, default=dict, comment="只读业务库来源快照")
    source_snapshot_hash = Column(String(64), nullable=False, comment="来源快照SHA-256")
    last_selected_at = Column(DateTime, nullable=True, comment="最近进入研究批次时间")

    linked_company = relationship("LeadCompany", lazy="noload")
    contacts = relationship("LeadContact", back_populates="subject", lazy="noload")
    research_runs = relationship("ResearchRun", back_populates="subject", lazy="noload")

    __table_args__ = (
        UniqueConstraint("source_system", "source_customer_id", name="uq_sales_subject_source_customer"),
        Index("idx_sales_subject_tier_selected", "seed_tier", "eligibility_status", "last_selected_at"),
        Index("idx_sales_subject_linked_company", "linked_company_id"),
        {"comment": "智能获客-统一研究主体"},
    )


class PublicPoolBatch(AuditMixin, Base):
    __tablename__ = "ark_sales_public_pool_batches"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_date = Column(Date, nullable=False, comment="批次业务日期")
    policy_version = Column(String(32), nullable=False, default="v1", comment="抽样策略版本")
    status = Column(String(16), nullable=False, default="pending", comment="pending/running/completed/failed")
    quota_per_tier = Column(Integer, nullable=False, default=20, comment="每档目标客户数")
    quotas = Column(JSON, nullable=False, default=dict, comment="各档目标配额")
    audit_snapshot = Column(JSON, nullable=False, default=dict, comment="生成时公海数据审计快照")
    result_counts = Column(JSON, nullable=False, default=dict, comment="各档实际选取与任务状态统计")
    idempotency_key = Column(String(96), nullable=False, unique=True, comment="批次生成幂等键")
    started_at = Column(DateTime, nullable=True, comment="生成开始时间")
    finished_at = Column(DateTime, nullable=True, comment="生成完成时间")
    error_message = Column(Text, nullable=True, comment="生成失败原因")

    tasks = relationship("PublicPoolTask", back_populates="batch", lazy="noload")

    __table_args__ = (
        Index("idx_sales_pool_batch_date_status", "batch_date", "status"),
        {"comment": "智能获客-公海每日研究批次"},
    )


class PublicPoolTask(AuditMixin, Base):
    __tablename__ = "ark_sales_public_pool_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("ark_sales_public_pool_batches.id", ondelete="CASCADE"), nullable=False, comment="所属批次ID")
    subject_id = Column(BigInteger, ForeignKey("ark_sales_research_subjects.id", ondelete="RESTRICT"), nullable=False, comment="研究主体ID")
    tier = Column(String(16), nullable=False, comment="抽样档位 T1/T2/T3")
    selection_rank = Column(Integer, nullable=False, comment="档位内抽样顺序")
    selection_reason = Column(JSON, nullable=False, default=list, comment="入选原因")
    status = Column(String(16), nullable=False, default="pending", comment="pending/running/completed/failed/skipped")
    review_status = Column(String(16), nullable=False, default="pending", comment="pending/approved/rejected")
    gate_status = Column(String(16), nullable=False, default="pending", comment="pending/passed/stopped")
    gate_snapshot = Column(JSON, nullable=True, comment="行业门控提交、哈希与是否授权深入背调")
    claimed_by = Column(String(128), nullable=True, comment="Agent标识")
    lease_token_hash = Column(String(64), nullable=True, comment="Agent租约令牌SHA-256")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约过期时间")
    attempt_count = Column(Integer, nullable=False, default=0, comment="执行次数")
    research_summary = Column(Text, nullable=True, comment="本轮研究摘要")
    error_message = Column(Text, nullable=True, comment="失败原因")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="完成时间")
    reviewed_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="审核业务员用户ID")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    opportunity_id = Column(BigInteger, ForeignKey("ark_customer_opportunities.id", ondelete="SET NULL"), nullable=True, comment="确认后生成的客户机会ID")

    batch = relationship("PublicPoolBatch", back_populates="tasks", lazy="noload")
    subject = relationship("ResearchSubject", lazy="noload")
    assessment = relationship("DealAssessment", back_populates="task", lazy="noload", uselist=False)

    __table_args__ = (
        UniqueConstraint("batch_id", "subject_id", name="uq_sales_pool_task_batch_subject"),
        Index("idx_sales_pool_task_claim", "status", "lease_expires_at", "created_at"),
        Index("idx_sales_pool_task_review", "review_status", "tier", "finished_at"),
        {"comment": "智能获客-公海客户研究任务"},
    )


class DealAssessment(AuditMixin, Base):
    __tablename__ = "ark_sales_deal_assessments"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_sales_public_pool_tasks.id", ondelete="CASCADE"), nullable=False, unique=True, comment="公海研究任务ID")
    subject_id = Column(BigInteger, ForeignKey("ark_sales_research_subjects.id", ondelete="RESTRICT"), nullable=False, comment="研究主体ID")
    grade = Column(String(4), nullable=False, comment="成交优先级 A/B/C/D")
    deal_likelihood = Column(String(16), nullable=False, comment="high/medium/low")
    evidence_confidence = Column(String(16), nullable=False, comment="high/medium/low")
    identity_decision = Column(String(24), nullable=False, comment="confirmed/candidate/unverifiable/rejected")
    business_quality_score = Column(Float, nullable=False, default=0, comment="业务质量分0-100")
    deal_score = Column(Float, nullable=False, default=0, comment="成交可能性分0-100")
    priority_score = Column(Float, nullable=False, default=0, comment="结合证据置信度后的排序分")
    score_factors = Column(JSON, nullable=False, default=dict, comment="确定性评分维度及理由")
    supplier_status = Column(String(32), nullable=False, default="unknown", comment="unknown/stable/looking/switching")
    pain_points = Column(JSON, nullable=False, default=list, comment="已证实或待核验痛点")
    product_fit = Column(JSON, nullable=False, default=list, comment="产品匹配点")
    industry_relevance = Column(String(16), nullable=False, default="uncertain", comment="core/adjacent/uncertain/irrelevant")
    industry_relevance_reason = Column(String(2000), nullable=False, default="", comment="行业门控结论与依据")
    research_depth = Column(String(16), nullable=False, default="focused", comment="gate_only/focused/deep")
    stop_reason = Column(Text, nullable=True, comment="提前停止深挖原因")
    social_profiles = Column(JSON, nullable=True, default=list, comment="社媒账号、活跃度与业务信号")
    knowledge_references = Column(JSON, nullable=True, default=list, comment="企业知识库文档版本引用")
    commercial_profile = Column(JSON, nullable=True, default=dict, comment="客户类型、采购阶段、体量和成交信号")
    recommended_strategy = Column(Text, nullable=False, comment="建议跟进策略")
    outreach_type = Column(String(32), nullable=False, comment="reactivation/new_development/intent_probe")
    opening_message_en = Column(Text, nullable=True, comment="供人工审核的英文开场草稿")
    risks = Column(JSON, nullable=False, default=list, comment="风险与待核验项")
    evidence_snapshot = Column(JSON, nullable=False, default=dict, comment="研判使用的证据引用快照")
    provider = Column(String(64), nullable=False, default="agent", comment="研判执行方")
    model = Column(String(128), nullable=True, comment="模型快照")
    assessment_version = Column(String(32), nullable=False, default="v1", comment="评分规则版本")
    completed_at = Column(DateTime, nullable=False, comment="研判完成时间")

    task = relationship("PublicPoolTask", back_populates="assessment", lazy="noload")
    subject = relationship("ResearchSubject", lazy="noload")

    __table_args__ = (
        Index("idx_sales_assessment_priority", "grade", "priority_score", "completed_at"),
        Index("idx_sales_assessment_subject", "subject_id", "completed_at"),
        {"comment": "智能获客-成交可能性研判"},
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
    company_id = Column(BigInteger, ForeignKey("ark_sales_companies.id", ondelete="CASCADE"), nullable=True, comment="候选公司ID")
    subject_id = Column(BigInteger, ForeignKey("ark_sales_research_subjects.id", ondelete="CASCADE"), nullable=True, comment="统一研究主体ID")
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
    subject = relationship("ResearchSubject", back_populates="contacts", lazy="noload")

    __table_args__ = (
        UniqueConstraint("company_id", "identity_key", name="uq_sales_contact_identity"),
        UniqueConstraint("subject_id", "identity_key", name="uq_sales_contact_subject_identity"),
        Index("idx_sales_contact_company_status", "company_id", "status"),
        Index("idx_sales_contact_email", "email_normalized"),
        {"comment": "智能获客-联系人与邮箱验证"},
    )


class ResearchRun(AuditMixin, Base):
    __tablename__ = "ark_sales_research_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    company_id = Column(BigInteger, ForeignKey("ark_sales_companies.id", ondelete="CASCADE"), nullable=True, comment="候选公司ID")
    subject_id = Column(BigInteger, ForeignKey("ark_sales_research_subjects.id", ondelete="CASCADE"), nullable=True, comment="统一研究主体ID")
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
    subject = relationship("ResearchSubject", back_populates="research_runs", lazy="noload")
    facts = relationship("ResearchFact", back_populates="run", lazy="noload")

    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_sales_research_company_idem"),
        UniqueConstraint("subject_id", "idempotency_key", name="uq_sales_research_subject_idem"),
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
