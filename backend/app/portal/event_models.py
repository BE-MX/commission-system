"""Auditable actions and transactional, encrypted delivery outbox."""

from sqlalchemy import Column, DateTime, Integer, JSON, LargeBinary, String, Index

from app.core.database import Base
from app.portal.model_base import ID, PREFIX, Record, reference


class AuditEvent(Record, Base):
    __tablename__ = PREFIX + "audit_events"
    actor_type = Column(String(16), nullable=False, comment='客户、员工或系统操作者类型')
    actor_id = Column(ID, comment='对应类型操作者ID')
    access_id = reference("customer_access", nullable=True)
    object_type = Column(String(32), nullable=False, comment='审计对象类别')
    object_public_id = Column(String(36), nullable=False, comment='目标对象公开ID')
    action = Column(String(64), nullable=False, comment='受控操作类型')
    before_version = Column(ID, comment='变更前版本')
    after_version = Column(ID, comment='变更后版本')
    reason = Column(String(500), nullable=False, default="", comment='操作理由，禁止存凭证与完整个人资料')
    safe_diff_json = Column(JSON, nullable=False, default=dict, comment='脱敏审计差异')
    trace_id = Column(String(64), nullable=False, comment='排障关联ID')
    __table_args__ = (Index("ix_op_audit_object", "object_type", "object_public_id", "created_at"),)


class OutboxEvent(Record, Base):
    __tablename__ = PREFIX + "outbox"
    event_key = Column(String(160), nullable=False, unique=True, comment='通知业务事件唯一键')
    event_type = Column(String(32), nullable=False, comment='通知类别')
    aggregate_public_id = Column(String(36), nullable=False, comment='通知所属业务对象')
    payload_json = Column(JSON, nullable=False, comment='通知非秘密引用数据')
    secret_envelope = Column(LargeBinary, comment='邀请或验证码AES-GCM短期密文')
    secret_key_version = Column(String(32), comment='邮件密钥版本引用')
    secret_expires_at = Column(DateTime, comment='秘密事件失效清理时间')
    status = Column(String(16), nullable=False, default="pending", comment='受服务层状态机约束的业务状态')
    attempt_count = Column(Integer, nullable=False, default=0, comment='发送累计尝试次数')
    next_attempt_at = Column(DateTime, nullable=False, comment='下次发送时间')
    lease_until = Column(DateTime, comment='任务租约截止，北京时间')
    lease_token = Column(String(64), comment='任务抢占身份')
    last_error_code = Column(String(64), comment='最近失败的脱敏错误码')
    __table_args__ = (Index("ix_op_outbox_pending", "status", "next_attempt_at"),)
