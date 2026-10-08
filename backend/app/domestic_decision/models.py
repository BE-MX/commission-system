"""Analysis-owned state. Business orders and wallet entries remain in domestic."""

from sqlalchemy import Column, Integer, BigInteger, String, JSON, DateTime, Date, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DecisionMapping(Base):
    __tablename__ = "ark_domestic_analysis_attr_mappings"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    property = Column(String(32), nullable=False, comment='分析属性')
    product_type = Column(String(16), nullable=False, default="", server_default="", comment='产品类型；空值表示通用映射')
    raw_value = Column(String(255), nullable=False, comment='原始值')
    standard_value = Column(String(255), nullable=False, comment='人工审核的标准值')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='最后维护人')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时）')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时）')
    __table_args__ = (UniqueConstraint("property", "product_type", "raw_value", name="uq_dom_analysis_mapping"),)


class DecisionConfig(Base):
    __tablename__ = "ark_domestic_analysis_config"
    key = Column(String(64), primary_key=True, comment='配置键')
    value = Column(JSON, nullable=False, comment='配置值')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment='最后维护人')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时）')


class DecisionEvent(Base):
    __tablename__ = "ark_domestic_analysis_events"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    source_event_key = Column(String(64), nullable=False, unique=True, comment='稳定事件幂等键')
    entity_type = Column(String(24), nullable=False, comment='实体类型')
    entity_id = Column(BigInteger().with_variant(Integer(), "sqlite"), nullable=False, comment='源实体编号；包含大整数账本编号')
    customer_id = Column(Integer, nullable=True, comment='客户编号')
    order_id = Column(Integer, nullable=True, comment='订单编号')
    event_type = Column(String(32), nullable=False, comment='创建、变更或删除')
    business_date = Column(Date, nullable=True, comment='订单业务日期')
    before = Column(JSON, nullable=True, comment='变更前必要字段快照')
    after = Column(JSON, nullable=True, comment='变更后必要字段快照')
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment='归属或创建用户')
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment='业务操作人；自动任务可为空')
    occurred_at = Column(DateTime, nullable=False, default=beijing_now, comment='事件时间（北京时）')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    __table_args__ = (Index("idx_dom_analysis_event_customer", "customer_id", "id"), Index("idx_dom_analysis_event_order", "order_id", "id"))


class DecisionRun(Base):
    __tablename__ = "ark_domestic_analysis_runs"
    id = Column(String(36), primary_key=True, comment='主键')
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='归属或创建用户')
    query_json = Column(JSON, nullable=False, comment='验证后的查询条件')
    result_json = Column(JSON, nullable=False, comment='固定结果快照')
    scope_customer_ids = Column(JSON, nullable=False, comment='生成时授权客户集合；读取再次校验')
    includes_finance = Column(Integer, nullable=False, default=0, comment='是否包含资金信息')
    data_version = Column(String(64), nullable=False, comment='事实与口径指纹')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时）')
    expires_at = Column(DateTime, nullable=False, comment='交互证据到期时间（北京时）')
    __table_args__ = (Index("idx_dom_analysis_run_owner", "owner_user_id", "created_at"),)


class DecisionView(Base):
    __tablename__ = "ark_domestic_analysis_views"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='归属或创建用户')
    name = Column(String(80), nullable=False, comment='视图名称')
    query_json = Column(JSON, nullable=False, comment='验证后的查询条件')
    time_mode = Column(String(16), nullable=False, default="rolling", comment='滚动或固定日期模式')
    shared = Column(Integer, nullable=False, default=0, comment='仅分享查询条件')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时）')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时）')
    __table_args__ = (Index("idx_dom_analysis_view_owner", "owner_user_id"),)


class DecisionAction(Base):
    __tablename__ = "ark_domestic_analysis_actions"
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='归属或创建用户')
    assignee_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='行动负责人')
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=False, comment='客户编号')
    source_key = Column(String(64), nullable=False, comment='行动请求幂等指纹')
    request_key = Column(String(64), nullable=False, comment="首次认领请求幂等键")
    request_hash = Column(String(64), nullable=False, comment="首次认领请求内容指纹")
    rule_key = Column(String(64), nullable=False, comment='触发规则编号')
    title = Column(String(200), nullable=False, comment='行动标题')
    evidence_json = Column(JSON, nullable=False, comment='生成时固定证据')
    trigger_json = Column(JSON, nullable=False, comment='条件指纹与资金权限标识')
    due_date = Column(Date, nullable=False, comment='期限（北京日期）')
    status = Column(String(24), nullable=False, default="todo", comment='行动或任务状态')
    result = Column(Text, nullable=True, comment='实际跟进结果说明')
    result_type = Column(String(32), nullable=True, comment='实际结果分类；不代替订单或入账')
    condition_changed = Column(Integer, nullable=False, default=0, comment='触发条件已变化')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时）')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时）')
    __table_args__ = (UniqueConstraint("owner_user_id", "source_key", name="uq_dom_analysis_action_source"), UniqueConstraint("owner_user_id", "request_key", name="uq_dom_analysis_action_request"), Index("idx_dom_analysis_action_due", "assignee_user_id", "status", "due_date"))


class DecisionJob(Base):
    __tablename__ = "ark_domestic_analysis_jobs"
    id = Column(String(36), primary_key=True, comment='主键')
    kind = Column(String(16), nullable=False, comment='简报或导出')
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment='归属或创建用户')
    request_key = Column(String(64), nullable=False, comment='用户请求幂等键')
    request_hash = Column(String(64), nullable=False, comment='请求内容指纹')
    run_id = Column(String(36), ForeignKey("ark_domestic_analysis_runs.id"), nullable=False, comment='固定分析快照')
    status = Column(String(16), nullable=False, default="queued", comment='行动或任务状态')
    source = Column(String(16), nullable=True, comment='AI、规则或快照')
    result_json = Column(JSON, nullable=True, comment='固定结果快照')
    error_message = Column(String(500), nullable=True, comment='失败说明')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时）')
    started_at = Column(DateTime, nullable=True, comment='开始时间（北京时）')
    finished_at = Column(DateTime, nullable=True, comment='结束时间（北京时）')
    __table_args__ = (UniqueConstraint("owner_user_id", "kind", "request_key", name="uq_dom_analysis_job_request"), Index("idx_dom_analysis_job_status", "status", "created_at"))
