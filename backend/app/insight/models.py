"""方舟洞见 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import LONGTEXT, MEDIUMTEXT
from sqlalchemy.orm import relationship

from app.core.database import Base


# ── 报告主表 ────────────────────────────────────────────
class InsightReport(Base):
    __tablename__ = "ark_insight_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(
        Enum(
            "industry_daily",
            "ai_tools",
            "shop_analysis",
            "competitor_analysis",
            "inquiry_analysis",
            "intelligence_overview",
            name="insight_report_type",
        ),
        nullable=False,
    )
    report_date = Column(Date, nullable=False)
    title = Column(String(255), nullable=False, default="")
    html_content = Column(LONGTEXT, nullable=True)
    file_path = Column(String(512), nullable=True)
    source_data = Column(JSON, nullable=True)
    report_metadata = Column(JSON, nullable=True)
    status = Column(
        Enum("pending", "published", "failed", "generating", "completed", name="insight_report_status"),
        nullable=False,
        default="pending",
    )
    error_msg = Column(Text, nullable=True)
    created_by = Column(Integer, nullable=True)
    # 情报速览扩展字段
    date_range_start = Column(Date, nullable=True)
    date_range_end = Column(Date, nullable=True)
    item_ids = Column(JSON, nullable=True)
    config_snapshot = Column(JSON, nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False)
    trigger_type = Column(String(32), nullable=False, default="manual")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_insight_report_date", "report_date"),
        Index("idx_insight_report_status", "status"),
        Index("idx_insight_report_created_at", "created_at"),
        Index("idx_insight_report_type_date", "report_type", "report_date"),
    )


# ── 信源配置表 ────────────────────────────────────────────
class InsightSource(Base):
    __tablename__ = "ark_insight_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    source_type = Column(
        Enum(
            "google_alerts_rss",
            "pinterest_scrape",
            "google_trends_rss",
            "amazon_bestseller",
            "competitor_rss",
            "competitor_html",
            "aihot_api",
            "xpoz",
            "competitor_monitor",
            "perplexity",
            "amazon",
            "manual",
            name="insight_source_type",
        ),
        nullable=False,
    )
    url = Column(String(1024), nullable=False)
    keywords = Column(JSON, nullable=True)
    exclude_keywords = Column(JSON, nullable=True)
    css_selector = Column(String(512), nullable=True)
    request_headers = Column(JSON, nullable=True)
    proxy_url = Column(String(255), nullable=True)
    config_json = Column(JSON, nullable=True)
    fetch_interval_hours = Column(SmallInteger, nullable=False, default=24)
    last_fetched_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    consecutive_failures = Column(SmallInteger, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    pipeline = Column(
        Enum("external", "internal", name="insight_source_pipeline"),
        nullable=False,
        default="external",
    )
    sort_order = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_insight_source_type", "source_type"),
        Index("idx_insight_source_is_active", "is_active"),
        Index("idx_insight_source_pipeline", "pipeline"),
    )


# ── 案例库 ────────────────────────────────────────────
class InsightCase(Base):
    __tablename__ = "ark_case_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, default="")
    scenario = Column(Text, nullable=True)
    what_was_done = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    customer_name = Column(String(200), nullable=True)
    tags = Column(JSON, nullable=True)
    attachments = Column(JSON, nullable=True)
    highlights = Column(JSON, nullable=True)
    customer_type = Column(String(50), nullable=True)
    market = Column(String(50), nullable=True)
    product_type = Column(String(50), nullable=True)
    key_phrases = Column(JSON, nullable=True)
    raw_summary = Column(Text, nullable=True)

    # ── SKILL-based 扩展字段 ──────────────────────
    customer_country = Column(String(50), nullable=True)
    communication_channel = Column(String(50), nullable=True)
    communication_period = Column(String(100), nullable=True)
    total_rounds = Column(SmallInteger, nullable=True)
    final_result = Column(String(50), nullable=True)
    background_check_status = Column(String(50), nullable=True)
    rounds_analysis = Column(JSON, nullable=True)
    dimension_scores = Column(JSON, nullable=True)
    golden_phrases = Column(JSON, nullable=True)
    red_flags = Column(JSON, nullable=True)
    core_strengths = Column(JSON, nullable=True)
    result_analysis = Column(JSON, nullable=True)
    improvements = Column(JSON, nullable=True)
    next_actions = Column(JSON, nullable=True)
    ai_draft = Column(JSON, nullable=True)
    user_corrections = Column(JSON, nullable=True)

    original_content = Column(MEDIUMTEXT, nullable=True)
    source_type = Column(
        Enum("screenshot", "text_paste", "manual", name="insight_case_source_type"),
        nullable=False,
        default="manual",
    )
    image_path = Column(String(512), nullable=True)
    share_person = Column(String(50), nullable=False, default="")
    share_date = Column(Date, nullable=True)
    uploaded_by = Column(Integer, nullable=False)
    status = Column(
        Enum("draft", "published", "archived", "processing", "failed", name="insight_case_status"),
        nullable=False,
        default="draft",
    )
    error_msg = Column(Text, nullable=True)
    like_count = Column(Integer, nullable=False, default=0)
    view_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── 周会纪要 ────────────────────────────────────────────
class MeetingMinutes(Base):
    __tablename__ = "ark_meeting_minutes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_date = Column(Date, nullable=False)
    title = Column(String(200), nullable=False, default="")
    duration = Column(String(20), nullable=True)
    participants = Column(String(500), nullable=True)
    original_text = Column(LONGTEXT, nullable=False)
    summary_md = Column(MEDIUMTEXT, nullable=True)
    structured_summary = Column(JSON, nullable=True)
    tasks_json = Column(JSON, nullable=True)
    source_url = Column(String(512), nullable=True)
    has_attachment = Column(Boolean, nullable=False, default=False)
    word_count_original = Column(Integer, nullable=True)
    word_count_summary = Column(Integer, nullable=True)
    status = Column(
        Enum("processing", "published", "failed", name="insight_minutes_status"),
        nullable=False,
        default="processing",
    )
    error_msg = Column(Text, nullable=True)
    uploaded_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship(
        "InsightTask",
        back_populates="minutes",
        cascade="all, delete-orphan",
        order_by="InsightTask.id",
    )


# ── 任务清单 ────────────────────────────────────────────
class InsightTask(Base):
    __tablename__ = "ark_insight_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    minutes_id = Column(
        Integer,
        ForeignKey("ark_meeting_minutes.id", ondelete="CASCADE"),
        nullable=False,
    )
    assignee = Column(String(50), nullable=False, default="待定")
    description = Column(String(500), nullable=False)
    deadline = Column(Date, nullable=True)
    priority = Column(
        Enum("high", "medium", "low", name="insight_task_priority"),
        nullable=False,
        default="medium",
    )
    status = Column(
        Enum("pending", "in_progress", "completed", "overdue", name="insight_task_status"),
        nullable=False,
        default="pending",
    )
    source_quote = Column(String(500), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    minutes = relationship("MeetingMinutes", back_populates="tasks")


# ── 情报条目 ────────────────────────────────────────────
class InsightItem(Base):
    __tablename__ = "ark_insight_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("ark_insight_sources.id"), nullable=True)
    source_type = Column(String(32), nullable=False)
    collected_at = Column(DateTime, nullable=False)
    published_at = Column(DateTime, nullable=True)
    original_url = Column(Text, nullable=True)
    title = Column(String(512), nullable=True)
    content_mode = Column(String(16), nullable=False, default="summary")
    content_md = Column(LONGTEXT, nullable=True)
    credibility_score = Column(SmallInteger, nullable=True)
    credibility_label = Column(String(32), nullable=True)
    credibility_note = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    item_type = Column(String(64), nullable=True)
    related_competitor = Column(String(128), nullable=True)
    is_featured = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False, default="active")
    # XPOZ 专属字段
    xpoz_post_id = Column(String(64), nullable=True)
    like_count = Column(Integer, nullable=True)
    comment_count = Column(Integer, nullable=True)
    media_type = Column(String(16), nullable=True)
    ai_signal = Column(String(100), nullable=True)
    ai_meaning = Column(String(200), nullable=True)
    ai_action_hint = Column(String(150), nullable=True)
    priority = Column(String(16), nullable=False, default="medium")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_insight_item_collected", "collected_at"),
        Index("idx_insight_item_source", "source_id"),
        Index("idx_insight_item_type", "item_type"),
        Index("idx_insight_item_cred", "credibility_score"),
        Index("idx_insight_item_featured", "is_featured"),
        Index("idx_insight_item_status", "status"),
        Index("idx_insight_item_xpoz", "xpoz_post_id", unique=True),
    )


# ── 采集任务日志 ────────────────────────────────────────
class InsightCollectionLog(Base):
    __tablename__ = "ark_insight_collection_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("ark_insight_sources.id"), nullable=True)
    run_at = Column(DateTime, nullable=False)
    status = Column(String(32), nullable=False)
    items_fetched = Column(Integer, nullable=False, default=0)
    items_written = Column(Integer, nullable=False, default=0)
    items_filtered = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_insight_log_source", "source_id"),
        Index("idx_insight_log_run", "run_at"),
    )


# ── 定时生成规则 ────────────────────────────────────────
class InsightScheduleRule(Base):
    __tablename__ = "ark_insight_schedule_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_name = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    cron_expression = Column(String(64), nullable=True)
    config_json = Column(JSON, nullable=True)
    notify_dingtalk = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_insight_rule_active", "is_active"),
    )


# ── 阿里询盘导入批次 ──────────────────────────────────────
class InquiryImportBatch(Base):
    __tablename__ = "ark_inquiry_import_batches"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_id = Column(String(100), nullable=False, unique=True, comment="ACCIO 批次ID")
    source = Column(String(50), nullable=False, default="accio_work")
    schema_version = Column(String(50), nullable=False)
    generated_at = Column(DateTime, nullable=True)
    time_range_start = Column(DateTime, nullable=True)
    time_range_end = Column(DateTime, nullable=True)
    item_count = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    unassigned_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="processing", comment="processing/success/partial_failed/failed")
    raw_payload = Column(JSON, nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ── 客户机会卡 ──────────────────────────────────────────
class CustomerOpportunity(Base):
    __tablename__ = "ark_customer_opportunities"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    opportunity_type = Column(String(50), nullable=False, comment="ali_inquiry/public_pool/customer_reactivation")
    source = Column(String(50), nullable=False, comment="alibaba_international/okki/manual")
    source_key = Column(String(255), nullable=False, unique=True, comment="外部来源幂等键")
    source_ref_type = Column(String(50), nullable=True, comment="conversation/inquiry/order/customer")
    source_ref_id = Column(String(100), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True, comment="方舟归属用户")
    owner_binding_id = Column(BigInteger, ForeignKey("ark_user_external_bindings.id"), nullable=True, comment="命中的外部账号绑定ID")
    owner_resolve_status = Column(String(20), nullable=False, default="unassigned", comment="resolved/unassigned/conflict/inactive_user")
    source_owner_external_json = Column(JSON, nullable=True, comment="原始外部归属信息")
    customer_name = Column(String(200), nullable=False, default="")
    customer_region = Column(String(100), nullable=True)
    customer_external_id = Column(String(100), nullable=True)
    priority_level = Column(String(5), nullable=False, default="C", comment="A/B/C/D")
    confidence_score = Column(SmallInteger, nullable=False, default=0)
    urgency = Column(String(20), nullable=False, default="normal", comment="urgent/high/normal/low")
    title = Column(String(255), nullable=False, default="")
    summary = Column(Text, nullable=True)
    key_signals_json = Column(JSON, nullable=True)
    background_check_json = Column(JSON, nullable=True)
    recommended_strategy = Column(Text, nullable=True)
    opening_message_en = Column(Text, nullable=True)
    follow_up_message_en = Column(Text, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    full_report_html = Column(Text, nullable=True, comment="ACCIO 完整背调报告 HTML")
    status = Column(String(30), nullable=False, default="pending", comment="pending/contacted/replied/quoted/won/lost/dismissed")
    feedback = Column(String(50), nullable=True)
    due_at = Column(DateTime, nullable=True)
    latest_message_at = Column(DateTime, nullable=True)
    handled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship(
        "CustomerOpportunityEvent",
        back_populates="opportunity",
        cascade="all, delete-orphan",
        order_by="CustomerOpportunityEvent.id.desc()",
    )

    __table_args__ = (
        Index("idx_opp_owner_status", "owner_user_id", "status"),
        Index("idx_opp_owner_priority", "owner_user_id", "priority_level", "due_at"),
        Index("idx_opp_resolve_status", "owner_resolve_status"),
        Index("idx_opp_latest_message", "latest_message_at"),
    )


# ── 客户机会事件 ────────────────────────────────────────
class CustomerOpportunityEvent(Base):
    __tablename__ = "ark_customer_opportunity_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    opportunity_id = Column(BigInteger, ForeignKey("ark_customer_opportunities.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False, comment="created/imported/viewed/copied/status_changed/feedback/assigned")
    actor_user_id = Column(Integer, nullable=True)
    event_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    opportunity = relationship("CustomerOpportunity", back_populates="events")

    __table_args__ = (
        Index("idx_event_opportunity", "opportunity_id", "event_type"),
        Index("idx_event_actor_created", "actor_user_id", "created_at"),
    )


# ── 客户经营雷达 ────────────────────────────────────────


class CustomerProfile(Base):
    """活画像主表 — 一个客户一条记录，持续积累信号"""
    __tablename__ = "ark_customer_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_name = Column(String(200), nullable=False, default="")
    customer_region = Column(String(100))
    customer_company = Column(String(200))
    customer_external_id = Column(String(100), unique=True)
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"))
    owner_resolve_status = Column(String(20), nullable=False, default="unassigned")
    profile_tags = Column(JSON)
    profile_judgement = Column(String(500))
    profile_signals_json = Column(JSON)
    priority_score = Column(SmallInteger, nullable=False, default=0)
    total_opportunities = Column(Integer, nullable=False, default=0)
    total_events = Column(Integer, nullable=False, default=0)
    last_event_at = Column(DateTime)
    last_opportunity_at = Column(DateTime)
    first_seen_at = Column(DateTime, nullable=False)
    source = Column(String(50), nullable=False, default="alibaba_international")
    source_json = Column(JSON)
    suggested_message = Column(Text)
    weight_adjustments = Column(JSON)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    events = relationship("CustomerProfileEvent", back_populates="profile",
                          cascade="all, delete-orphan", order_by="CustomerProfileEvent.occurred_at.desc()")
    actions = relationship("CustomerAction", back_populates="profile",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_profile_owner", "owner_user_id", "status"),
        Index("idx_profile_name_region", "customer_name", "customer_region"),
        Index("idx_profile_priority", "priority_score"),
    )


class CustomerProfileEvent(Base):
    """画像事件流 — 所有信号先成为事件再更新画像"""
    __tablename__ = "ark_customer_profile_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("ark_customer_profiles.id", ondelete="CASCADE"), nullable=False)
    event_source = Column(String(50), nullable=False, comment="accio_inquiry/okki_order/logistics/manual_note")
    event_type = Column(String(50), nullable=False, comment="new_inquiry/replied/won/lost/order_placed/manual_note")
    source_ref_type = Column(String(50))
    source_ref_id = Column(String(100))
    opportunity_id = Column(BigInteger, ForeignKey("ark_customer_opportunities.id"))
    event_title = Column(String(255), nullable=False, default="")
    event_summary = Column(Text)
    event_payload = Column(JSON)
    event_score = Column(SmallInteger, nullable=False, default=0)
    actor_user_id = Column(Integer)
    occurred_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    profile = relationship("CustomerProfile", back_populates="events")

    __table_args__ = (
        Index("idx_cpe_profile_time", "profile_id", "occurred_at"),
        Index("idx_cpe_source", "event_source", "event_type"),
        Index("idx_cpe_opportunity", "opportunity_id"),
    )


class CustomerAction(Base):
    """行动候选池 — 每天为每个客户生成一条推荐行动"""
    __tablename__ = "ark_customer_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(BigInteger, ForeignKey("ark_customer_profiles.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    thread_group = Column(String(30), nullable=False, comment="new_inquiry/sample_delivery/key_account/reorder_window/reactivation/public_pool")
    thread_priority = Column(String(10), nullable=False, default="normal")
    action_reason = Column(String(500), nullable=False, default="")
    suggested_next_action = Column(String(500))
    suggested_message = Column(Text)
    source_evidence = Column(JSON)
    action_status = Column(String(20), nullable=False, default="pending")
    snoozed_until = Column(DateTime)
    action_date = Column(Date, nullable=False)
    completed_at = Column(DateTime)
    completed_by = Column(Integer)
    user_feedback = Column(String(50))
    user_note = Column(Text)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    profile = relationship("CustomerProfile", back_populates="actions")

    __table_args__ = (
        Index("idx_action_owner_date", "owner_user_id", "action_date", "thread_group"),
        Index("idx_action_profile", "profile_id", "action_date"),
        Index("idx_action_status", "owner_user_id", "action_status", "action_date"),
    )
