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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_insight_rule_active", "is_active"),
        {"comment": "方舟洞见-报告定时生成规则"},
    )


# ── 阿里询盘导入批次 ──────────────────────────────────────
class InquiryImportBatch(Base):
    __tablename__ = "ark_inquiry_import_batches"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(String(100), nullable=False, unique=True, comment="ACCIO 批次ID")
    source = Column(String(50), nullable=False, default="accio_work", comment="导入来源，默认 accio_work")
    schema_version = Column(String(50), nullable=False, comment="推送数据 schema 版本")
    generated_at = Column(DateTime, nullable=True, comment="ACCIO 侧生成时间")
    time_range_start = Column(DateTime, nullable=True, comment="询盘时间范围起")
    time_range_end = Column(DateTime, nullable=True, comment="询盘时间范围止")
    item_count = Column(Integer, nullable=False, default=0, comment="推送条目总数")
    created_count = Column(Integer, nullable=False, default=0, comment="新建机会数")
    updated_count = Column(Integer, nullable=False, default=0, comment="更新机会数")
    unassigned_count = Column(Integer, nullable=False, default=0, comment="未匹配归属数")
    failed_count = Column(Integer, nullable=False, default=0, comment="失败条数")
    status = Column(String(20), nullable=False, default="processing", comment="processing/success/partial_failed/failed")
    raw_payload = Column(JSON, nullable=True, comment="原始推送数据")
    error_msg = Column(Text, nullable=True, comment="失败错误信息")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = {"comment": "阿里询盘导入批次表"}


# ── 客户机会卡 ──────────────────────────────────────────
class CustomerOpportunity(Base):
    __tablename__ = "ark_customer_opportunities"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    opportunity_type = Column(String(50), nullable=False, comment="ali_inquiry/public_pool/customer_reactivation")
    source = Column(String(50), nullable=False, comment="alibaba_international/okki/manual")
    source_key = Column(String(255), nullable=False, unique=True, comment="外部来源幂等键")
    source_ref_type = Column(String(50), nullable=True, comment="conversation/inquiry/order/customer")
    source_ref_id = Column(String(100), nullable=True, comment="外部引用ID")
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True, comment="方舟归属用户，空=待分配")
    owner_binding_id = Column(BigInteger, ForeignKey("ark_user_external_bindings.id"), nullable=True, comment="命中的外部账号绑定ID")
    owner_resolve_status = Column(String(20), nullable=False, default="unassigned", comment="resolved/unassigned/conflict/inactive_user")
    source_owner_external_json = Column(JSON, nullable=True, comment="原始外部归属信息")
    customer_name = Column(String(200), nullable=False, default="", comment="客户名称")
    customer_region = Column(String(100), nullable=True, comment="客户地区")
    customer_external_id = Column(String(100), nullable=True, comment="客户外部ID")
    priority_level = Column(String(5), nullable=False, default="C", comment="A/B/C/D")
    confidence_score = Column(SmallInteger, nullable=False, default=0, comment="置信度分值")
    urgency = Column(String(20), nullable=False, default="normal", comment="urgent/high/normal/low")
    title = Column(String(255), nullable=False, default="", comment="机会标题")
    summary = Column(Text, nullable=True, comment="机会摘要")
    key_signals_json = Column(JSON, nullable=True, comment="关键信号JSON")
    conversation_summary_json = Column(JSON, nullable=True, comment="ACCIO 压缩后的询盘历史摘要")
    background_check_json = Column(JSON, nullable=True, comment="背调结果JSON")
    background_summary_json = Column(JSON, nullable=True, comment="ACCIO 压缩后的背调摘要")
    customer_profile_json = Column(JSON, nullable=True, comment="ACCIO 客户档案快照")
    recommended_strategy = Column(Text, nullable=True, comment="AI推荐跟进策略")
    opening_message_en = Column(Text, nullable=True, comment="开场话术(英文)")
    follow_up_message_en = Column(Text, nullable=True, comment="跟进话术(英文)")
    evidence_json = Column(JSON, nullable=True, comment="证据依据JSON")
    full_report_html = Column(Text, nullable=True, comment="ACCIO 完整背调报告 HTML")
    status = Column(String(30), nullable=False, default="pending", comment="pending/contacted/replied/quoted/won/lost/dismissed")
    feedback = Column(String(50), nullable=True, comment="业务员反馈")
    due_at = Column(DateTime, nullable=True, comment="处理截止时间(按优先等级计算)")
    latest_message_at = Column(DateTime, nullable=True, comment="客户最新消息时间")
    handled_at = Column(DateTime, nullable=True, comment="处理时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

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
        {"comment": "客户机会卡"},
    )


# ── 客户机会事件 ────────────────────────────────────────
class CustomerOpportunityEvent(Base):
    __tablename__ = "ark_customer_opportunity_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    opportunity_id = Column(BigInteger, ForeignKey("ark_customer_opportunities.id", ondelete="CASCADE"), nullable=False, comment="关联机会ID")
    event_type = Column(String(50), nullable=False, comment="created/imported/viewed/copied/status_changed/feedback/assigned")
    actor_user_id = Column(Integer, nullable=True, comment="操作人用户ID")
    event_payload = Column(JSON, nullable=True, comment="事件附加数据JSON")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    opportunity = relationship("CustomerOpportunity", back_populates="events")

    __table_args__ = (
        Index("idx_event_opportunity", "opportunity_id", "event_type"),
        Index("idx_event_actor_created", "actor_user_id", "created_at"),
        {"comment": "客户机会事件表"},
    )


# ── 客户经营雷达 ────────────────────────────────────────


class CustomerProfile(Base):
    """活画像主表 — 一个客户一条记录，持续积累信号"""
    __tablename__ = "ark_customer_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_name = Column(String(200), nullable=False, default="", comment="客户名称")
    customer_region = Column(String(100), comment="客户地区")
    customer_company = Column(String(200), comment="客户公司名")
    customer_external_id = Column(String(100), unique=True, comment="客户外部ID(唯一)")
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"), comment="归属业务员用户ID")
    owner_resolve_status = Column(String(20), nullable=False, default="unassigned", comment="归属解析状态 resolved/unassigned/conflict/inactive_user")
    profile_tags = Column(JSON, comment="画像标签数组")
    profile_judgement = Column(String(500), comment="AI画像判断结论")
    profile_signals_json = Column(JSON, comment="画像信号JSON")
    priority_score = Column(SmallInteger, nullable=False, default=0, comment="优先级分")
    total_opportunities = Column(Integer, nullable=False, default=0, comment="累计机会数")
    total_events = Column(Integer, nullable=False, default=0, comment="累计事件数")
    last_event_at = Column(DateTime, comment="最近事件时间")
    last_opportunity_at = Column(DateTime, comment="最近机会时间")
    first_seen_at = Column(DateTime, nullable=False, comment="首次出现时间")
    source = Column(String(50), nullable=False, default="alibaba_international", comment="来源，默认 alibaba_international")
    source_json = Column(JSON, comment="来源原始信息JSON")
    suggested_message = Column(Text, comment="推荐话术")
    weight_adjustments = Column(JSON, comment="权重调整JSON")
    status = Column(String(20), nullable=False, default="active", comment="画像状态，默认 active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    events = relationship("CustomerProfileEvent", back_populates="profile",
                          cascade="all, delete-orphan", order_by="CustomerProfileEvent.occurred_at.desc()")
    actions = relationship("CustomerAction", back_populates="profile",
                           cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_profile_owner", "owner_user_id", "status"),
        Index("idx_profile_name_region", "customer_name", "customer_region"),
        Index("idx_profile_priority", "priority_score"),
        {"comment": "客户经营雷达-客户活画像主表"},
    )


class CustomerProfileEvent(Base):
    """画像事件流 — 所有信号先成为事件再更新画像"""
    __tablename__ = "ark_customer_profile_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_id = Column(BigInteger, ForeignKey("ark_customer_profiles.id", ondelete="CASCADE"), nullable=False, comment="关联画像ID")
    event_source = Column(String(50), nullable=False, comment="accio_inquiry/okki_order/logistics/manual_note")
    event_type = Column(String(50), nullable=False, comment="new_inquiry/replied/won/lost/order_placed/manual_note")
    source_ref_type = Column(String(50), comment="外部引用类型")
    source_ref_id = Column(String(100), comment="外部引用ID")
    opportunity_id = Column(BigInteger, ForeignKey("ark_customer_opportunities.id"), comment="关联机会ID")
    event_title = Column(String(255), nullable=False, default="", comment="事件标题")
    event_summary = Column(Text, comment="事件摘要")
    event_payload = Column(JSON, comment="事件附加数据JSON")
    event_score = Column(SmallInteger, nullable=False, default=0, comment="事件评分(正负分)")
    actor_user_id = Column(Integer, comment="操作人用户ID")
    occurred_at = Column(DateTime, nullable=False, comment="事件发生时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    profile = relationship("CustomerProfile", back_populates="events")

    __table_args__ = (
        Index("idx_cpe_profile_time", "profile_id", "occurred_at"),
        Index("idx_cpe_source", "event_source", "event_type"),
        Index("idx_cpe_opportunity", "opportunity_id"),
        {"comment": "客户经营雷达-画像事件流"},
    )


class CustomerAction(Base):
    """行动候选池 — 每天为每个客户生成一条推荐行动"""
    __tablename__ = "ark_customer_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    profile_id = Column(BigInteger, ForeignKey("ark_customer_profiles.id", ondelete="CASCADE"), nullable=False, comment="关联画像ID")
    owner_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="归属业务员用户ID")
    thread_group = Column(String(30), nullable=False, comment="new_inquiry/sample_delivery/key_account/reorder_window/reactivation/public_pool")
    thread_priority = Column(String(10), nullable=False, default="normal", comment="线索优先级标签 优先/重点/保持/顺手")
    action_reason = Column(String(500), nullable=False, default="", comment="推荐理由")
    suggested_next_action = Column(String(500), comment="建议下一步行动")
    suggested_message = Column(Text, comment="建议话术")
    source_evidence = Column(JSON, comment="依据证据JSON")
    action_status = Column(String(20), nullable=False, default="pending", comment="行动状态 pending/done/dismissed/snoozed")
    snoozed_until = Column(DateTime, comment="延后截止时间")
    action_date = Column(Date, nullable=False, comment="行动日期")
    completed_at = Column(DateTime, comment="完成时间")
    completed_by = Column(Integer, comment="标记完成的用户ID")
    user_feedback = Column(String(50), comment="用户反馈")
    user_note = Column(Text, comment="用户备注")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    profile = relationship("CustomerProfile", back_populates="actions")

    __table_args__ = (
        Index("idx_action_owner_date", "owner_user_id", "action_date", "thread_group"),
        Index("idx_action_profile", "profile_id", "action_date"),
        Index("idx_action_status", "owner_user_id", "action_status", "action_date"),
        {"comment": "客户经营雷达-行动候选池"},
    )
