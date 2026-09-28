"""私海客户工作台（PCW）SQLAlchemy schema。

设计来源：docs/requirements/private-customer-workbench-prototype/schema-migrations.md。
事项以 (business_key, business_cycle) 稳定去重，行动按事项+轮次扩展在
ark_customer_actions（见 app.customer.models.CustomerAction）；本模块不定义
ORM relationship，关联由服务层显式查询。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now
from app.customer.models import USER_ID


HASH64 = String(64).with_variant(mysql.CHAR(64), "mysql")


class CustomerWorkItem(Base):
    __tablename__ = "ark_customer_work_items"
    __table_args__ = (
        UniqueConstraint("business_key", "business_cycle", name="uq_customer_work_item_key"),
        Index("ix_ark_customer_work_items_customer_state", "customer_id", "state"),
        {"comment": "私海客户经营事项表；以稳定业务键+真实业务周期跨日去重，扫描日、负责人和规则版本变化不改变事项身份。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="经营事项ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_work_item_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="创建时不可变的存储客户ID；当前逻辑客户统一解析ark_customer_object_ownerships")
    business_key = Column(String(128), nullable=False, comment="稳定业务事件键：来源域持久分配，不含扫描日、负责人或提示词版本")
    business_cycle = Column(String(64), nullable=False, comment="真实业务周期标识；无新周期证据不得更换以绕过去重")
    work_type = Column(String(32), nullable=False, comment="事项类型：inquiry、reorder、sample、monitor、maintenance、campaign或登记值")
    state = Column(String(24), nullable=False, default="open", index=True, comment="事项状态：open、awaiting_reply、resolved、cancelled")
    title = Column(String(500), nullable=False, comment="面向业务员的事项标题")
    context_json = Column(JSON, nullable=False, default=dict, comment="pcw_work_item_context_v1：稳定来源引用与最近一次评估上下文快照")
    next_action_round = Column(Integer, nullable=False, default=1, comment="下一行动轮次；完成未解决行动时在事项行锁内递增")
    row_version = Column(Integer, nullable=False, default=1, comment="乐观锁版本；完成行动与改约同事务校验")
    resolved_at = Column(DateTime, nullable=True, comment="事项解决的北京时间；仅resolved非空")
    resolved_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_work_item_resolved_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="解决该事项的方舟用户ID；系统解决允许为空")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事项创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="事项最后更新的北京时间")


class CustomerEvaluationRun(Base):
    __tablename__ = "ark_customer_evaluation_runs"
    __table_args__ = (
        UniqueConstraint("run_uid", name="uq_customer_evaluation_run_uid"),
        UniqueConstraint("business_date", "rule_version", "scope_hash", "run_kind", "attempt", name="uq_customer_evaluation_run_attempt"),
        {"comment": "每日客户评估批次表；冻结客户范围、规则版本与输入水位，同日显式重评以run_kind/attempt区分，不伪装自然重跑。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="评估批次ID")
    run_uid = Column(String(36), nullable=False, comment="对外暴露的批次UUID")
    business_date = Column(Date, nullable=False, index=True, comment="评估业务日期（北京时间）")
    rule_version = Column(String(32), nullable=False, comment="评估规则版本")
    run_kind = Column(String(16), nullable=False, comment="批次类型：scheduled、manual、dry_run")
    attempt = Column(Integer, nullable=False, default=1, comment="同业务日同范围的重试序号，从1递增")
    scope_hash = Column(HASH64, nullable=False, comment="冻结客户范围规范序列化的SHA-256")
    frozen_scope_json = Column(JSON, nullable=False, comment="pcw_evaluation_scope_v1：冻结的客户集合、归属版本与输入水位")
    status = Column(String(16), nullable=False, default="running", index=True, comment="批次状态：running、completed、failed")
    expected_count = Column(Integer, nullable=False, default=0, comment="冻结范围内应评估客户数")
    rule_completed = Column(Integer, nullable=False, default=0, comment="规则评估完成客户数")
    rule_failed = Column(Integer, nullable=False, default=0, comment="规则评估失败客户数")
    ai_completed = Column(Integer, nullable=False, default=0, comment="AI增量分析完成客户数")
    ai_skipped_unchanged = Column(Integer, nullable=False, default=0, comment="输入无变化跳过AI分析客户数")
    ai_failed = Column(Integer, nullable=False, default=0, comment="AI分析失败客户数；不阻塞规则结果")
    checkpoint_json = Column(JSON, nullable=True, comment="分片检查点；用于中断恢复")
    lease_until = Column(DateTime, nullable=True, comment="批次执行租约到期的北京时间")
    triggered_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_evaluation_run_triggered_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="手动触发用户ID；定时调度允许为空")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="批次创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="批次最后更新的北京时间")


class CustomerEvaluationItem(Base):
    __tablename__ = "ark_customer_evaluation_items"
    __table_args__ = (
        UniqueConstraint("run_id", "customer_id", name="uq_customer_evaluation_item_customer"),
        Index("ix_ark_customer_evaluation_items_retry", "rules_status", "next_retry_at"),
        {"comment": "评估批次逐客户结果表；customer_id为冻结时点存储客户ID（不加外键，避免合并后悬挂），运行时经逻辑客户解析当前归属。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="评估明细ID")
    run_id = Column(BigInteger, ForeignKey("ark_customer_evaluation_runs.id", name="fk_customer_evaluation_item_run", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="所属评估批次ID")
    customer_id = Column(BigInteger, nullable=False, index=True, comment="冻结时点的存储客户ID；不加外键，归属变化由逻辑客户解析")
    assignment_version = Column(String(64), nullable=True, comment="冻结时点归属版本；供漂移审计")
    input_hash = Column(HASH64, nullable=False, comment="本客户评估输入规范序列化的SHA-256；无变化时AI跳过")
    watermarks_json = Column(JSON, nullable=True, comment="评估时使用的各来源已授权同步水位")
    rules_status = Column(String(16), nullable=False, default="pending", comment="规则评估状态：pending、completed、failed")
    ai_status = Column(String(24), nullable=False, default="pending", comment="AI分析状态：pending、completed、skipped_unchanged、failed、disabled")
    error_code = Column(String(64), nullable=True, comment="失败的稳定错误码")
    error_message = Column(String(500), nullable=True, comment="可行动且脱敏的失败说明")
    action_counters_json = Column(JSON, nullable=True, comment="pcw_action_counters_v1：本客户新建/复用/抑制行动计数")
    next_retry_at = Column(DateTime, nullable=True, comment="失败补偿下一次重试的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="明细创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="明细最后更新的北京时间")


class CustomerFactReview(Base):
    __tablename__ = "ark_customer_fact_reviews"
    __table_args__ = (
        UniqueConstraint("candidate_fact_id", name="uq_customer_fact_review_candidate"),
        Index("ix_ark_customer_fact_reviews_status_defer", "status", "defer_until"),
        {"comment": "AI档案建议人工审核元数据表；只保存审核状态与事实/修订引用，不复制画像内容；绑定或输入变化使旧建议stale而不是重置pending。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="建议审核ID")
    candidate_fact_id = Column(BigInteger, ForeignKey("ark_customer_facts.id", name="fk_customer_fact_review_candidate", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="被审核的候选事实ID；一条候选事实只审核一次")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_fact_review_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="建议所属存储客户ID")
    status = Column(String(16), nullable=False, default="pending", index=True, comment="审核状态：pending、accepted、rejected、deferred、stale")
    decision_reason = Column(String(1000), nullable=True, comment="驳回必填的审核原因；采纳可补充说明")
    defer_until = Column(DateTime, nullable=True, comment="deferred重新提醒的北京时间")
    reviewer_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_fact_review_reviewer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="完成审核的方舟用户ID")
    revision_annotation_id = Column(BigInteger, ForeignKey("ark_customer_annotations.id", name="fk_customer_fact_review_annotation", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="采纳或编辑采纳产生的Annotation v2修订ID")
    profile_revision_event_id = Column(BigInteger, ForeignKey("ark_customer_events.id", name="fk_customer_fact_review_event", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="采纳后档案修订事件ID")
    suggestion_version = Column(Integer, nullable=False, default=1, comment="建议乐观锁版本；同一建议仅一次有效决定")
    decided_at = Column(DateTime, nullable=True, comment="完成审核决定的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="建议登记创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="审核状态最后更新的北京时间")


class ConversationBinding(Base):
    __tablename__ = "ark_customer_conversation_bindings"
    __table_args__ = (
        UniqueConstraint("source_system", "source_account_key", "source_conversation_id", name="uq_customer_conversation_binding_source"),
        {"comment": "源系统会话到客户的当前绑定表；源系统+账号+会话ID是稳定身份，重绑历史在binding_events单独留痕。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="会话绑定ID")
    source_system = Column(String(24), nullable=False, comment="会话来源系统：whatsapp、alibaba、email或登记值")
    source_account_key = Column(String(64), nullable=False, comment="源账号命名空间键，不含凭证")
    source_conversation_id = Column(String(128), nullable=False, comment="源系统内稳定会话ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_binding_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, index=True, comment="当前绑定存储客户ID；待绑定为空")
    contact_id = Column(BigInteger, ForeignKey("ark_customer_contacts.id", name="fk_customer_binding_contact", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="绑定时明确的外部联系人ID")
    projected_conversation_id = Column(BigInteger, ForeignKey("ark_customer_conversations.id", name="fk_customer_binding_conversation", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="绑定成功后投影的客户会话ID")
    version = Column(Integer, nullable=False, default=0, comment="绑定版本；未绑定为0，首次绑定成功为1，重绑递增")
    state = Column(String(16), nullable=False, default="pending", index=True, comment="绑定状态：pending、active、unbound")
    share_scope = Column(String(24), nullable=False, default="customer_team", comment="绑定时预览并确认的共享范围")
    evidence_json = Column(JSON, nullable=True, comment="绑定依据引用：verified_contact_point等证据对象ID")
    bound_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_binding_bound_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="执行绑定的方舟用户ID")
    bound_at = Column(DateTime, nullable=True, comment="当前绑定生效的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="绑定记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="绑定记录最后更新的北京时间")


class ConversationBindingEvent(Base):
    __tablename__ = "ark_customer_conversation_binding_events"
    __table_args__ = {"comment": "会话绑定变化的不可变审计表；记录绑定、重绑、解绑的前后客户与版本，重绑须走治理链。"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="绑定事件ID")
    binding_id = Column(BigInteger, ForeignKey("ark_customer_conversation_bindings.id", name="fk_customer_binding_event_binding", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="所属绑定记录ID")
    event_type = Column(String(24), nullable=False, comment="事件类型：bound、rebound、unbound")
    before_customer_id = Column(BigInteger, nullable=True, comment="变化前存储客户ID；首次绑定为空")
    after_customer_id = Column(BigInteger, nullable=True, comment="变化后存储客户ID；解绑为空")
    binding_version = Column(Integer, nullable=False, comment="事件生效后的绑定版本")
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_binding_event_actor", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="执行绑定变化的方舟用户ID")
    reason = Column(String(1000), nullable=True, comment="重绑或解绑的业务原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件记录的北京时间")


class ConversationAnalysisJob(Base):
    __tablename__ = "ark_customer_conversation_analysis_jobs"
    __table_args__ = (
        UniqueConstraint("job_uid", name="uq_customer_analysis_job_uid"),
        UniqueConstraint("conversation_id", "input_manifest_hash", "binding_version", "rule_version", name="uq_customer_analysis_job_input"),
        {"comment": "会话分析异步任务表；相同会话、输入清单哈希、绑定版本与规则版本复用同一任务，失权或重绑使旧派生结果stale。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="分析任务ID")
    job_uid = Column(String(36), nullable=False, comment="对外暴露的任务UUID")
    conversation_id = Column(BigInteger, ForeignKey("ark_customer_conversations.id", name="fk_customer_analysis_job_conversation", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="被分析的客户会话ID")
    binding_id = Column(BigInteger, ForeignKey("ark_customer_conversation_bindings.id", name="fk_customer_analysis_job_binding", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="分析依据的会话绑定ID")
    binding_version = Column(Integer, nullable=False, comment="发起分析时校验的绑定版本")
    analysis_version = Column(Integer, nullable=False, comment="产生结果在会话内的分析版本号")
    input_manifest_hash = Column(HASH64, nullable=False, comment="服务端计算的已授权输入消息清单与水位哈希；不信任客户端哈希")
    rule_version = Column(String(32), nullable=False, comment="分析规则与提示词版本")
    status = Column(String(16), nullable=False, default="queued", index=True, comment="任务状态：queued、running、succeeded、failed、stale、cancelled")
    coverage_json = Column(JSON, nullable=True, comment="pcw_analysis_coverage_v1：sync_from、sync_to、gaps、attachments_unread")
    failure_reason = Column(String(500), nullable=True, comment="失败的可行动脱敏说明")
    result_analysis_id = Column(BigInteger, ForeignKey("ark_customer_conversation_analyses.id", name="fk_customer_analysis_job_result", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="成功时写入的会话分析版本ID")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_analysis_job_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="发起分析的方舟用户ID")
    started_at = Column(DateTime, nullable=True, comment="任务开始执行的北京时间")
    finished_at = Column(DateTime, nullable=True, comment="任务到达终态的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="任务创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="任务最后更新的北京时间")


class OrderAnalysisBatchMap(Base):
    __tablename__ = "ark_customer_order_batch_map"
    __table_args__ = (
        UniqueConstraint("order_item_id", "mapping_version", name="uq_customer_order_batch_item"),
        {"comment": "订单明细到商业采购批次与产品族的版本化映射表；无法确定真实批次时标记低置信同日归并，不假装精确。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="批次映射ID")
    order_id = Column(BigInteger, ForeignKey("ark_customer_orders.id", name="fk_customer_order_batch_order", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="方舟客户订单ID")
    order_item_id = Column(BigInteger, ForeignKey("ark_customer_order_items.id", name="fk_customer_order_batch_item", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="方舟订单明细ID；整单级映射允许为空")
    purchase_batch_key = Column(String(128), nullable=False, index=True, comment="商业采购批次稳定键；排除样品、取消、退回失效与拆单重复")
    product_family = Column(String(128), nullable=False, comment="映射时确定的产品族")
    mapping_version = Column(String(32), nullable=False, comment="批次归并规则版本；版本更新整体重映射")
    provenance = Column(String(32), nullable=False, comment="批次来源：explicit=真实批次证据，same_day_merge=同客户同业务日同族低置信归并")
    quality_status = Column(String(24), nullable=False, default="normal", comment="映射质量：normal、low_confidence")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="映射写入的北京时间")


class ReorderWindow(Base):
    __tablename__ = "ark_customer_reorder_windows"
    __table_args__ = (
        UniqueConstraint("occurrence_key", name="uq_customer_reorder_window_key"),
        {"comment": "按产品族与商业采购批次计算的复购观察窗口表；窗口是询问采购计划的依据，不表示客户库存即将耗尽。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="复购窗口ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_reorder_window_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="窗口所属存储客户ID")
    product_family = Column(String(128), nullable=False, index=True, comment="窗口产品族")
    anchor_batch_key = Column(String(128), nullable=False, comment="窗口锚定的最近商业采购批次键")
    occurrence_key = Column(String(160), nullable=False, comment="窗口稳定实例键：产品族+锚定批次+窗口实例；规则版本更新同一窗口不重复建")
    metric_version = Column(String(32), nullable=False, default="commercial_cycle_v1", comment="周期口径版本；旧purchase_cycle_days指标语义不变")
    sample_refs_json = Column(JSON, nullable=False, default=list, comment="pcw_reorder_samples_v1：参与计算的批次键与间隔天数样本")
    median_interval_days = Column(Integer, nullable=True, comment="批次间隔中位数天数；样本不足为空")
    window_from = Column(Date, nullable=False, comment="观察窗口开始业务日期（末单+中位数-7天）")
    window_to = Column(Date, nullable=False, comment="观察窗口结束业务日期（末单+中位数+7天）")
    confidence = Column(String(16), nullable=False, comment="窗口置信：regular、irregular、insufficient")
    state = Column(String(16), nullable=False, default="open", index=True, comment="窗口状态：open、covered、superseded、closed")
    work_item_id = Column(BigInteger, ForeignKey("ark_customer_work_items.id", name="fk_customer_reorder_window_work_item", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="窗口关联的经营事项ID")
    action_id = Column(BigInteger, ForeignKey("ark_customer_actions.id", name="fk_customer_reorder_window_action", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="窗口当前关联的行动ID；新单覆盖时旧行动cancelled")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="窗口创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="窗口最后更新的北京时间")


class MonitorSubscription(Base):
    __tablename__ = "ark_customer_monitor_subscriptions"
    __table_args__ = (
        UniqueConstraint("customer_id", "channel", "normalized_url_hash", name="uq_customer_monitor_subscription_url"),
        {"comment": "客户官网与社媒监控订阅表；调度开关独立于采集状态，暂停只改enabled，保留最近采集结果与水位。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="监控订阅ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_monitor_sub_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="订阅所属存储客户ID")
    channel = Column(String(24), nullable=False, comment="监控渠道：website、instagram、facebook、linkedin、news")
    url = Column(String(1000), nullable=False, comment="订阅地址原文；服务端校验HTTPS、DNS、重定向与内容限制后入库")
    normalized_url_hash = Column(HASH64, nullable=False, comment="规范化URL的SHA-256；规范化不去掉有意义路径")
    interval_days = Column(Integer, nullable=False, default=7, comment="采集间隔天数；重点客户周级、普通月级为试点值")
    enabled = Column(Boolean, nullable=False, default=True, comment="调度开关；暂停仅改本字段，不删除历史与水位")
    collection_status = Column(String(16), nullable=False, default="baseline", index=True, comment="采集状态：baseline、active、failed、restricted；active表示最近采集成功")
    baseline_source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id", name="fk_customer_monitor_sub_baseline", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="首次成功采集建立的基线快照来源记录ID")
    last_attempt_at = Column(DateTime, nullable=True, comment="最近一次采集尝试的北京时间")
    last_success_at = Column(DateTime, nullable=True, comment="最近一次采集成功的北京时间；失败保留旧成功时间")
    next_run_at = Column(DateTime, nullable=True, index=True, comment="下一次计划采集的北京时间")
    last_error = Column(String(500), nullable=True, comment="最近失败的可行动脱敏说明；失败显示失败而非无变化")
    row_version = Column(Integer, nullable=False, default=1, comment="乐观锁版本；订阅修改按expected_subscription_version校验")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_monitor_sub_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="创建订阅的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="订阅创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="订阅最后更新的北京时间")


class MonitorEvent(Base):
    __tablename__ = "ark_customer_monitor_events"
    __table_args__ = (
        UniqueConstraint("stable_event_key", name="uq_customer_monitor_event_key"),
        {"comment": "客户监控候选事件表；事件身份由稳定业务主题+发生实例构成，跨渠道同事件归并后多证据挂event_sources。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="监控事件ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_monitor_event_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="事件所属存储客户ID")
    stable_event_key = Column(String(160), nullable=False, comment="稳定事件键：已归并事件身份，不由当前归属或网页标题生成")
    event_type = Column(String(32), nullable=False, index=True, comment="事件类型：store_opening、new_product、channel_change、procurement、risk、general")
    title = Column(String(500), nullable=False, comment="事件标题")
    summary = Column(Text, nullable=True, comment="事件摘要；不复制网页原文")
    occurred_at = Column(DateTime, nullable=True, comment="事件实际发生的北京时间；未知为空")
    discovered_at = Column(DateTime, nullable=True, comment="变化提取发现该事件的北京时间")
    collected_at = Column(DateTime, nullable=True, comment="内容实际采集的北京时间；不以查询时间冒充")
    old_value = Column(Text, nullable=True, comment="变化前内容摘录")
    new_value = Column(Text, nullable=True, comment="变化后内容摘录")
    status = Column(String(16), nullable=False, default="pending", index=True, comment="确认状态：pending、confirmed、ignored")
    confidence = Column(String(16), nullable=False, default="medium", comment="置信度：high、medium、low")
    row_version = Column(Integer, nullable=False, default=1, comment="乐观锁版本；事件决定按expected_event_version校验")
    decided_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_monitor_event_decided_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="确认或忽略的方舟用户ID")
    decided_at = Column(DateTime, nullable=True, comment="完成决定的北京时间")
    decision_reason = Column(String(1000), nullable=True, comment="确认或忽略的原因；忽略必填")
    action_id = Column(BigInteger, ForeignKey("ark_customer_actions.id", name="fk_customer_monitor_event_action", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="确认后一次性生成的关联行动ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="事件最后更新的北京时间")


class MonitorEventSource(Base):
    __tablename__ = "ark_customer_monitor_event_sources"
    __table_args__ = (
        UniqueConstraint("event_id", "source_record_id", name="uq_customer_monitor_event_source"),
        {"comment": "监控事件多源证据链接表；同一事件可挂多个渠道的不可变来源快照。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="事件证据ID")
    event_id = Column(BigInteger, ForeignKey("ark_customer_monitor_events.id", name="fk_customer_monitor_event_source_event", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="所属监控事件ID")
    source_record_id = Column(BigInteger, ForeignKey("ark_customer_source_records.id", name="fk_customer_monitor_event_source_record", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="原始快照来源记录ID")
    evidence_locator = Column(String(500), nullable=True, comment="证据在来源记录内的定位，例如页面区块或URL片段")
    published_at = Column(DateTime, nullable=True, comment="来源内容发布时间的北京时间；未知为空")
    fetched_at = Column(DateTime, nullable=True, comment="方舟采集该来源的北京时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="证据链接创建的北京时间")


class MaintenancePlan(Base):
    __tablename__ = "ark_customer_maintenance_plans"
    __table_args__ = {"comment": "客户维护计划表；六类计划（manual/birthday/holiday/campaign/shipping/sample）共用，typed_payload按schema-migrations第6节校验。"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="维护计划ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_maintenance_plan_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="计划所属存储客户ID")
    plan_type = Column(String(16), nullable=False, index=True, comment="计划类型：manual、birthday、holiday、campaign、shipping、sample")
    title = Column(String(500), nullable=False, comment="计划标题")
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai", comment="计划使用的IANA时区；客户当地时间换算依赖该值")
    recurrence_json = Column(JSON, nullable=True, comment="pcw_recurrence_v1：年度或周期发生规则；生日/节日按发生年实例")
    typed_payload = Column(JSON, nullable=False, comment="按plan_type校验的强类型载荷；见schema-migrations第6节六类payload")
    evidence_json = Column(JSON, nullable=True, comment="计划依据引用：适用日期核验、活动版本或物流关联证据")
    status = Column(String(16), nullable=False, default="active", index=True, comment="计划状态：active、paused、closed")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_maintenance_plan_owner", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="计划负责人；空表示由实时归属服务解析")
    plan_version = Column(Integer, nullable=False, default=1, comment="计划乐观锁版本；修改按expected_plan_version校验")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_maintenance_plan_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="创建计划的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="计划创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="计划最后更新的北京时间")


class MaintenanceOccurrence(Base):
    __tablename__ = "ark_customer_maintenance_occurrences"
    __table_args__ = (
        UniqueConstraint("plan_id", "occurrence_key", name="uq_customer_maintenance_occurrence_key"),
        {"comment": "维护计划实例表；改约只更新日期不换实例身份，实例始终指向当前后续行动。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="计划实例ID")
    plan_id = Column(BigInteger, ForeignKey("ark_customer_maintenance_plans.id", name="fk_customer_maintenance_occ_plan", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="所属维护计划ID")
    occurrence_key = Column(String(160), nullable=False, comment="实例稳定键：计划+发生年/事件/轮次，不含扫描日")
    work_item_id = Column(BigInteger, ForeignKey("ark_customer_work_items.id", name="fk_customer_maintenance_occ_work_item", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="实例关联的经营事项ID")
    current_action_id = Column(BigInteger, ForeignKey("ark_customer_actions.id", name="fk_customer_maintenance_occ_action", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="实例当前指向的行动ID；完成后续在同一事务内更新")
    occurrence_date = Column(Date, nullable=False, index=True, comment="实例发生的北京时间业务日期")
    local_date = Column(Date, nullable=True, comment="客户当地时间的发生日期；辅助提示用")
    status = Column(String(16), nullable=False, default="planned", index=True, comment="实例状态：planned、due、fulfilled、cancelled")
    occurrence_version = Column(Integer, nullable=False, default=1, comment="实例乐观锁版本；完成行动时与行动/事项版本一起原子校验")
    fulfilled_at = Column(DateTime, nullable=True, comment="该次计划完成执行的北京时间；不代表全部客户事项解决")
    fulfilled_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_maintenance_occ_fulfilled_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="完成该次计划的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="实例创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="实例最后更新的北京时间")


class SampleCase(Base):
    __tablename__ = "ark_customer_sample_cases"
    __table_args__ = (
        UniqueConstraint("sample_order_id", "item_set_hash", "feedback_round", name="uq_customer_sample_case_round"),
        {"comment": "样品事项表；阶段ordered→shipped→delivered→awaiting_test→testing→feedback_received→closed，物流只推进发货/签收，测试与反馈须有客户证据。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="样品事项ID")
    customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id", name="fk_customer_sample_case_customer", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="样品事项所属存储客户ID")
    sample_order_id = Column(BigInteger, ForeignKey("ark_customer_orders.id", name="fk_customer_sample_case_order", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="样品订单ID；非sample订单入口拒绝")
    item_set_hash = Column(HASH64, nullable=False, comment="样品明细集合规范哈希；同样品单不同明细集合区分不同事项")
    sample_item_ids_json = Column(JSON, nullable=False, comment="Schema v1样品订单明细ID数组")
    shipment_link_ids_json = Column(JSON, nullable=True, comment="Schema v1关联的物流订单关联ID数组；发出/签收来自物流")
    stage = Column(String(24), nullable=False, default="ordered", index=True, comment="样品阶段：ordered、shipped、delivered、awaiting_test、testing、feedback_received、closed")
    feedback_round = Column(Integer, nullable=False, default=1, comment="反馈轮次；closed为终态，新测试创建新轮次")
    test_planned_date = Column(Date, nullable=True, comment="计划测试业务日期；改约更新本字段并保留历史")
    test_actual_date = Column(Date, nullable=True, comment="客户明确证据的实际测试日期；签收不自动推进")
    feedback_received_at = Column(DateTime, nullable=True, comment="收到客户反馈的北京时间")
    feedback_text = Column(Text, nullable=True, comment="客户反馈内容摘录")
    work_item_id = Column(BigInteger, ForeignKey("ark_customer_work_items.id", name="fk_customer_sample_case_work_item", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="样品事项关联的经营事项ID")
    sample_version = Column(Integer, nullable=False, default=1, comment="样品事项乐观锁版本；改约按expected_sample_version校验")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_sample_case_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="创建样品事项的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="样品事项创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="样品事项最后更新的北京时间")


class ShipmentOrderLink(Base):
    __tablename__ = "ark_customer_shipment_order_links"
    __table_args__ = (
        UniqueConstraint("shipment_id", "order_id", "order_item_id", "link_role", name="uq_customer_shipment_order_link"),
        {"comment": "物流运单与客户订单的显式关联表；支持一票多单和一单多票，收件人相似不作为绑定依据。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="物流订单关联ID")
    shipment_id = Column(BigInteger, ForeignKey("shipment_tracking.id", name="fk_customer_shipment_link_shipment", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="运单跟踪ID（shipment_tracking.id）")
    order_id = Column(BigInteger, ForeignKey("ark_customer_orders.id", name="fk_customer_shipment_link_order", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="方舟客户订单ID")
    order_item_id = Column(BigInteger, ForeignKey("ark_customer_order_items.id", name="fk_customer_shipment_link_item", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=True, comment="方舟订单明细ID；整单关联允许为空")
    linked_quantity = Column(String(64), nullable=True, comment="关联数量Decimal字符串；缺数量为unknown，不猜数值")
    linked_unit = Column(String(32), nullable=True, comment="关联数量单位")
    link_role = Column(String(24), nullable=False, default="full", comment="关联角色：full=整单，partial=部分明细")
    evidence_json = Column(JSON, nullable=True, comment="关联确认依据引用；无明确关联不生成客户提醒")
    state = Column(String(16), nullable=False, default="active", index=True, comment="关联状态：active、revoked")
    link_version = Column(Integer, nullable=False, default=1, comment="关联乐观锁版本")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_shipment_link_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="确认关联的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="关联创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="关联最后更新的北京时间")


class Campaign(Base):
    __tablename__ = "ark_customer_campaigns"
    __table_args__ = {"comment": "新品与优惠活动表；管理员维护有效期、适用产品/市场与排除条件，预览匹配带版本，生成任务前实时重校验。"}

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="活动ID")
    title = Column(String(200), nullable=False, comment="活动标题")
    campaign_type = Column(String(24), nullable=False, index=True, comment="活动类型：new_product、offer")
    product_scope_json = Column(JSON, nullable=False, comment="pcw_campaign_product_scope_v1：适用产品族/型号集合")
    market_scope_json = Column(JSON, nullable=True, comment="pcw_campaign_market_scope_v1：适用市场/客户范围")
    exclusions_json = Column(JSON, nullable=True, comment="pcw_campaign_exclusions_v1：排除条件；DNC、未处理投诉另由治理链抑制")
    content_refs_json = Column(JSON, nullable=True, comment="活动内容引用：素材、文档ID数组")
    effective_from = Column(DateTime, nullable=False, comment="活动生效的北京时间")
    effective_to = Column(DateTime, nullable=False, comment="活动截止的北京时间；过期为派生态expired不落库")
    status = Column(String(16), nullable=False, default="draft", index=True, comment="活动状态：draft、active、paused、closed；关闭不重开")
    audience_rule_version = Column(String(32), nullable=False, default="v1", comment="受众匹配规则版本；匹配快照带版本")
    campaign_version = Column(Integer, nullable=False, default=1, comment="活动乐观锁版本；修改/发布/暂停按expected_campaign_version校验")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_campaign_owner", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="活动负责管理员ID")
    published_at = Column(DateTime, nullable=True, comment="首次发布（draft→active）的北京时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_campaign_created_by", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, comment="创建活动的方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="活动创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="活动最后更新的北京时间")


class OperationReceipt(Base):
    __tablename__ = "ark_customer_operation_receipts"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "operation_scope", "key_hash", name="uq_customer_operation_receipt"),
        {"comment": "写操作幂等回执表；相同键相同请求哈希重放原结果，相同键不同内容返回IDEMPOTENCY_CONFLICT；保留期覆盖客户端最大重试窗口。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="幂等回执ID")
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_operation_receipt_actor", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="操作方舟用户ID；先鉴权再重放")
    operation_scope = Column(String(64), nullable=False, comment="操作范围：路由+资源域稳定标识")
    key_hash = Column(HASH64, nullable=False, comment="Idempotency-Key的SHA-256；不保存原始凭据")
    request_hash = Column(HASH64, nullable=False, comment="规范请求JSON（排序键+紧凑分隔符）的SHA-256")
    result_json = Column(JSON, nullable=False, comment="首次执行成功返回的业务结果快照；重放原样返回")
    status = Column(String(16), nullable=False, default="completed", comment="回执状态：completed、failed")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="回执创建的北京时间")
    expires_at = Column(DateTime, nullable=False, index=True, comment="回执过期的北京时间；过期后可清理")


class CustomerNotificationDelivery(Base):
    __tablename__ = "ark_customer_notification_deliveries"
    __table_args__ = (
        UniqueConstraint("delivery_key", name="uq_customer_notification_delivery_key"),
        {"comment": "行动通知投递记录表（transactional outbox）；投递、已读、实际联系与行动完成四个状态分开，投递前重校验当前归属与联系限制。"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="通知投递ID")
    action_id = Column(BigInteger, ForeignKey("ark_customer_actions.id", name="fk_customer_notification_action", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="通知引用的行动ID；通知已读不改变行动")
    recipient_user_id = Column(USER_ID, ForeignKey("ark_users.id", name="fk_customer_notification_recipient", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False, index=True, comment="接收方舟用户ID")
    channel = Column(String(24), nullable=False, default="in_app", comment="投递渠道：in_app或已配置外部渠道")
    purpose = Column(String(32), nullable=False, comment="通知目的：due、overdue、monitor、maintenance或登记值")
    delivery_key = Column(String(128), nullable=False, comment="投递幂等键：行动+接收人+目的+版本")
    status = Column(String(16), nullable=False, default="pending", index=True, comment="投递状态：pending、delivered、read、failed")
    attempts = Column(Integer, nullable=False, default=0, comment="已尝试投递次数")
    next_retry_at = Column(DateTime, nullable=True, comment="失败补偿下一次重试的北京时间")
    last_error = Column(String(500), nullable=True, comment="最近投递失败的可行动脱敏说明")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="投递记录创建的北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="投递记录最后更新的北京时间")


PCW_MODELS = (
    CustomerWorkItem,
    CustomerEvaluationRun,
    CustomerEvaluationItem,
    CustomerFactReview,
    ConversationBinding,
    ConversationBindingEvent,
    ConversationAnalysisJob,
    OrderAnalysisBatchMap,
    ReorderWindow,
    MonitorSubscription,
    MonitorEvent,
    MonitorEventSource,
    MaintenancePlan,
    MaintenanceOccurrence,
    SampleCase,
    ShipmentOrderLink,
    Campaign,
    OperationReceipt,
    CustomerNotificationDelivery,
)

__all__ = [
    *(model.__name__ for model in PCW_MODELS),
    "PCW_MODELS",
]
