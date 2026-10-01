"""Customer workbench lifecycle, responsibility, delegation and daily admission records."""

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now
from app.customer.models import USER_ID


def item_ref():
    return Column(BigInteger, ForeignKey("ark_customer_work_items.id", ondelete="RESTRICT"), nullable=False, index=True, comment="经营事项ID；通过事项解析当前客户与权限")


def actor_ref():
    return Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, index=True, comment="执行登记的方舟用户ID")


class WorkItemEvent(Base):
    __tablename__ = "ark_customer_work_item_events"
    __table_args__ = ({"comment": "经营事项不可变事件：状态、结果、重开、纠正与来源版本；不能删除外部事实。"},)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="事件ID")
    item_id = item_ref()
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=True, comment="操作人；确定性来源消费可为空")
    event_type = Column(String(32), nullable=False, index=True, comment="事件类型")
    from_state = Column(String(24), nullable=False, comment="操作前状态")
    to_state = Column(String(24), nullable=False, comment="操作后状态")
    reason = Column(Text, nullable=False, comment="原因、实际结果或来源变化说明")
    evidence_refs = Column(JSON, nullable=False, default=list, comment="已校验且保留版本的证据引用")
    input_revision = Column(Integer, nullable=False, comment="本次登记依赖的事项输入版本")
    item_version = Column(Integer, nullable=False, comment="事件提交后的事项版本")
    payload_json = Column(JSON, nullable=False, default=dict, comment="事件结构化附加内容，包含历史结果与可逆登记前态")
    occurred_at = Column(DateTime, nullable=False, default=beijing_now, index=True, comment="事件发生的北京时间")


class WorkItemDependency(Base):
    __tablename__ = "ark_customer_work_item_dependencies"
    __table_args__ = (UniqueConstraint("item_id", "source_domain", "source_id", name="uq_work_item_dependency_source"), {"comment": "事项所需的责任行动/源任务；源模块仍拥有执行事实写入权。"})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="依赖ID")
    item_id = item_ref()
    source_domain = Column(String(24), nullable=False, comment="来源：action/shipment/design等登记域")
    source_id = Column(String(64), nullable=False, comment="源对象持久ID")
    title = Column(String(500), nullable=False, comment="必要交付内容，不复制无权查看的价格或沟通")
    required = Column(Boolean, nullable=False, default=True, comment="是否必须在解决前验收")
    observed_status = Column(String(32), nullable=False, default="unknown", comment="最近核验状态；不可用不得冒充完成")
    observed_revision = Column(String(64), nullable=True, comment="最近核验的源版本")
    source_valid = Column(Boolean, nullable=False, default=False, comment="最近观察是否仍有效")
    observed_at = Column(DateTime, nullable=True, comment="来源最近核验的北京时间")


class CustomerDelegation(Base):
    __tablename__ = "ark_customer_delegations"
    __table_args__ = ({"comment": "事项授权范围内持续委派；多个Run受generation与事项生命周期共同约束。"},)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="委派ID")
    item_id = item_ref()
    actor_user_id = actor_ref()
    goal = Column(Text, nullable=False, comment="这次委派要达成的明确目标")
    scope_json = Column(JSON, nullable=False, comment="只读/产物准备工具范围与当前授权快照")
    status = Column(String(24), nullable=False, default="active", index=True, comment="active/waiting/needs_decision/blocked/paused/cancelled/completed")
    generation = Column(Integer, nullable=False, default=1, comment="取消/恢复令牌；旧代次不得执行新动作")
    input_revision = Column(Integer, nullable=False, comment="委派读取的事项来源版本")
    row_version = Column(Integer, nullable=False, default=1, comment="委派乐观锁版本")
    review_at = Column(DateTime, nullable=True, comment="继续核验的北京时间")
    last_run_id = Column(BigInteger, ForeignKey("ark_agent_runs.id", ondelete="RESTRICT"), nullable=True, comment="最近受控运行ID；终态Run不能复活")
    pause_origin = Column(String(16), nullable=True, comment="item或manual；恢复事项不复活独立手动暂停")
    pause_reason = Column(String(1000), nullable=True, comment="暂停、终止或受阻原因")
    cancel_requested = Column(Boolean, nullable=False, default=False, comment="在途Run停止请求；不是已经停止的证明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新北京时间")


class WorkbenchDailyPlan(Base):
    __tablename__ = "ark_customer_daily_plans"
    __table_args__ = (UniqueConstraint("actor_user_id", "business_date", name="uq_workbench_plan_actor_day"), {"comment": "北京业务日普通事项容量账本，完成/策略切换不释放已领取预算。"})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="日计划ID")
    actor_user_id = actor_ref()
    business_date = Column(Date, nullable=False, index=True, comment="北京时间业务日期")
    policy_version = Column(String(32), nullable=False, comment="入选策略版本；不构成日计划身份")
    budget = Column(Integer, nullable=False, comment="今日普通事项容量，显式增额另有审计")
    focus = Column(String(24), nullable=False, default="commitments", comment="个人经营重点，仅调整同优先级排序")
    row_version = Column(Integer, nullable=False, default=1, comment="日计划乐观锁版本")
    initialized = Column(Boolean, nullable=False, default=False, comment="已执行首次普通入选，空清单也不得无限补位")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新北京时间")


class WorkbenchAdmission(Base):
    __tablename__ = "ark_customer_daily_admissions"
    __table_args__ = (UniqueConstraint("plan_id", "item_id", name="uq_workbench_plan_item"), {"comment": "当日已领取事项集合；完成、暂停、重开均不退还或重复消费容量。"})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="入选ID")
    plan_id = Column(BigInteger, ForeignKey("ark_customer_daily_plans.id", ondelete="RESTRICT"), nullable=False, index=True, comment="日计划ID")
    item_id = item_ref()
    admission_type = Column(String(24), nullable=False, comment="ordinary/manual_extra/urgent_override")
    reason = Column(String(1000), nullable=False, comment="入选/紧急新增/主动增额的依据")
    budget_before = Column(Integer, nullable=False, comment="操作前普通容量")
    budget_after = Column(Integer, nullable=False, comment="操作后普通容量")
    admitted_at = Column(DateTime, nullable=False, default=beijing_now, comment="实际入选的北京时间")


class WorkItemFeedback(Base):
    __tablename__ = "ark_customer_work_item_feedback"
    __table_args__ = (UniqueConstraint("item_id", "target_id", "target_revision", "actor_user_id", "dimension", name="uq_work_item_feedback_dimension"), {"comment": "事实准确、建议适用与实际采纳分别评价，重复点击不增加样本量。"})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="反馈ID")
    item_id = item_ref()
    actor_user_id = actor_ref()
    target_id = Column(String(64), nullable=False, comment="被评价的建议/事实/行动ID")
    target_revision = Column(Integer, nullable=False, comment="被评价内容版本")
    dimension = Column(String(24), nullable=False, comment="accuracy/applicability/adoption")
    decision = Column(String(8), nullable=False, comment="yes/no；不是模型整体准确率或经营收益")
    reason = Column(String(1000), nullable=True, comment="反馈原因")
    evidence_refs = Column(JSON, nullable=False, default=list, comment="纠错依据引用")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新北京时间")


class WorkItemSourceDelivery(Base):
    __tablename__ = "ark_customer_work_item_source_deliveries"
    __table_args__ = (UniqueConstraint("source_domain", "source_event_id", "source_revision", "item_id", name="uq_work_item_source_delivery"), {"comment": "源事件至少一次消费的版本化去重记录，跨日不创建副本事项。"})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="消费ID")
    item_id = item_ref()
    source_domain = Column(String(24), nullable=False, comment="登记来源域")
    source_event_id = Column(String(64), nullable=False, comment="来源持久事件ID")
    source_revision = Column(Integer, nullable=False, comment="来源版本，旧版本不得覆盖新事实")
    processed_at = Column(DateTime, nullable=False, default=beijing_now, comment="消费北京时间")
