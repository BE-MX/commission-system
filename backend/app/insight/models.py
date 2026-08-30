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
from app.core.time import beijing_now


# ── 报告主表 ────────────────────────────────────────────
class InsightReport(Base):
    __tablename__ = "ark_insight_reports"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
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
        comment="报告类型 industry_daily/ai_tools/shop_analysis/competitor_analysis/inquiry_analysis/intelligence_overview",
    )
    report_date = Column(Date, nullable=False, comment="报告所属日期")
    title = Column(String(255), nullable=False, default="", comment="报告标题")
    html_content = Column(LONGTEXT, nullable=True, comment="HTML 正文")
    file_path = Column(String(512), nullable=True, comment="静态 HTML 文件路径")
    source_data = Column(JSON, nullable=True, comment="原始数据快照")
    report_metadata = Column(JSON, nullable=True, comment="附加元数据(shop/week 等)")
    status = Column(
        Enum("pending", "published", "failed", "generating", "completed", name="insight_report_status"),
        nullable=False,
        default="pending",
        comment="状态 pending/published/failed/generating/completed",
    )
    error_msg = Column(Text, nullable=True, comment="生成失败错误信息")
    created_by = Column(Integer, nullable=True, comment="操作人ID(定时任务为NULL)")
    # 情报速览扩展字段
    date_range_start = Column(Date, nullable=True, comment="情报选材起始日期")
    date_range_end = Column(Date, nullable=True, comment="情报选材结束日期")
    item_ids = Column(JSON, nullable=True, comment="使用的情报条目ID列表")
    config_snapshot = Column(JSON, nullable=True, comment="生成时配置快照")
    is_pinned = Column(Boolean, nullable=False, default=False, comment="0=否,1=置顶")
    trigger_type = Column(String(32), nullable=False, default="manual", comment="manual/scheduled")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        Index("idx_insight_report_date", "report_date"),
        Index("idx_insight_report_status", "status"),
        Index("idx_insight_report_created_at", "created_at"),
        Index("idx_insight_report_type_date", "report_type", "report_date"),
        {"comment": "方舟洞见-报告主表"},
    )


# ── 信源配置表 ────────────────────────────────────────────
class InsightSource(Base):
    __tablename__ = "ark_insight_sources"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), nullable=False, comment="信源名称")
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
        comment="信源类型 google_alerts_rss/pinterest_scrape/google_trends_rss/amazon_bestseller/competitor_rss/competitor_html/aihot_api/xpoz/competitor_monitor/perplexity/amazon/manual",
    )
    url = Column(String(1024), nullable=False, comment="信源URL")
    keywords = Column(JSON, nullable=True, comment="RSS 关键词过滤")
    exclude_keywords = Column(JSON, nullable=True, comment="排除关键词过滤（JSON数组，命中任一丢弃）")
    css_selector = Column(String(512), nullable=True, comment="HTML 爬虫 CSS 选择器")
    request_headers = Column(JSON, nullable=True, comment="自定义请求头")
    proxy_url = Column(String(255), nullable=True, comment="HTTP 代理地址（如 http://127.0.0.1:1080），NULL 或不填则直连")
    config_json = Column(JSON, nullable=True, comment="差异化配置(cron,target_accounts,monitor_fields等)")
    fetch_interval_hours = Column(SmallInteger, nullable=False, default=24, comment="抓取间隔(小时)")
    last_fetched_at = Column(DateTime, nullable=True, comment="最近成功抓取时间")
    last_error = Column(Text, nullable=True, comment="最近抓取错误信息")
    consecutive_failures = Column(SmallInteger, nullable=False, default=0, comment="连续失败次数")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    pipeline = Column(
        Enum("external", "internal", name="insight_source_pipeline"),
        nullable=False,
        default="external",
        comment="所属管线",
    )
    sort_order = Column(SmallInteger, nullable=False, default=0, comment="排序")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        Index("idx_insight_source_type", "source_type"),
        Index("idx_insight_source_is_active", "is_active"),
        Index("idx_insight_source_pipeline", "pipeline"),
        {"comment": "方舟洞见-情报信源配置"},
    )


# ── 案例库 ────────────────────────────────────────────
class InsightCase(Base):
    __tablename__ = "ark_case_library"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    title = Column(String(200), nullable=False, default="", comment="案例标题")
    scenario = Column(Text, nullable=True, comment="场景描述")
    what_was_done = Column(Text, nullable=True, comment="做了什么")
    result = Column(Text, nullable=True, comment="结果")
    customer_name = Column(String(200), nullable=True, comment="客户名称")
    tags = Column(JSON, nullable=True, comment="标签数组")
    attachments = Column(JSON, nullable=True, comment="附件数组")
    highlights = Column(JSON, nullable=True, comment="AI 提取的核心亮点(兼容字段)")
    customer_type = Column(String(50), nullable=True, comment="客户类型(批发/零售/沙龙)")
    market = Column(String(50), nullable=True, comment="目标市场")
    product_type = Column(String(50), nullable=True, comment="产品类型")
    key_phrases = Column(JSON, nullable=True, comment="关键话术")
    raw_summary = Column(Text, nullable=True, comment="AI 摘要")

    # ── SKILL-based 扩展字段 ──────────────────────
    customer_country = Column(String(50), nullable=True, comment="客户国家")
    communication_channel = Column(String(50), nullable=True, comment="沟通渠道")
    communication_period = Column(String(100), nullable=True, comment="沟通时段")
    total_rounds = Column(SmallInteger, nullable=True, comment="总回合数")
    final_result = Column(String(50), nullable=True, comment="最终结果(成交/未成交/谈判中/流失)")
    background_check_status = Column(String(50), nullable=True, comment="背调状态")
    rounds_analysis = Column(JSON, nullable=True, comment="回合拆解(R1/R2...)")
    dimension_scores = Column(JSON, nullable=True, comment="六维度评分")
    golden_phrases = Column(JSON, nullable=True, comment="亮点话术")
    red_flags = Column(JSON, nullable=True, comment="问题话术")
    core_strengths = Column(JSON, nullable=True, comment="核心亮点")
    result_analysis = Column(JSON, nullable=True, comment="结果归因")
    improvements = Column(JSON, nullable=True, comment="不足与优化方向")
    next_actions = Column(JSON, nullable=True, comment="下一步行动清单")
    ai_draft = Column(JSON, nullable=True, comment="AI 原始完整输出快照")
    user_corrections = Column(JSON, nullable=True, comment="用户评价修正,字段名→修正内容")

    original_content = Column(MEDIUMTEXT, nullable=True, comment="原始输入内容")
    source_type = Column(
        Enum("screenshot", "text_paste", "manual", name="insight_case_source_type"),
        nullable=False,
        default="manual",
        comment="上传方式",
    )
    image_path = Column(String(512), nullable=True, comment="截图文件路径")
    share_person = Column(String(50), nullable=False, default="", comment="分享人姓名")
    share_date = Column(Date, nullable=True, comment="分享日期")
    uploaded_by = Column(Integer, nullable=False, comment="上传人用户ID")
    status = Column(
        Enum("draft", "published", "archived", "processing", "failed", name="insight_case_status"),
        nullable=False,
        default="draft",
        comment="状态",
    )
    error_msg = Column(Text, nullable=True, comment="处理失败信息")
    like_count = Column(Integer, nullable=False, default=0, comment="认可数")
    view_count = Column(Integer, nullable=False, default=0, comment="查看次数")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = {"comment": "方舟洞见-业务员案例库"}


# ── 周会纪要 ────────────────────────────────────────────
class MeetingMinutes(Base):
    __tablename__ = "ark_meeting_minutes"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    meeting_date = Column(Date, nullable=False, comment="会议日期")
    title = Column(String(200), nullable=False, default="", comment="会议主题")
    duration = Column(String(20), nullable=True, comment="时长(如 '90min')")
    participants = Column(String(500), nullable=True, comment="参与人姓名串")
    original_text = Column(LONGTEXT, nullable=False, comment="原始转录文本")
    summary_md = Column(MEDIUMTEXT, nullable=True, comment="精要版 Markdown")
    structured_summary = Column(JSON, nullable=True, comment="结构化精要(topics/decisions/action_items/outcome)")
    tasks_json = Column(JSON, nullable=True, comment="任务清单冗余JSON")
    source_url = Column(String(512), nullable=True, comment="原文链接")
    has_attachment = Column(Boolean, nullable=False, default=False, comment="是否含附件")
    word_count_original = Column(Integer, nullable=True, comment="原文字数")
    word_count_summary = Column(Integer, nullable=True, comment="精要字数")
    status = Column(
        Enum("processing", "published", "failed", name="insight_minutes_status"),
        nullable=False,
        default="processing",
        comment="处理状态",
    )
    error_msg = Column(Text, nullable=True, comment="处理失败信息")
    uploaded_by = Column(Integer, nullable=False, comment="上传人用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = {"comment": "方舟洞见-周会纪要"}

    tasks = relationship(
        "InsightTask",
        back_populates="minutes",
        cascade="all, delete-orphan",
        order_by="InsightTask.id",
    )


# ── 任务清单 ────────────────────────────────────────────
class InsightTask(Base):
    __tablename__ = "ark_insight_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    minutes_id = Column(
        Integer,
        ForeignKey("ark_meeting_minutes.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联会议纪要ID",
    )
    assignee = Column(String(50), nullable=False, default="待定", comment="责任人姓名")
    description = Column(String(500), nullable=False, comment="任务描述")
    deadline = Column(Date, nullable=True, comment="截止日期")
    priority = Column(
        Enum("high", "medium", "low", name="insight_task_priority"),
        nullable=False,
        default="medium",
        comment="优先级",
    )
    status = Column(
        Enum("pending", "in_progress", "completed", "overdue", name="insight_task_status"),
        nullable=False,
        default="pending",
        comment="任务状态",
    )
    source_quote = Column(String(500), nullable=True, comment="原文依据")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    completed_by = Column(Integer, nullable=True, comment="标记完成的用户ID")
    notes = Column(Text, nullable=True, comment="跟进备注")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = {"comment": "方舟洞见-任务执行清单"}

    minutes = relationship("MeetingMinutes", back_populates="tasks")


# ── 情报条目 ────────────────────────────────────────────
class InsightItem(Base):
    __tablename__ = "ark_insight_items"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    source_id = Column(Integer, ForeignKey("ark_insight_sources.id"), nullable=True, comment="来源信源ID")
    source_type = Column(String(32), nullable=False, comment="信源类型冗余")
    collected_at = Column(DateTime, nullable=False, comment="采集时间")
    published_at = Column(DateTime, nullable=True, comment="原始发布时间")
    original_url = Column(Text, nullable=True, comment="原始链接(溯源用)")
    title = Column(String(512), nullable=True, comment="标题")
    content_mode = Column(String(16), nullable=False, default="summary", comment="full_text/summary")
    content_md = Column(LONGTEXT, nullable=True, comment="Markdown内容")
    credibility_score = Column(SmallInteger, nullable=True, comment="可信度分值1-5")
    credibility_label = Column(String(32), nullable=True, comment="verified/plausible/uncertain/unverifiable")
    credibility_note = Column(Text, nullable=True, comment="可信度说明")
    tags = Column(JSON, nullable=True, comment="情报标签数组")
    item_type = Column(String(64), nullable=True, comment="条目类型")
    related_competitor = Column(String(128), nullable=True, comment="关联竞品")
    is_featured = Column(Boolean, nullable=False, default=False, comment="0=否,1=精选")
    status = Column(String(32), nullable=False, default="active", comment="active/archived/flagged")
    # XPOZ 专属字段
    xpoz_post_id = Column(String(64), nullable=True, comment="XPOZ帖子唯一ID")
    like_count = Column(Integer, nullable=True, comment="点赞数")
    comment_count = Column(Integer, nullable=True, comment="评论数")
    media_type = Column(String(16), nullable=True, comment="photo/video/carousel")
    ai_signal = Column(String(100), nullable=True, comment="AI提取核心信号")
    ai_meaning = Column(String(200), nullable=True, comment="AI分析业务意义")
    ai_action_hint = Column(String(150), nullable=True, comment="AI建议可执行动作")
    priority = Column(String(16), nullable=False, default="medium", comment="high/medium/low")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        Index("idx_insight_item_collected", "collected_at"),
        Index("idx_insight_item_source", "source_id"),
        Index("idx_insight_item_type", "item_type"),
        Index("idx_insight_item_cred", "credibility_score"),
        Index("idx_insight_item_featured", "is_featured"),
        Index("idx_insight_item_status", "status"),
        Index("idx_insight_item_xpoz", "xpoz_post_id", unique=True),
        {"comment": "方舟洞见-情报条目表"},
    )


# ── 采集任务日志 ────────────────────────────────────────
class InsightCollectionLog(Base):
    __tablename__ = "ark_insight_collection_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    source_id = Column(Integer, ForeignKey("ark_insight_sources.id"), nullable=True, comment="来源信源ID")
    run_at = Column(DateTime, nullable=False, comment="执行时间")
    status = Column(String(32), nullable=False, comment="success/partial/failed")
    items_fetched = Column(Integer, nullable=False, default=0, comment="抓取条数")
    items_written = Column(Integer, nullable=False, default=0, comment="写入条数")
    items_filtered = Column(Integer, nullable=False, default=0, comment="过滤丢弃条数")
    error_message = Column(Text, nullable=True, comment="错误信息")
    duration_ms = Column(Integer, nullable=True, comment="执行耗时(毫秒)")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        Index("idx_insight_log_source", "source_id"),
        Index("idx_insight_log_run", "run_at"),
        {"comment": "方舟洞见-信源采集任务日志"},
    )


# ── 定时生成规则 ────────────────────────────────────────
class InsightScheduleRule(Base):
    __tablename__ = "ark_insight_schedule_rules"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    rule_name = Column(String(128), nullable=False, comment="规则名称")
    is_active = Column(Boolean, nullable=False, default=True, comment="0=禁用,1=启用")
    cron_expression = Column(String(64), nullable=True, comment="cron表达式")
    config_json = Column(JSON, nullable=True, comment="选材规则、生成配置")
    notify_dingtalk = Column(Boolean, nullable=False, default=True, comment="0=否,1=是")
    last_run_at = Column(DateTime, nullable=True, comment="最近执行时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        Index("idx_insight_rule_active", "is_active"),
        {"comment": "方舟洞见-报告定时生成规则"},
    )


from app.customer.models import (
    CustomerAction,
    CustomerOpportunity,
    CustomerOpportunityEvent,
)


__all__ = [
    "InsightReport",
    "InsightSource",
    "InsightCase",
    "MeetingMinutes",
    "InsightTask",
    "InsightItem",
    "InsightCollectionLog",
    "InsightScheduleRule",
    "CustomerOpportunity",
    "CustomerOpportunityEvent",
    "CustomerAction",
]
