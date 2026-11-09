"""Independent customer-development responsibility and its audit trail."""
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

_UINT = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
_ID = BigInteger().with_variant(Integer, "sqlite")
_CUSTOMER = "ark_domestic_customers.id"
_USER = "ark_users.id"


class FollowupResponsibility(Base):
    __tablename__ = "ark_dom_followup_responsibilities"

    customer_id = Column(Integer, ForeignKey(_CUSTOMER), primary_key=True, comment="内贸客户ID")
    owner_user_id = Column(_UINT, ForeignKey(_USER), index=True, comment="当前主要跟进人")
    status = Column(String(16), nullable=False, default="unassigned", comment="当前协作状态")
    stage = Column(String(24), comment="当前开发进度")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    last_progress_at = Column(DateTime, comment="最近有效推进时间（北京时间）")
    next_plan_date = Column(Date, comment="当前承诺的下次开发安排（北京日期）")
    allow_future_contact = Column(Boolean, comment="停止开发后是否允许未来联系")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="最后更新时间（北京时间）")


class FollowupScope(Base):
    __tablename__ = "ark_dom_followup_scopes"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_key", name="uq_dom_fu_scope_member"),
        Index("ix_dom_fu_scope_region", "province", "city"),
    )

    id = Column(_ID, primary_key=True, comment="主键")
    user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="授权成员或协作人ID")
    customer_id = Column(Integer, ForeignKey(_CUSTOMER), index=True, comment="内贸客户ID")
    province = Column(String(64), comment="授权省份，客户级授权为空")
    city = Column(String(64), comment="授权城市，空表示省内全市")
    scope_key = Column(String(132), nullable=False, comment="每个成员的授权去重键（客户或地区）")
    added_by_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="创建授权或协作关系的用户")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class FollowupCollaborator(Base):
    __tablename__ = "ark_dom_followup_collaborators"

    customer_id = Column(Integer, ForeignKey(_CUSTOMER), primary_key=True, comment="内贸客户ID")
    user_id = Column(_UINT, ForeignKey(_USER), primary_key=True, index=True, comment="授权成员或协作人ID")
    added_by_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="创建授权或协作关系的用户")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class FollowupHandoff(Base):
    __tablename__ = "ark_dom_followup_handoffs"
    __table_args__ = (
        UniqueConstraint("customer_id", "pending_marker", name="uq_dom_fu_handoff_pending"),
        Index("ix_dom_fu_handoff_recipient", "recipient_user_id", "status"),
    )

    id = Column(_ID, primary_key=True, comment="主键")
    customer_id = Column(Integer, ForeignKey(_CUSTOMER), nullable=False, comment="内贸客户ID")
    from_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="原跟进负责人")
    recipient_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="拟接收的新负责人")
    requester_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="发起交接或接手申请的用户")
    kind = Column(String(12), nullable=False, comment="交接类型（发起交接或申请接手）")
    status = Column(String(16), nullable=False, default="pending", comment="交接单处理状态")
    pending_marker = Column(Integer, default=1, comment="待处理时为1，其余为空，限制每客户仅一单待处理")
    responsibility_version = Column(Integer, nullable=False, comment="交接或事件对应的责任版本")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    reason = Column(String(500), nullable=False, comment="操作原因")
    summary = Column(Text, comment="经人员确认的交接摘要")
    obstacle = Column(String(500), comment="当前推进障碍")
    commitment = Column(String(500), comment="已经向客户承诺的事项")
    next_step = Column(String(500), comment="接续推进的建议")
    tasks = Column(JSON, nullable=False, comment="所选待办、处理决定与漂移校验快照")
    selected_record_ids = Column(JSON, nullable=False, comment="选入交接包的已确认记录ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    handled_at = Column(DateTime, comment="处理时间（北京时间）")
    handled_by_user_id = Column(_UINT, ForeignKey(_USER), comment="处理交接的用户")
    handling_reason = Column(String(500), comment="交接处理说明")


class FollowupCollaborationEvent(Base):
    __tablename__ = "ark_dom_followup_collab_events"
    __table_args__ = (
        UniqueConstraint("customer_id", "actor_user_id", "idempotency_key", name="uq_dom_fu_collab_request"),
        Index("ix_dom_fu_collab_customer", "customer_id", "id"),
    )

    id = Column(_ID, primary_key=True, comment="主键")
    customer_id = Column(Integer, ForeignKey(_CUSTOMER), nullable=False, comment="内贸客户ID")
    actor_user_id = Column(_UINT, ForeignKey(_USER), nullable=False, comment="执行操作的用户")
    action = Column(String(24), nullable=False, comment="协作审计事件动作")
    idempotency_key = Column(String(64), comment="同一客户与操作者的幂等键")
    request_hash = Column(String(64), comment="幂等请求的参数哈希")
    handoff_id = Column(_ID, ForeignKey("ark_dom_followup_handoffs.id"), comment="关联交接单ID")
    from_user_id = Column(_UINT, ForeignKey(_USER), comment="原跟进负责人")
    to_user_id = Column(_UINT, ForeignKey(_USER), comment="变更后的主要跟进人")
    responsibility_version = Column(Integer, nullable=False, comment="交接或事件对应的责任版本")
    reason = Column(String(500), comment="操作原因")
    details = Column(JSON, comment="事件的结构化补充证据")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")


class FollowupCustomerProfile(Base):
    __tablename__ = "ark_dom_followup_customer_profiles"

    customer_id = Column(Integer, ForeignKey(_CUSTOMER), primary_key=True, comment="内贸客户ID")
    wechat = Column(String(120), comment="客户微信号")
    deal_status = Column(String(16), comment="人工核实的成交结论")
    deal_evidence = Column(Text, comment="人工核实成交时提供的依据")
    deal_verified_by_user_id = Column(_UINT, ForeignKey(_USER), comment="成交核实人")
    deal_verified_at = Column(DateTime, comment="成交核实时间（北京时间）")
