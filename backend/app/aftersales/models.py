"""客户售后管理数据模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base


USER_ID = mysql.INTEGER(unsigned=True)


class AfterSalesCase(Base):
    __tablename__ = "ark_aftersales_cases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_no = Column(String(40), nullable=False, unique=True)
    creator_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    creator_name_snapshot = Column(String(64), nullable=False)

    customer_id = Column(String(64), nullable=False)
    customer_name_snapshot = Column(String(256), nullable=False)
    customer_grade = Column(String(1), nullable=False)
    order_id = Column(String(64), nullable=False)
    order_no_snapshot = Column(String(64), nullable=False)
    purchase_date = Column(Date, nullable=False)
    feedback_date = Column(Date, nullable=False)
    feedback_channel = Column(String(32))

    product_id = Column(BigInteger)
    product_name_snapshot = Column(String(256), nullable=False)
    is_custom_product = Column(Boolean, nullable=False, default=False)
    batch_no = Column(String(128))
    color_value = Column(String(128), nullable=False)
    length_value = Column(String(128), nullable=False)
    weight_value = Column(Numeric(12, 2), nullable=False)
    weight_unit = Column(String(16), nullable=False)
    quantity = Column(Numeric(12, 2), nullable=False)

    primary_issue_type = Column(String(32), nullable=False)
    secondary_issue_types_json = Column(JSON)
    problem_description = Column(Text, nullable=False)
    occurred_stage = Column(String(32), nullable=False)
    care_storage_note = Column(Text)
    affects_end_customer = Column(String(16), nullable=False)
    affected_goods_value = Column(Numeric(15, 2), nullable=False)
    affected_goods_currency = Column(String(8), nullable=False, default="USD")

    sales_evidence_confirmed = Column(Boolean)
    sales_evidence_note = Column(Text)
    evidence_score = Column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    evidence_is_sufficient = Column(Boolean, nullable=False, default=False)
    evidence_missing_items_json = Column(JSON)
    evidence_waiver_approved = Column(Boolean, nullable=False, default=False, comment="证据不足豁免是否获批")
    evidence_waiver_reason = Column(Text, comment="业务员申请证据豁免原因")
    evidence_waiver_decision_note = Column(Text, comment="主管证据豁免意见")
    evidence_waived_by_user_id = Column(USER_ID, ForeignKey("ark_users.id"), comment="证据豁免审批人")
    evidence_waived_at = Column(DateTime, comment="证据豁免审批时间")

    responsibility_class = Column(String(1))
    responsibility_reason = Column(Text)
    responsibility_override_reason = Column(Text)
    selected_actions_json = Column(JSON)
    has_compensation = Column(Boolean, nullable=False, default=False)
    estimated_compensation_usd = Column(Numeric(15, 2), nullable=False, default=0)
    requires_return = Column(Boolean, nullable=False, default=False)
    customer_reply_draft = Column(Text)

    execution_result = Column(Text)
    customer_feedback = Column(Text)
    sop_version_id = Column(BigInteger, ForeignKey("ark_aftersales_sop_versions.id"))

    current_status = Column(String(32), nullable=False, default="draft")
    current_owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"))
    supervisor_user_id_snapshot = Column(USER_ID, ForeignKey("ark_users.id"))
    director_user_id_snapshot = Column(USER_ID, ForeignKey("ark_users.id"))
    workflow_round = Column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    version = Column(mysql.INTEGER(unsigned=True), nullable=False, default=1)

    approved_at = Column(DateTime)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)

    evidence = relationship(
        "AfterSalesEvidence", back_populates="case", lazy="noload", cascade="all, delete-orphan"
    )
    ai_runs = relationship(
        "AfterSalesAiRun", back_populates="case", lazy="noload", cascade="all, delete-orphan"
    )
    reviews = relationship(
        "AfterSalesReview", back_populates="case", lazy="noload", cascade="all, delete-orphan"
    )
    events = relationship(
        "AfterSalesEvent", back_populates="case", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_aftersales_case_creator", "creator_user_id", "current_status"),
        Index("ix_aftersales_case_owner", "current_owner_user_id", "current_status"),
        Index("ix_aftersales_case_customer", "customer_id"),
        Index("ix_aftersales_case_created", "created_at"),
        {"comment": "客户售后单"},
    )


class AfterSalesEvidence(Base):
    __tablename__ = "ark_aftersales_evidence"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(BigInteger, ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False)
    evidence_type = Column(String(32), nullable=False)
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    summary = Column(Text)
    uploaded_by_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime)

    case = relationship("AfterSalesCase", back_populates="evidence", lazy="noload")

    __table_args__ = (
        Index("ix_aftersales_evidence_case", "case_id", "evidence_type"),
        {"comment": "售后证据文件"},
    )


class AfterSalesAiRun(Base):
    __tablename__ = "ark_aftersales_ai_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(BigInteger, ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False)
    sop_version_id = Column(BigInteger, ForeignKey("ark_aftersales_sop_versions.id"), nullable=False)
    run_no = Column(mysql.INTEGER(unsigned=True), nullable=False)
    status = Column(String(24), nullable=False)
    preset_code = Column(String(64), nullable=False, default="aftersales_solution_advice")
    input_summary_json = Column(JSON)
    output_json = Column(JSON)
    model_snapshot = Column(String(128))
    duration_ms = Column(mysql.INTEGER(unsigned=True))
    error_summary = Column(String(500))
    created_by_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)

    case = relationship("AfterSalesCase", back_populates="ai_runs", lazy="noload")

    __table_args__ = (
        UniqueConstraint("case_id", "run_no", name="uq_aftersales_ai_run"),
        {"comment": "售后 AI 分析运行记录"},
    )


class AfterSalesReview(Base):
    __tablename__ = "ark_aftersales_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(BigInteger, ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False)
    workflow_round = Column(mysql.INTEGER(unsigned=True), nullable=False)
    reviewer_role = Column(String(24), nullable=False)
    reviewer_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    reviewer_name_snapshot = Column(String(64), nullable=False)
    decision = Column(String(16), nullable=False)
    remark = Column(Text, comment="审核意见")
    compensation_snapshot_json = Column(JSON)
    idempotency_key = Column(String(64), unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("AfterSalesCase", back_populates="reviews", lazy="noload")

    __table_args__ = (
        UniqueConstraint(
            "case_id", "workflow_round", "reviewer_role", name="uq_aftersales_review_round_role"
        ),
        {"comment": "售后审核记录"},
    )


class AfterSalesEvent(Base):
    __tablename__ = "ark_aftersales_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(BigInteger, ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=True)
    event_type = Column(String(32), nullable=False)
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id"))
    actor_name_snapshot = Column(String(64))
    workflow_round = Column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    detail_json = Column(JSON)
    idempotency_key = Column(String(64), unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("AfterSalesCase", back_populates="events", lazy="noload")

    __table_args__ = (
        Index("ix_aftersales_event_case", "case_id", "created_at"),
        {"comment": "售后不可变审计事件"},
    )


class AfterSalesSopVersion(Base):
    __tablename__ = "ark_aftersales_sop_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    version_no = Column(String(40), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=False)
    change_summary = Column(Text, nullable=False)
    effective_date = Column(Date, nullable=False)
    parse_status = Column(String(24), nullable=False, default="pending")
    structured_content_json = Column(JSON)
    issue_mapping_json = Column(JSON)
    clause_count = Column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=False)
    activated_at = Column(DateTime)
    uploaded_by_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_aftersales_sop_active", "is_active"),
        {"comment": "售后 SOP 版本"},
    )


class AfterSalesNotificationLog(Base):
    __tablename__ = "ark_aftersales_notification_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(BigInteger, ForeignKey("ark_aftersales_cases.id", ondelete="CASCADE"), nullable=False)
    business_event_key = Column(String(128), nullable=False)
    recipient_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False)
    recipient_dingtalk_id = Column(String(100), nullable=True)
    template_code = Column(String(64), nullable=False)
    payload_json = Column(JSON)
    status = Column(String(16), nullable=False, default="pending")
    attempt_count = Column(mysql.INTEGER(unsigned=True), nullable=False, default=0)
    next_retry_at = Column(DateTime)
    last_error_summary = Column(String(500))
    sent_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "business_event_key",
            "recipient_user_id",
            name="uq_aftersales_notify_event_recipient",
        ),
        Index("ix_aftersales_notify_retry", "status", "next_retry_at"),
        {"comment": "售后钉钉通知日志"},
    )
