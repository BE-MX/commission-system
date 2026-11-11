"""项目雷达持久化模型。"""

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from app.auth import models as _auth_models  # noqa: F401
from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class RadarTarget(Base):
    __tablename__ = "ark_project_radar_target"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    canonical_url = Column(String(1024), nullable=False, comment="归一化目标地址")
    url_hash = Column(String(64), nullable=False, unique=True, comment="目标地址SHA-256唯一键")
    kind = Column(String(16), nullable=False, default="website", comment="目标类型repo/website/article")
    title = Column(String(255), nullable=False, default="", comment="项目标题")
    item_type = Column(String(64), nullable=False, default="other", comment="项目雷达类型字典代码")
    one_liner = Column(String(500), nullable=False, default="", comment="一句话说明")
    description = Column(MEDIUMTEXT, nullable=True, comment="AI详细说明")
    ark_modules = Column(JSON, nullable=False, default=list, comment="可应用方舟模块及理由难度")
    version = Column(String(128), nullable=True, comment="数据源提供的当前版本")
    last_updated_at = Column(DateTime, nullable=True, comment="数据源最近更新时间（北京时间）")
    last_update_summary = Column(JSON, nullable=False, default=list, comment="最近更新摘要")
    read_state = Column(String(16), nullable=False, default="pending", comment="读取状态pending/ok/limited/failed")
    consecutive_failures = Column(Integer, nullable=False, default=0, comment="连续读取失败天数")
    last_error = Column(String(500), nullable=True, comment="最近读取错误摘要")
    last_scanned_at = Column(DateTime, nullable=True, comment="最近扫描时间（北京时间）")
    scan_enabled = Column(Boolean, nullable=False, default=True, comment="是否存在有效订阅并允许扫描")
    scan_mode = Column(String(16), nullable=False, default="program", comment="扫描方式program/agent")
    last_agent_check_at = Column(DateTime, nullable=True, comment="最近agent检查时间（二期）")
    stars = Column(Integer, nullable=True, comment="GitHub Star数")
    archived = Column(Boolean, nullable=False, default=False, comment="GitHub仓库是否归档")
    license = Column(String(128), nullable=True, comment="开源协议")
    language = Column(String(64), nullable=True, comment="主要开发语言")
    repo_etag = Column(String(255), nullable=True, comment="GitHub仓库信息ETag")
    release_etag = Column(String(255), nullable=True, comment="GitHub Release ETag")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = (
        Index("idx_radar_target_scan", "scan_enabled", "scan_mode", "last_scanned_at"),
        {"comment": "项目雷达-全局追踪目标"},
    )


class RadarTrackedPage(Base):
    __tablename__ = "ark_project_radar_tracked_page"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    target_id = Column(Integer, ForeignKey("ark_project_radar_target.id", ondelete="CASCADE"), nullable=False, comment="追踪目标ID")
    url = Column(String(1024), nullable=False, comment="追踪页地址")
    url_hash = Column(String(64), nullable=False, comment="完整追踪页地址SHA-256")
    page_kind = Column(String(16), nullable=False, default="changelog", comment="页面类型changelog/rss/pricing/docs")
    enabled = Column(Boolean, nullable=False, default=True, comment="是否启用")
    etag = Column(String(255), nullable=True, comment="页面HTTP ETag")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("target_id", "url_hash", name="uq_radar_page_target_url_hash"),
        Index("idx_radar_page_target", "target_id", "enabled"),
        {"comment": "项目雷达-网站追踪页"},
    )


class RadarUpdate(Base):
    __tablename__ = "ark_project_radar_update"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    target_id = Column(Integer, ForeignKey("ark_project_radar_target.id", ondelete="CASCADE"), nullable=False, comment="追踪目标ID")
    event_key = Column(String(191), nullable=False, comment="更新事件幂等键")
    detected_at = Column(DateTime, nullable=False, default=beijing_now, comment="检测时间（北京时间）")
    rule_level = Column(String(16), nullable=False, comment="规则分级key/normal/noise")
    ai_level = Column(String(16), nullable=True, comment="AI复核分级key/normal/noise")
    ai_reason = Column(String(1000), nullable=True, comment="AI复核理由")
    from_version = Column(String(128), nullable=True, comment="更新前版本")
    to_version = Column(String(128), nullable=True, comment="更新后版本")
    summary = Column(JSON, nullable=False, default=list, comment="更新内容摘要")
    ark_impact = Column(Text, nullable=True, comment="对方舟的影响与落地建议")
    raw_ref = Column(JSON, nullable=True, comment="原文出处与检测证据")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("target_id", "event_key", name="uq_radar_update_target_event"),
        Index("idx_radar_update_target_time", "target_id", "detected_at"),
        {"comment": "项目雷达-检测到的更新"},
    )


class RadarSubscription(Base):
    __tablename__ = "ark_project_radar_subscription"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, comment="订阅用户ID")
    target_id = Column(Integer, ForeignKey("ark_project_radar_target.id", ondelete="CASCADE"), nullable=False, comment="追踪目标ID")
    status = Column(String(16), nullable=False, default="inbox", comment="试用状态inbox/trying/adopted/dropped")
    watch_level = Column(String(16), nullable=False, default="normal", comment="关注级别key/normal/adopted/silent")
    tags = Column(JSON, nullable=False, default=list, comment="个人标签")
    remark = Column(Text, nullable=False, default="", comment="个人笔记")
    overrides = Column(JSON, nullable=False, default=dict, comment="人工修改并锁定的字段")
    ai_suggestions = Column(JSON, nullable=False, default=dict, comment="待用户采纳的AI新建议")
    unread_update_id = Column(Integer, ForeignKey("ark_project_radar_update.id", ondelete="SET NULL"), nullable=True, comment="未读更新ID")
    last_pushed_at = Column(DateTime, nullable=True, comment="最近推送时间（北京时间）")
    last_normal_pushed_at = Column(DateTime, nullable=True, comment="最近普通更新推送时间（北京时间）")
    removed_at = Column(DateTime, nullable=True, comment="移出雷达时间（软删除）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("user_id", "target_id", name="uq_radar_subscription_user_target"),
        Index("idx_radar_subscription_user", "user_id", "removed_at", "status"),
        Index("idx_radar_subscription_target", "target_id", "removed_at"),
        {"comment": "项目雷达-个人订阅"},
    )


class RadarSource(Base):
    __tablename__ = "ark_project_radar_source"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    subscription_id = Column(Integer, ForeignKey("ark_project_radar_subscription.id", ondelete="CASCADE"), nullable=False, comment="个人订阅ID")
    ingest_job_id = Column(Integer, ForeignKey("ark_project_radar_ingest_job.id", ondelete="SET NULL"), nullable=True, comment="收录任务ID")
    source_url = Column(String(1024), nullable=False, comment="原始来源地址")
    channel = Column(String(32), nullable=False, comment="来源渠道dingtalk/web/mcp等")
    raw_text = Column(Text, nullable=True, comment="用户原始输入或笔记")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")

    __table_args__ = (
        Index("idx_radar_source_subscription", "subscription_id", "created_at"),
        {"comment": "项目雷达-个人订阅来源"},
    )


class RadarSnapshot(Base):
    __tablename__ = "ark_project_radar_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    target_id = Column(Integer, ForeignKey("ark_project_radar_target.id", ondelete="CASCADE"), nullable=False, comment="追踪目标ID")
    tracked_page_id = Column(Integer, ForeignKey("ark_project_radar_tracked_page.id", ondelete="CASCADE"), nullable=True, comment="追踪页ID")
    captured_at = Column(DateTime, nullable=False, default=beijing_now, comment="快照时间（北京时间）")
    version = Column(String(128), nullable=True, comment="快照版本")
    release_tag = Column(String(128), nullable=True, comment="Release标签")
    etag = Column(String(255), nullable=True, comment="HTTP ETag")
    clean_text_compressed = Column(MEDIUMTEXT, nullable=True, comment="去噪正文压缩文本")
    text_hash = Column(String(64), nullable=True, comment="正文SHA-256")
    raw_ref = Column(JSON, nullable=True, comment="快照原文出处")

    __table_args__ = (
        Index("idx_radar_snapshot_target_time", "target_id", "captured_at"),
        Index("idx_radar_snapshot_page_time", "tracked_page_id", "captured_at"),
        {"comment": "项目雷达-压缩快照"},
    )


class RadarIngestJob(Base):
    __tablename__ = "ark_project_radar_ingest_job"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    request_key = Column(String(191), nullable=False, unique=True, comment="收录请求幂等键或钉钉消息ID")
    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, comment="提交用户ID")
    channel = Column(String(32), nullable=False, comment="收录渠道")
    raw_input = Column(Text, nullable=False, comment="原始输入")
    status = Column(String(20), nullable=False, default="queued", comment="任务状态queued/reading/awaiting_choice/completed/failed")
    candidates = Column(JSON, nullable=False, default=list, comment="待选项目候选")
    result = Column(JSON, nullable=False, default=dict, comment="收录结果")
    error = Column(String(1000), nullable=True, comment="失败原因")
    retry_count = Column(Integer, nullable=False, default=0, comment="已重试次数")
    dingtalk_id = Column(String(100), nullable=True, comment="钉钉发送人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = (
        Index("idx_radar_ingest_status", "status", "updated_at"),
        Index("idx_radar_ingest_user", "user_id", "created_at"),
        {"comment": "项目雷达-持久收录任务"},
    )


class RadarDialog(Base):
    __tablename__ = "ark_project_radar_dialog"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, unique=True, comment="用户ID")
    kind = Column(String(20), nullable=False, comment="上下文类型choose/supplement/card")
    job_id = Column(Integer, ForeignKey("ark_project_radar_ingest_job.id", ondelete="CASCADE"), nullable=True, comment="收录任务ID")
    target_id = Column(Integer, ForeignKey("ark_project_radar_target.id", ondelete="CASCADE"), nullable=True, comment="追踪目标ID")
    payload = Column(JSON, nullable=False, default=dict, comment="对话上下文数据")
    expires_at = Column(DateTime, nullable=False, comment="过期时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")

    __table_args__ = (
        Index("idx_radar_dialog_expiry", "expires_at"),
        {"comment": "项目雷达-钉钉对话上下文"},
    )


class RadarUserSetting(Base):
    __tablename__ = "ark_project_radar_user_setting"

    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), primary_key=True, comment="用户ID")
    digest_time = Column(String(5), nullable=False, default="08:00", comment="个人早报时间HH:mm")
    send_empty = Column(Boolean, nullable=False, default=False, comment="无更新时是否发送")
    sleepy_reminder = Column(Boolean, nullable=False, default=True, comment="是否开启周一沉睡提醒")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = {"comment": "项目雷达-个人推送设置"}


class RadarGlobalSetting(Base):
    __tablename__ = "ark_project_radar_global_setting"

    id = Column(Integer, primary_key=True, autoincrement=False, comment="单例主键")
    scan_time = Column(String(5), nullable=False, default="06:30", comment="全局扫描时间HH:mm")
    normal_push_cooldown_days = Column(Integer, nullable=False, default=7, comment="普通更新推送冷却天数")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = {"comment": "项目雷达-全局扫描设置"}


class RadarScanRun(Base):
    __tablename__ = "ark_project_radar_scan_run"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    scan_date = Column(Date, nullable=False, unique=True, comment="扫描日期（北京时间）")
    status = Column(String(20), nullable=False, default="running", comment="运行状态running/success/partial/failed")
    total_count = Column(Integer, nullable=False, default=0, comment="应扫描项目数")
    success_count = Column(Integer, nullable=False, default=0, comment="成功项目数")
    failed_count = Column(Integer, nullable=False, default=0, comment="失败项目数")
    error = Column(String(1000), nullable=True, comment="扫描错误摘要")
    started_at = Column(DateTime, nullable=False, default=beijing_now, comment="开始时间（北京时间）")
    finished_at = Column(DateTime, nullable=True, comment="完成时间（北京时间）")

    __table_args__ = {"comment": "项目雷达-每日扫描健康记录"}


class RadarDigest(Base):
    __tablename__ = "ark_project_radar_digest"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, comment="接收用户ID")
    digest_date = Column(Date, nullable=False, comment="早报日期（北京时间）")
    item_count = Column(Integer, nullable=False, default=0, comment="更新项目数")
    status = Column(String(20), nullable=False, default="pending", comment="投递状态pending/sent/failed")
    dingtalk_ref = Column(String(256), nullable=True, comment="钉钉投递回执")
    content = Column(MEDIUMTEXT, nullable=False, comment="早报Markdown正文")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("user_id", "digest_date", name="uq_radar_digest_user_date"),
        Index("idx_radar_digest_date", "digest_date", "status"),
        {"comment": "项目雷达-每日早报"},
    )


class RadarDelivery(Base):
    __tablename__ = "ark_project_radar_delivery"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    subscription_id = Column(Integer, ForeignKey("ark_project_radar_subscription.id", ondelete="CASCADE"), nullable=False, comment="个人订阅ID")
    update_id = Column(Integer, ForeignKey("ark_project_radar_update.id", ondelete="CASCADE"), nullable=False, comment="更新ID")
    digest_id = Column(Integer, ForeignKey("ark_project_radar_digest.id", ondelete="CASCADE"), nullable=False, comment="早报ID")
    delivered_at = Column(DateTime, nullable=False, default=beijing_now, comment="投递时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("subscription_id", "update_id", name="uq_radar_delivery_sub_update"),
        Index("idx_radar_delivery_digest", "digest_id"),
        {"comment": "项目雷达-个人更新投递记录"},
    )


class RadarOutbox(Base):
    __tablename__ = "ark_project_radar_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="CASCADE"), nullable=False, comment="接收用户ID")
    dedup_key = Column(String(191), nullable=False, unique=True, comment="消息幂等键")
    kind = Column(String(32), nullable=False, comment="消息类型digest/markdown/action_card")
    payload = Column(JSON, nullable=False, default=dict, comment="消息内容与关联ID")
    status = Column(String(20), nullable=False, default="pending", comment="投递状态pending/sent/failed")
    attempts = Column(Integer, nullable=False, default=0, comment="投递尝试次数")
    claimed_at = Column(DateTime, nullable=True, comment="原子领取时间（北京时间）")
    last_error = Column(String(500), nullable=True, comment="最近投递错误")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    sent_at = Column(DateTime, nullable=True, comment="发送成功时间（北京时间）")

    __table_args__ = (
        Index("idx_radar_outbox_status", "status", "created_at"),
        {"comment": "项目雷达-钉钉异步消息发件箱"},
    )
