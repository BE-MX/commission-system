"""内贸客户跟进领域模型（规格第三节）。

不建 ORM relationship（红线 9），关联一律由 service 显式查询。
FK 类型与目标列一致：ark_domestic_customers.id 是有符号 INT，ark_users.id
是 unsigned INT，ark_domestic_shipments.id 是 BIGINT（红线 5）。
"""
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, SmallInteger, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DomesticFollowup(Base):
    __tablename__ = "ark_domestic_followups"
    __table_args__ = (
        Index("ix_dom_followup_customer_date", "customer_id", "followup_date"),
        Index("ix_dom_followup_author_status", "author_user_id", "status"),
        {"comment": "内贸客户跟进记录：一次触达一条"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=True,
                         comment="客户ID；草稿可暂空，确认时必填")
    author_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="录入人，永久保留")
    followup_date = Column(Date, nullable=False, comment="跟进日期（北京日期）")
    channel = Column(String(16), nullable=True, comment="沟通方式（sys_dict: domestic_followup_channel）")
    raw_text = Column(Text, nullable=True, comment="业务员原文，永不被 AI 覆盖")
    summary = Column(String(500), nullable=True, comment="一句话摘要")
    state_changes = Column(JSON, nullable=True, comment="客户状态变化（sys_dict: domestic_followup_state_change）")
    next_date = Column(Date, nullable=True, comment="下次跟进日期")
    next_plan = Column(String(500), nullable=True, comment="下次跟进内容")
    next_method = Column(String(16), nullable=True, comment="下次跟进方式")
    chat_title = Column(String(120), nullable=True, comment="截图聊天标题，确认后学习为客户别名")
    source = Column(String(16), nullable=False, default="web", comment="web/mobile/mini/wechat_agent/import")
    status = Column(String(12), nullable=False, default="draft", comment="draft/confirmed/discarded")
    ai_status = Column(String(12), nullable=False, default="none", comment="none/running/done/failed")
    ai_result = Column(JSON, nullable=True, comment="AI 归一化后的草稿")
    ai_error = Column(String(255), nullable=True, comment="AI 失败原因（不含原文）")
    ai_log_id = Column(BigInteger, nullable=True, comment="AI 调用日志ID")
    source_task_id = Column(BigInteger, nullable=True, comment="从哪张待办发起的记录")
    request_id = Column(String(64), nullable=False, unique=True, comment="客户端幂等键")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁：状态迁移时 +1")
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class DomesticFollowupItem(Base):
    __tablename__ = "ark_domestic_followup_items"
    __table_args__ = (
        Index("ix_dom_followup_item_followup", "followup_id"),
        Index("ix_dom_followup_item_board", "kind", "status", "customer_id"),
        {"comment": "跟进条目：要点 / 异常 / 意见建议"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    followup_id = Column(BigInteger, ForeignKey("ark_domestic_followups.id"), nullable=False, comment="所属跟进记录")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID（冗余，供看板查询）")
    seq = Column(SmallInteger, nullable=False, comment="同类条目内的序号，从 1 开始")
    kind = Column(String(12), nullable=False, comment="content/issue/suggestion")
    text = Column(String(1000), nullable=False, comment="条目内容")
    category = Column(String(32), nullable=True, comment="分类（sys_dict: domestic_followup_category）")
    severity = Column(String(8), nullable=True, comment="一般/紧急")
    origin = Column(String(16), nullable=False, default="user", comment="user/ai_inferred")
    status = Column(String(20), nullable=True, comment="issue/suggestion：open/handling/resolved/closed_no_action")
    handler_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="当前处理人")
    resolution = Column(String(500), nullable=True, comment="处理说明")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间（北京时间）")
    resolved_by_followup_id = Column(BigInteger, nullable=True, comment="在哪条跟进里处理")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class DomesticFollowupAttachment(Base):
    __tablename__ = "ark_domestic_followup_attachments"
    __table_args__ = (
        Index("ix_dom_followup_att_followup", "followup_id"),
        Index("ix_dom_followup_att_uploader", "uploader_user_id", "followup_id"),
        {"comment": "跟进截图附件，带 OCR 文本"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    followup_id = Column(BigInteger, ForeignKey("ark_domestic_followups.id"), nullable=True, comment="所属跟进；上传后未绑定为空")
    uploader_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="上传人")
    seq = Column(SmallInteger, nullable=False, default=0, comment="在记录中的顺序")
    file_path = Column(String(255), nullable=False, comment="domestic 存储相对路径")
    file_name = Column(String(255), nullable=True, comment="原始文件名")
    mime_type = Column(String(64), nullable=True, comment="MIME")
    file_size = Column(Integer, nullable=False, default=0, comment="字节数")
    ocr_status = Column(String(12), nullable=False, default="pending", comment="pending/done/failed")
    ocr_text = Column(Text, nullable=True, comment="OCR 文本")
    unreadable_note = Column(String(500), nullable=True, comment="AI 读不到的内容说明（语音/视频等）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="上传时间（北京时间）")


class DomesticCustomerAlias(Base):
    __tablename__ = "ark_domestic_customer_aliases"
    __table_args__ = (
        UniqueConstraint("alias_norm", "customer_id", name="uq_dom_customer_alias"),
        {"comment": "客户别名：聊天标题 / 微信备注名 → 客户"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id", ondelete="CASCADE"), nullable=False, comment="客户ID")
    alias = Column(String(120), nullable=False, comment="别名原文")
    alias_norm = Column(String(120), nullable=False, comment="归一化别名（去空白、小写）")
    hit_count = Column(Integer, nullable=False, default=1, comment="确认命中次数")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="首次记录人")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class DomesticFollowupTask(Base):
    __tablename__ = "ark_domestic_followup_tasks"
    __table_args__ = (
        Index("ix_dom_followup_task_assignee", "assignee_user_id", "status", "due_date"),
        Index("ix_dom_followup_task_customer", "customer_id", "status"),
        {"comment": "跟进任务：约定跟进 / 收货回访 / 异常跟进 / 意见跟进"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_type = Column(String(12), nullable=False, comment="plan/receipt/issue/suggestion")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID")
    assignee_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="负责人")
    source_key = Column(String(96), nullable=False, unique=True, comment="来源唯一键，一个来源只生一次任务")
    title = Column(String(200), nullable=False, comment="标题")
    due_date = Column(Date, nullable=False, comment="到期日（北京日期）")
    status = Column(String(12), nullable=False, default="todo", comment="todo/done/expired/cancelled")
    snooze_count = Column(SmallInteger, nullable=False, default=0, comment="顺延次数")
    payload = Column(JSON, nullable=True, comment="展示用快照：批次列表 / 计划内容 / 条目摘要")
    source_followup_id = Column(BigInteger, nullable=True, comment="来源跟进记录")
    source_item_id = Column(BigInteger, nullable=True, comment="来源条目")
    closed_by_followup_id = Column(BigInteger, nullable=True, comment="被哪条跟进关闭")
    closed_reason = Column(String(16), nullable=True, comment="回访完成/有新跟进/条目已解决/超时过期/客户释放")
    closed_by_user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="关闭操作人；系统关闭为空")
    closed_at = Column(DateTime, nullable=True, comment="关闭时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")


class DomesticFollowupTaskShipment(Base):
    __tablename__ = "ark_domestic_followup_task_shipments"
    __table_args__ = ({"comment": "收货回访任务覆盖的发货批次；shipment_id 唯一保证每批次只提醒一次"},)

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_domestic_followup_tasks.id"), nullable=False, index=True, comment="回访任务")
    shipment_id = Column(BigInteger, ForeignKey("ark_domestic_shipments.id"), nullable=False, unique=True, comment="发货批次")


class DomesticFollowupDigest(Base):
    __tablename__ = "ark_domestic_followup_digests"
    __table_args__ = (
        UniqueConstraint("user_id", "digest_date", "kind", "ref_key", name="uq_dom_followup_digest"),
        Index("ix_dom_followup_digest_pending", "kind", "pushed_at"),
        {"comment": "跟进推送发件箱：同人同日同类只推一次"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="接收人")
    digest_date = Column(Date, nullable=False, comment="推送业务日（北京日期）")
    kind = Column(String(12), nullable=False, comment="daily=每日汇总，urgent=紧急异常")
    ref_key = Column(String(64), nullable=False, default="", comment="daily 为空串；urgent 为 item:<id>")
    title = Column(String(100), nullable=False, comment="通知标题")
    markdown = Column(Text, nullable=False, comment="通知正文")
    attempts = Column(SmallInteger, nullable=False, default=0, comment="发送失败次数")
    last_error = Column(String(255), nullable=True, comment="最近一次失败原因")
    pushed_at = Column(DateTime, nullable=True, comment="推送成功时间（北京时间）")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class DomesticFollowupConfig(Base):
    __tablename__ = "ark_domestic_followup_config"
    __table_args__ = ({"comment": "跟进模块配置：回访天数、上线日、紧急接收人、跟进频率"},)

    key = Column(String(64), primary_key=True, comment="配置键")
    value = Column(JSON, nullable=True, comment="配置值")
    updated_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=True, comment="最后维护人")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")
