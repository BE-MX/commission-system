"""Announcement metadata and durable publication/delivery facts; no duplicate body."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from app.core.database import Base
from app.core.time import beijing_now


class AnnouncementConfig(Base):
    __tablename__ = 'ark_announcement_config'
    id = Column(Integer, primary_key=True, comment='主键')  # singleton id=1
    library_id = Column(BigInteger, ForeignKey('ark_knowledge_libraries.id'), nullable=False, unique=True, comment='公告知识库ID')
    group_name = Column(String(120), nullable=False, default='', comment='公告群名称')
    conversation_id = Column(String(256), nullable=False, default='', comment='钉钉群会话ID')
    robot_code = Column(String(128), nullable=False, default='', comment='应用机器人编码')
    delivery_enabled = Column(Boolean, nullable=False, default=False, comment='自动推送开关')
    channel_verified = Column(Boolean, nullable=False, default=False, comment='图文通道已验证')
    weekly_enabled = Column(Boolean, nullable=False, default=False, comment='每周汇总开关')
    weekly_hour = Column(Integer, nullable=False, default=9, comment='周一北京时间小时')
    weekly_minute = Column(Integer, nullable=False, default=0, comment='周一北京时间分钟')
    preset_name = Column(String(100), nullable=False, default='', comment='周报AI方案名称')
    executor_id = Column(Integer, nullable=False, comment='后台执行方舟用户ID')
    version = Column(Integer, nullable=False, default=1, comment='配置版本')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间')


class Announcement(Base):
    __tablename__ = 'ark_announcement_items'
    document_id = Column(BigInteger, ForeignKey('ark_knowledge_documents.id'), primary_key=True, comment='公告知识文档ID')
    pinned = Column(Boolean, nullable=False, default=False, comment='是否置顶')
    withdrawn_at = Column(DateTime, comment='撤回时间')
    withdrawal_reason = Column(String(500), comment='撤回原因')
    published_at = Column(DateTime, comment='最后发布时间')
    published_by = Column(Integer, comment='最后发布人ID')


class AnnouncementMeta(Base):
    __tablename__ = 'ark_announcement_revision_meta'
    revision_id = Column(BigInteger, ForeignKey('ark_knowledge_revisions.id'), primary_key=True, comment='知识修订ID')
    category_id = Column(BigInteger, ForeignKey('ark_knowledge_documents.id'), nullable=False, comment='类别目录ID')
    category_name = Column(String(256), nullable=False, comment='类别名称快照')
    important = Column(Boolean, nullable=False, default=False, comment='重要标记')
    effective_at = Column(DateTime, comment='生效时间')
    expires_at = Column(DateTime, comment='截止时间')
    change_note = Column(String(500), nullable=False, default='', comment='更新说明')


class Publication(Base):
    __tablename__ = 'ark_announcement_publications'
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    document_id = Column(BigInteger, ForeignKey('ark_knowledge_documents.id'), nullable=False, comment='公告知识文档ID')
    revision_id = Column(BigInteger, ForeignKey('ark_knowledge_revisions.id'), nullable=False, comment='知识修订ID')
    kind = Column(String(16), nullable=False, comment='发布事件类型')
    title = Column(String(256), nullable=False, comment='公告标题快照')
    reason = Column(String(500), comment='撤回说明')
    actor_id = Column(Integer, nullable=False, comment='操作用户ID')
    created_at = Column(DateTime, nullable=False, default=beijing_now, index=True, comment='创建时间')
    __table_args__ = (UniqueConstraint('document_id', 'revision_id', 'kind', name='uq_announcement_publication'),)


class WeeklyReport(Base):
    __tablename__ = 'ark_announcement_weekly'
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    library_id = Column(BigInteger, ForeignKey('ark_knowledge_libraries.id'), nullable=False, comment='公告知识库ID')
    period_start = Column(DateTime, nullable=False, comment='统计区间起点（北京时间）')
    period_end = Column(DateTime, nullable=False, comment='统计区间终点（不含）')
    status = Column(String(24), nullable=False, default='queued', comment='处理状态')
    sources = Column(JSON, nullable=False, default=list, comment='冻结来源及版本')
    body = Column(Text, nullable=False, default='', comment='周报正文')
    error = Column(String(200), comment='脱敏处理说明')
    attempts = Column(Integer, nullable=False, default=0, comment='尝试次数')
    lease_token = Column(String(40), comment='领取租约令牌')
    lease_until = Column(DateTime, comment='租约截止时间')
    config_version = Column(Integer, nullable=False, comment='配置版本快照')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间')
    generation = Column(Integer, nullable=False, default=1, comment='周报版本号')
    auto_send = Column(Boolean, nullable=False, default=False, comment='完成后自动发送')
    history = Column(JSON, nullable=False, default=list, comment='历史周报版本')
    __table_args__ = (UniqueConstraint('library_id', 'period_start', name='uq_announcement_weekly_period'),)


class Delivery(Base):
    __tablename__ = 'ark_announcement_deliveries'
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    source_key = Column(String(80), nullable=False, comment='投递来源唯一业务键')
    publication_id = Column(BigInteger, ForeignKey('ark_announcement_publications.id'), comment='发布事件ID')
    weekly_id = Column(BigInteger, ForeignKey('ark_announcement_weekly.id'), comment='周报ID')
    sequence = Column(Integer, nullable=False, comment='消息序号')
    target = Column(String(256), nullable=False, comment='目标群快照')
    robot_code = Column(String(128), nullable=False, comment='应用机器人编码')
    config_version = Column(Integer, nullable=False, comment='配置版本快照')
    payload = Column(JSON, nullable=False, comment='冻结消息内容与授权指纹')
    status = Column(String(24), nullable=False, default='queued', index=True, comment='处理状态')
    attempts = Column(Integer, nullable=False, default=0, comment='尝试次数')
    next_attempt_at = Column(DateTime, nullable=False, default=beijing_now, comment='下次尝试时间')
    lease_token = Column(String(40), comment='领取租约令牌')
    lease_until = Column(DateTime, comment='租约截止时间')
    error = Column(String(200), comment='脱敏处理说明')
    receipt = Column(String(256), comment='钉钉接口回执')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间')
    sent_at = Column(DateTime, comment='投递时间')
    __table_args__ = (UniqueConstraint('source_key', 'sequence', name='uq_announcement_delivery_part'),)
