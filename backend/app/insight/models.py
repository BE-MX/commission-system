"""方舟洞见 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
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
