"""私海客户工作台（PCW）阶段 0：19 张新表 + ark_customer_actions 扩展 7 列。

设计来源：docs/requirements/private-customer-workbench-prototype/schema-migrations.md
事项以 (business_key, business_cycle) 稳定去重；行动按事项+轮次扩展在
ark_customer_actions。所有外键 ondelete/onupdate=RESTRICT。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "169_pcw_customer_workbench"
# main 已有 168_customer_media_customer_tags（b9e70801）；按 AGENTS.md 查全部分支后改号，
# 合并到 main 前需先 rebase，保证 alembic 单 head。
down_revision = "168_customer_media_customer_tags"
branch_labels = None
depends_on = None

# ark_users.id 是 unsigned int
_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
# SHA-256 hex 摘要
_HASH64 = sa.String(64).with_variant(mysql.CHAR(64), "mysql")


def upgrade() -> None:
    # ── 经营事项主表（被 actions/reorder_windows/maintenance_occurrences/sample_cases 引用，最先建）──
    op.create_table(
        "ark_customer_work_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="经营事项ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="创建时不可变的存储客户ID；当前逻辑客户统一解析ark_customer_object_ownerships"),
        sa.Column("business_key", sa.String(128), nullable=False, comment="稳定业务事件键：来源域持久分配，不含扫描日、负责人或提示词版本"),
        sa.Column("business_cycle", sa.String(64), nullable=False, comment="真实业务周期标识；无新周期证据不得更换以绕过去重"),
        sa.Column("work_type", sa.String(32), nullable=False, comment="事项类型：inquiry、reorder、sample、monitor、maintenance、campaign或登记值"),
        sa.Column("state", sa.String(24), nullable=False, comment="事项状态：open、awaiting_reply、resolved、cancelled"),
        sa.Column("title", sa.String(500), nullable=False, comment="面向业务员的事项标题"),
        sa.Column("context_json", sa.JSON(), nullable=False, comment="pcw_work_item_context_v1：稳定来源引用与最近一次评估上下文快照"),
        sa.Column("next_action_round", sa.Integer(), nullable=False, comment="下一行动轮次；完成未解决行动时在事项行锁内递增"),
        sa.Column("row_version", sa.Integer(), nullable=False, comment="乐观锁版本；完成行动与改约同事务校验"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True, comment="事项解决的北京时间；仅resolved非空"),
        sa.Column("resolved_by", _UINT, nullable=True, comment="解决该事项的方舟用户ID；系统解决允许为空"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="事项创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="事项最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_work_item_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by"], ["ark_users.id"], name="fk_customer_work_item_resolved_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("business_key", "business_cycle", name="uq_customer_work_item_key"),
        comment="私海客户经营事项表；以稳定业务键+真实业务周期跨日去重，扫描日、负责人和规则版本变化不改变事项身份。",
    )
    op.create_index("ix_ark_customer_work_items_customer_id", "ark_customer_work_items", ["customer_id"])
    op.create_index("ix_ark_customer_work_items_state", "ark_customer_work_items", ["state"])
    op.create_index("ix_ark_customer_work_items_customer_state", "ark_customer_work_items", ["customer_id", "state"])

    # ── ark_customer_actions 扩展 7 列 ──
    op.add_column("ark_customer_actions", sa.Column("work_item_id", sa.BigInteger(), nullable=True, comment="私海工作台工作项ID；雷达存量行动为空，PCW 新建行动由业务代码保证必填"))
    op.add_column("ark_customer_actions", sa.Column("action_round", sa.Integer(), nullable=True, comment="同一工作项内的行动轮次，从1开始递增；与work_item_id组合唯一，历史行动为空"))
    op.add_column("ark_customer_actions", sa.Column("parent_action_id", sa.BigInteger(), nullable=True, comment="重试或升级时指向同一工作项内的上一轮行动ID，构成行动链"))
    op.add_column("ark_customer_actions", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1", comment="乐观锁版本号，每次状态变更由业务代码加1，冲突时拒绝写入"))
    op.add_column("ark_customer_actions", sa.Column("original_due_at", sa.DateTime(), nullable=True, comment="首次生成时承诺的业务截止时间，延期后保持不变用于审计"))
    op.add_column("ark_customer_actions", sa.Column("business_due_at", sa.DateTime(), nullable=True, comment="当前生效的业务截止时间，延期时更新"))
    op.add_column("ark_customer_actions", sa.Column("due_provenance", sa.String(24), nullable=True, comment="业务截止时间来源：rule、agent、manual、migration；历史行动无可靠来源可空"))
    op.create_foreign_key("fk_customer_action_work_item", "ark_customer_actions", "ark_customer_work_items", ["work_item_id"], ["id"], ondelete="RESTRICT", onupdate="RESTRICT")
    op.create_foreign_key("fk_customer_action_parent_action", "ark_customer_actions", "ark_customer_actions", ["parent_action_id"], ["id"], ondelete="RESTRICT", onupdate="RESTRICT")
    op.create_unique_constraint("uq_customer_action_item_round", "ark_customer_actions", ["work_item_id", "action_round"])
    op.create_index("ix_ark_customer_actions_work_item_id", "ark_customer_actions", ["work_item_id"])
    op.create_index("ix_ark_customer_actions_business_due_at", "ark_customer_actions", ["business_due_at"])
    op.create_index("ix_ark_customer_actions_owner_status_due", "ark_customer_actions", ["owner_user_id", "status", "business_due_at"])

    # ── 每日客户评估批次 ──
    op.create_table(
        "ark_customer_evaluation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="评估批次ID"),
        sa.Column("run_uid", sa.String(36), nullable=False, comment="对外暴露的批次UUID"),
        sa.Column("business_date", sa.Date(), nullable=False, comment="评估业务日期（北京时间）"),
        sa.Column("rule_version", sa.String(32), nullable=False, comment="评估规则版本"),
        sa.Column("run_kind", sa.String(16), nullable=False, comment="批次类型：scheduled、manual、dry_run"),
        sa.Column("attempt", sa.Integer(), nullable=False, comment="同业务日同范围的重试序号，从1递增"),
        sa.Column("scope_hash", _HASH64, nullable=False, comment="冻结客户范围规范序列化的SHA-256"),
        sa.Column("frozen_scope_json", sa.JSON(), nullable=False, comment="pcw_evaluation_scope_v1：冻结的客户集合、归属版本与输入水位"),
        sa.Column("status", sa.String(16), nullable=False, comment="批次状态：running、completed、failed"),
        sa.Column("expected_count", sa.Integer(), nullable=False, comment="冻结范围内应评估客户数"),
        sa.Column("rule_completed", sa.Integer(), nullable=False, comment="规则评估完成客户数"),
        sa.Column("rule_failed", sa.Integer(), nullable=False, comment="规则评估失败客户数"),
        sa.Column("ai_completed", sa.Integer(), nullable=False, comment="AI增量分析完成客户数"),
        sa.Column("ai_skipped_unchanged", sa.Integer(), nullable=False, comment="输入无变化跳过AI分析客户数"),
        sa.Column("ai_failed", sa.Integer(), nullable=False, comment="AI分析失败客户数；不阻塞规则结果"),
        sa.Column("checkpoint_json", sa.JSON(), nullable=True, comment="分片检查点；用于中断恢复"),
        sa.Column("lease_until", sa.DateTime(), nullable=True, comment="批次执行租约到期的北京时间"),
        sa.Column("triggered_by", _UINT, nullable=True, comment="手动触发用户ID；定时调度允许为空"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="批次创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="批次最后更新的北京时间"),
        sa.ForeignKeyConstraint(["triggered_by"], ["ark_users.id"], name="fk_customer_evaluation_run_triggered_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("run_uid", name="uq_customer_evaluation_run_uid"),
        sa.UniqueConstraint("business_date", "rule_version", "scope_hash", "run_kind", "attempt", name="uq_customer_evaluation_run_attempt"),
        comment="每日客户评估批次表；冻结客户范围、规则版本与输入水位，同日显式重评以run_kind/attempt区分，不伪装自然重跑。",
    )
    op.create_index("ix_ark_customer_evaluation_runs_business_date", "ark_customer_evaluation_runs", ["business_date"])
    op.create_index("ix_ark_customer_evaluation_runs_status", "ark_customer_evaluation_runs", ["status"])

    # ── 评估批次逐客户结果 ──
    op.create_table(
        "ark_customer_evaluation_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="评估明细ID"),
        sa.Column("run_id", sa.BigInteger(), nullable=False, comment="所属评估批次ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="冻结时点的存储客户ID；不加外键，归属变化由逻辑客户解析"),
        sa.Column("assignment_version", sa.String(64), nullable=True, comment="冻结时点归属版本；供漂移审计"),
        sa.Column("input_hash", _HASH64, nullable=False, comment="本客户评估输入规范序列化的SHA-256；无变化时AI跳过"),
        sa.Column("watermarks_json", sa.JSON(), nullable=True, comment="评估时使用的各来源已授权同步水位"),
        sa.Column("rules_status", sa.String(16), nullable=False, comment="规则评估状态：pending、completed、failed"),
        sa.Column("ai_status", sa.String(24), nullable=False, comment="AI分析状态：pending、completed、skipped_unchanged、failed、disabled"),
        sa.Column("error_code", sa.String(64), nullable=True, comment="失败的稳定错误码"),
        sa.Column("error_message", sa.String(500), nullable=True, comment="可行动且脱敏的失败说明"),
        sa.Column("action_counters_json", sa.JSON(), nullable=True, comment="pcw_action_counters_v1：本客户新建/复用/抑制行动计数"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True, comment="失败补偿下一次重试的北京时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="明细创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="明细最后更新的北京时间"),
        sa.ForeignKeyConstraint(["run_id"], ["ark_customer_evaluation_runs.id"], name="fk_customer_evaluation_item_run", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("run_id", "customer_id", name="uq_customer_evaluation_item_customer"),
        comment="评估批次逐客户结果表；customer_id为冻结时点存储客户ID（不加外键，避免合并后悬挂），运行时经逻辑客户解析当前归属。",
    )
    op.create_index("ix_ark_customer_evaluation_items_run_id", "ark_customer_evaluation_items", ["run_id"])
    op.create_index("ix_ark_customer_evaluation_items_customer_id", "ark_customer_evaluation_items", ["customer_id"])
    op.create_index("ix_ark_customer_evaluation_items_retry", "ark_customer_evaluation_items", ["rules_status", "next_retry_at"])

    # ── AI档案建议人工审核 ──
    op.create_table(
        "ark_customer_fact_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="建议审核ID"),
        sa.Column("candidate_fact_id", sa.BigInteger(), nullable=False, comment="被审核的候选事实ID；一条候选事实只审核一次"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="建议所属存储客户ID"),
        sa.Column("status", sa.String(16), nullable=False, comment="审核状态：pending、accepted、rejected、deferred、stale"),
        sa.Column("decision_reason", sa.String(1000), nullable=True, comment="驳回必填的审核原因；采纳可补充说明"),
        sa.Column("defer_until", sa.DateTime(), nullable=True, comment="deferred重新提醒的北京时间"),
        sa.Column("reviewer_user_id", _UINT, nullable=True, comment="完成审核的方舟用户ID"),
        sa.Column("revision_annotation_id", sa.BigInteger(), nullable=True, comment="采纳或编辑采纳产生的Annotation v2修订ID"),
        sa.Column("profile_revision_event_id", sa.BigInteger(), nullable=True, comment="采纳后档案修订事件ID"),
        sa.Column("suggestion_version", sa.Integer(), nullable=False, comment="建议乐观锁版本；同一建议仅一次有效决定"),
        sa.Column("decided_at", sa.DateTime(), nullable=True, comment="完成审核决定的北京时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="建议登记创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="审核状态最后更新的北京时间"),
        sa.ForeignKeyConstraint(["candidate_fact_id"], ["ark_customer_facts.id"], name="fk_customer_fact_review_candidate", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_fact_review_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["ark_users.id"], name="fk_customer_fact_review_reviewer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["revision_annotation_id"], ["ark_customer_annotations.id"], name="fk_customer_fact_review_annotation", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_revision_event_id"], ["ark_customer_events.id"], name="fk_customer_fact_review_event", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("candidate_fact_id", name="uq_customer_fact_review_candidate"),
        comment="AI档案建议人工审核元数据表；只保存审核状态与事实/修订引用，不复制画像内容；绑定或输入变化使旧建议stale而不是重置pending。",
    )
    op.create_index("ix_ark_customer_fact_reviews_customer_id", "ark_customer_fact_reviews", ["customer_id"])
    op.create_index("ix_ark_customer_fact_reviews_status", "ark_customer_fact_reviews", ["status"])
    op.create_index("ix_ark_customer_fact_reviews_status_defer", "ark_customer_fact_reviews", ["status", "defer_until"])

    # ── 源系统会话到客户的当前绑定 ──
    op.create_table(
        "ark_customer_conversation_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="会话绑定ID"),
        sa.Column("source_system", sa.String(24), nullable=False, comment="会话来源系统：whatsapp、alibaba、email或登记值"),
        sa.Column("source_account_key", sa.String(64), nullable=False, comment="源账号命名空间键，不含凭证"),
        sa.Column("source_conversation_id", sa.String(128), nullable=False, comment="源系统内稳定会话ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=True, comment="当前绑定存储客户ID；待绑定为空"),
        sa.Column("contact_id", sa.BigInteger(), nullable=True, comment="绑定时明确的外部联系人ID"),
        sa.Column("projected_conversation_id", sa.BigInteger(), nullable=True, comment="绑定成功后投影的客户会话ID"),
        sa.Column("version", sa.Integer(), nullable=False, comment="绑定版本；未绑定为0，首次绑定成功为1，重绑递增"),
        sa.Column("state", sa.String(16), nullable=False, comment="绑定状态：pending、active、unbound"),
        sa.Column("share_scope", sa.String(24), nullable=False, comment="绑定时预览并确认的共享范围"),
        sa.Column("evidence_json", sa.JSON(), nullable=True, comment="绑定依据引用：verified_contact_point等证据对象ID"),
        sa.Column("bound_by", _UINT, nullable=True, comment="执行绑定的方舟用户ID"),
        sa.Column("bound_at", sa.DateTime(), nullable=True, comment="当前绑定生效的北京时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="绑定记录创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="绑定记录最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_binding_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["ark_customer_contacts.id"], name="fk_customer_binding_contact", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["projected_conversation_id"], ["ark_customer_conversations.id"], name="fk_customer_binding_conversation", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["bound_by"], ["ark_users.id"], name="fk_customer_binding_bound_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("source_system", "source_account_key", "source_conversation_id", name="uq_customer_conversation_binding_source"),
        comment="源系统会话到客户的当前绑定表；源系统+账号+会话ID是稳定身份，重绑历史在binding_events单独留痕。",
    )
    op.create_index("ix_ark_customer_conversation_bindings_customer_id", "ark_customer_conversation_bindings", ["customer_id"])
    op.create_index("ix_ark_customer_conversation_bindings_state", "ark_customer_conversation_bindings", ["state"])

    # ── 会话绑定变化审计 ──
    op.create_table(
        "ark_customer_conversation_binding_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="绑定事件ID"),
        sa.Column("binding_id", sa.BigInteger(), nullable=False, comment="所属绑定记录ID"),
        sa.Column("event_type", sa.String(24), nullable=False, comment="事件类型：bound、rebound、unbound"),
        sa.Column("before_customer_id", sa.BigInteger(), nullable=True, comment="变化前存储客户ID；首次绑定为空"),
        sa.Column("after_customer_id", sa.BigInteger(), nullable=True, comment="变化后存储客户ID；解绑为空"),
        sa.Column("binding_version", sa.Integer(), nullable=False, comment="事件生效后的绑定版本"),
        sa.Column("actor_user_id", _UINT, nullable=False, comment="执行绑定变化的方舟用户ID"),
        sa.Column("reason", sa.String(1000), nullable=True, comment="重绑或解绑的业务原因"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="事件记录的北京时间"),
        sa.ForeignKeyConstraint(["binding_id"], ["ark_customer_conversation_bindings.id"], name="fk_customer_binding_event_binding", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["ark_users.id"], name="fk_customer_binding_event_actor", ondelete="RESTRICT", onupdate="RESTRICT"),
        comment="会话绑定变化的不可变审计表；记录绑定、重绑、解绑的前后客户与版本，重绑须走治理链。",
    )
    op.create_index("ix_ark_customer_conversation_binding_events_binding_id", "ark_customer_conversation_binding_events", ["binding_id"])

    # ── 会话分析异步任务 ──
    op.create_table(
        "ark_customer_conversation_analysis_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="分析任务ID"),
        sa.Column("job_uid", sa.String(36), nullable=False, comment="对外暴露的任务UUID"),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False, comment="被分析的客户会话ID"),
        sa.Column("binding_id", sa.BigInteger(), nullable=True, comment="分析依据的会话绑定ID"),
        sa.Column("binding_version", sa.Integer(), nullable=False, comment="发起分析时校验的绑定版本"),
        sa.Column("analysis_version", sa.Integer(), nullable=False, comment="产生结果在会话内的分析版本号"),
        sa.Column("input_manifest_hash", _HASH64, nullable=False, comment="服务端计算的已授权输入消息清单与水位哈希；不信任客户端哈希"),
        sa.Column("rule_version", sa.String(32), nullable=False, comment="分析规则与提示词版本"),
        sa.Column("status", sa.String(16), nullable=False, comment="任务状态：queued、running、succeeded、failed、stale、cancelled"),
        sa.Column("coverage_json", sa.JSON(), nullable=True, comment="pcw_analysis_coverage_v1：sync_from、sync_to、gaps、attachments_unread"),
        sa.Column("failure_reason", sa.String(500), nullable=True, comment="失败的可行动脱敏说明"),
        sa.Column("result_analysis_id", sa.BigInteger(), nullable=True, comment="成功时写入的会话分析版本ID"),
        sa.Column("created_by", _UINT, nullable=False, comment="发起分析的方舟用户ID"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="任务开始执行的北京时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="任务到达终态的北京时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="任务创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="任务最后更新的北京时间"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ark_customer_conversations.id"], name="fk_customer_analysis_job_conversation", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["binding_id"], ["ark_customer_conversation_bindings.id"], name="fk_customer_analysis_job_binding", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["result_analysis_id"], ["ark_customer_conversation_analyses.id"], name="fk_customer_analysis_job_result", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_analysis_job_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("job_uid", name="uq_customer_analysis_job_uid"),
        sa.UniqueConstraint("conversation_id", "input_manifest_hash", "binding_version", "rule_version", name="uq_customer_analysis_job_input"),
        comment="会话分析异步任务表；相同会话、输入清单哈希、绑定版本与规则版本复用同一任务，失权或重绑使旧派生结果stale。",
    )
    op.create_index("ix_ark_customer_conversation_analysis_jobs_conversation_id", "ark_customer_conversation_analysis_jobs", ["conversation_id"])
    op.create_index("ix_ark_customer_conversation_analysis_jobs_status", "ark_customer_conversation_analysis_jobs", ["status"])

    # ── 订单明细到商业采购批次的版本化映射 ──
    op.create_table(
        "ark_customer_order_batch_map",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="批次映射ID"),
        sa.Column("order_id", sa.BigInteger(), nullable=False, comment="方舟客户订单ID"),
        sa.Column("order_item_id", sa.BigInteger(), nullable=True, comment="方舟订单明细ID；整单级映射允许为空"),
        sa.Column("purchase_batch_key", sa.String(128), nullable=False, comment="商业采购批次稳定键；排除样品、取消、退回失效与拆单重复"),
        sa.Column("product_family", sa.String(128), nullable=False, comment="映射时确定的产品族"),
        sa.Column("mapping_version", sa.String(32), nullable=False, comment="批次归并规则版本；版本更新整体重映射"),
        sa.Column("provenance", sa.String(32), nullable=False, comment="批次来源：explicit=真实批次证据，same_day_merge=同客户同业务日同族低置信归并"),
        sa.Column("quality_status", sa.String(24), nullable=False, comment="映射质量：normal、low_confidence"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="映射写入的北京时间"),
        sa.ForeignKeyConstraint(["order_id"], ["ark_customer_orders.id"], name="fk_customer_order_batch_order", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["order_item_id"], ["ark_customer_order_items.id"], name="fk_customer_order_batch_item", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("order_item_id", "mapping_version", name="uq_customer_order_batch_item"),
        comment="订单明细到商业采购批次与产品族的版本化映射表；无法确定真实批次时标记低置信同日归并，不假装精确。",
    )
    op.create_index("ix_ark_customer_order_batch_map_order_id", "ark_customer_order_batch_map", ["order_id"])
    op.create_index("ix_ark_customer_order_batch_map_purchase_batch_key", "ark_customer_order_batch_map", ["purchase_batch_key"])

    # ── 复购观察窗口 ──
    op.create_table(
        "ark_customer_reorder_windows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="复购窗口ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="窗口所属存储客户ID"),
        sa.Column("product_family", sa.String(128), nullable=False, comment="窗口产品族"),
        sa.Column("anchor_batch_key", sa.String(128), nullable=False, comment="窗口锚定的最近商业采购批次键"),
        sa.Column("occurrence_key", sa.String(160), nullable=False, comment="窗口稳定实例键：产品族+锚定批次+窗口实例；规则版本更新同一窗口不重复建"),
        sa.Column("metric_version", sa.String(32), nullable=False, comment="周期口径版本；旧purchase_cycle_days指标语义不变"),
        sa.Column("sample_refs_json", sa.JSON(), nullable=False, comment="pcw_reorder_samples_v1：参与计算的批次键与间隔天数样本"),
        sa.Column("median_interval_days", sa.Integer(), nullable=True, comment="批次间隔中位数天数；样本不足为空"),
        sa.Column("window_from", sa.Date(), nullable=False, comment="观察窗口开始业务日期（末单+中位数-7天）"),
        sa.Column("window_to", sa.Date(), nullable=False, comment="观察窗口结束业务日期（末单+中位数+7天）"),
        sa.Column("confidence", sa.String(16), nullable=False, comment="窗口置信：regular、irregular、insufficient"),
        sa.Column("state", sa.String(16), nullable=False, comment="窗口状态：open、covered、superseded、closed"),
        sa.Column("work_item_id", sa.BigInteger(), nullable=True, comment="窗口关联的经营事项ID"),
        sa.Column("action_id", sa.BigInteger(), nullable=True, comment="窗口当前关联的行动ID；新单覆盖时旧行动cancelled"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="窗口创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="窗口最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_reorder_window_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["work_item_id"], ["ark_customer_work_items.id"], name="fk_customer_reorder_window_work_item", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["action_id"], ["ark_customer_actions.id"], name="fk_customer_reorder_window_action", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("occurrence_key", name="uq_customer_reorder_window_key"),
        comment="按产品族与商业采购批次计算的复购观察窗口表；窗口是询问采购计划的依据，不表示客户库存即将耗尽。",
    )
    op.create_index("ix_ark_customer_reorder_windows_customer_id", "ark_customer_reorder_windows", ["customer_id"])
    op.create_index("ix_ark_customer_reorder_windows_product_family", "ark_customer_reorder_windows", ["product_family"])
    op.create_index("ix_ark_customer_reorder_windows_state", "ark_customer_reorder_windows", ["state"])

    # ── 客户官网与社媒监控订阅 ──
    op.create_table(
        "ark_customer_monitor_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="监控订阅ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="订阅所属存储客户ID"),
        sa.Column("channel", sa.String(24), nullable=False, comment="监控渠道：website、instagram、facebook、linkedin、news"),
        sa.Column("url", sa.String(1000), nullable=False, comment="订阅地址原文；服务端校验HTTPS、DNS、重定向与内容限制后入库"),
        sa.Column("normalized_url_hash", _HASH64, nullable=False, comment="规范化URL的SHA-256；规范化不去掉有意义路径"),
        sa.Column("interval_days", sa.Integer(), nullable=False, comment="采集间隔天数；重点客户周级、普通月级为试点值"),
        sa.Column("enabled", sa.Boolean(), nullable=False, comment="调度开关；暂停仅改本字段，不删除历史与水位"),
        sa.Column("collection_status", sa.String(16), nullable=False, comment="采集状态：baseline、active、failed、restricted；active表示最近采集成功"),
        sa.Column("baseline_source_record_id", sa.BigInteger(), nullable=True, comment="首次成功采集建立的基线快照来源记录ID"),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True, comment="最近一次采集尝试的北京时间"),
        sa.Column("last_success_at", sa.DateTime(), nullable=True, comment="最近一次采集成功的北京时间；失败保留旧成功时间"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True, comment="下一次计划采集的北京时间"),
        sa.Column("last_error", sa.String(500), nullable=True, comment="最近失败的可行动脱敏说明；失败显示失败而非无变化"),
        sa.Column("row_version", sa.Integer(), nullable=False, comment="乐观锁版本；订阅修改按expected_subscription_version校验"),
        sa.Column("created_by", _UINT, nullable=False, comment="创建订阅的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="订阅创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="订阅最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_monitor_sub_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["baseline_source_record_id"], ["ark_customer_source_records.id"], name="fk_customer_monitor_sub_baseline", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_monitor_sub_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("customer_id", "channel", "normalized_url_hash", name="uq_customer_monitor_subscription_url"),
        comment="客户官网与社媒监控订阅表；调度开关独立于采集状态，暂停只改enabled，保留最近采集结果与水位。",
    )
    op.create_index("ix_ark_customer_monitor_subscriptions_customer_id", "ark_customer_monitor_subscriptions", ["customer_id"])
    op.create_index("ix_ark_customer_monitor_subscriptions_collection_status", "ark_customer_monitor_subscriptions", ["collection_status"])
    op.create_index("ix_ark_customer_monitor_subscriptions_next_run_at", "ark_customer_monitor_subscriptions", ["next_run_at"])

    # ── 客户监控候选事件 ──
    op.create_table(
        "ark_customer_monitor_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="监控事件ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="事件所属存储客户ID"),
        sa.Column("stable_event_key", sa.String(160), nullable=False, comment="稳定事件键：已归并事件身份，不由当前归属或网页标题生成"),
        sa.Column("event_type", sa.String(32), nullable=False, comment="事件类型：store_opening、new_product、channel_change、procurement、risk、general"),
        sa.Column("title", sa.String(500), nullable=False, comment="事件标题"),
        sa.Column("summary", sa.Text(), nullable=True, comment="事件摘要；不复制网页原文"),
        sa.Column("occurred_at", sa.DateTime(), nullable=True, comment="事件实际发生的北京时间；未知为空"),
        sa.Column("discovered_at", sa.DateTime(), nullable=True, comment="变化提取发现该事件的北京时间"),
        sa.Column("collected_at", sa.DateTime(), nullable=True, comment="内容实际采集的北京时间；不以查询时间冒充"),
        sa.Column("old_value", sa.Text(), nullable=True, comment="变化前内容摘录"),
        sa.Column("new_value", sa.Text(), nullable=True, comment="变化后内容摘录"),
        sa.Column("status", sa.String(16), nullable=False, comment="确认状态：pending、confirmed、ignored"),
        sa.Column("confidence", sa.String(16), nullable=False, comment="置信度：high、medium、low"),
        sa.Column("row_version", sa.Integer(), nullable=False, comment="乐观锁版本；事件决定按expected_event_version校验"),
        sa.Column("decided_by", _UINT, nullable=True, comment="确认或忽略的方舟用户ID"),
        sa.Column("decided_at", sa.DateTime(), nullable=True, comment="完成决定的北京时间"),
        sa.Column("decision_reason", sa.String(1000), nullable=True, comment="确认或忽略的原因；忽略必填"),
        sa.Column("action_id", sa.BigInteger(), nullable=True, comment="确认后一次性生成的关联行动ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="事件创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="事件最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_monitor_event_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by"], ["ark_users.id"], name="fk_customer_monitor_event_decided_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["action_id"], ["ark_customer_actions.id"], name="fk_customer_monitor_event_action", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("stable_event_key", name="uq_customer_monitor_event_key"),
        comment="客户监控候选事件表；事件身份由稳定业务主题+发生实例构成，跨渠道同事件归并后多证据挂event_sources。",
    )
    op.create_index("ix_ark_customer_monitor_events_customer_id", "ark_customer_monitor_events", ["customer_id"])
    op.create_index("ix_ark_customer_monitor_events_event_type", "ark_customer_monitor_events", ["event_type"])
    op.create_index("ix_ark_customer_monitor_events_status", "ark_customer_monitor_events", ["status"])

    # ── 监控事件多源证据链接 ──
    op.create_table(
        "ark_customer_monitor_event_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="事件证据ID"),
        sa.Column("event_id", sa.BigInteger(), nullable=False, comment="所属监控事件ID"),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False, comment="原始快照来源记录ID"),
        sa.Column("evidence_locator", sa.String(500), nullable=True, comment="证据在来源记录内的定位，例如页面区块或URL片段"),
        sa.Column("published_at", sa.DateTime(), nullable=True, comment="来源内容发布时间的北京时间；未知为空"),
        sa.Column("fetched_at", sa.DateTime(), nullable=True, comment="方舟采集该来源的北京时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="证据链接创建的北京时间"),
        sa.ForeignKeyConstraint(["event_id"], ["ark_customer_monitor_events.id"], name="fk_customer_monitor_event_source_event", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["source_record_id"], ["ark_customer_source_records.id"], name="fk_customer_monitor_event_source_record", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("event_id", "source_record_id", name="uq_customer_monitor_event_source"),
        comment="监控事件多源证据链接表；同一事件可挂多个渠道的不可变来源快照。",
    )
    op.create_index("ix_ark_customer_monitor_event_sources_event_id", "ark_customer_monitor_event_sources", ["event_id"])

    # ── 客户维护计划 ──
    op.create_table(
        "ark_customer_maintenance_plans",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="维护计划ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="计划所属存储客户ID"),
        sa.Column("plan_type", sa.String(16), nullable=False, comment="计划类型：manual、birthday、holiday、campaign、shipping、sample"),
        sa.Column("title", sa.String(500), nullable=False, comment="计划标题"),
        sa.Column("timezone", sa.String(64), nullable=False, comment="计划使用的IANA时区；客户当地时间换算依赖该值"),
        sa.Column("recurrence_json", sa.JSON(), nullable=True, comment="pcw_recurrence_v1：年度或周期发生规则；生日/节日按发生年实例"),
        sa.Column("typed_payload", sa.JSON(), nullable=False, comment="按plan_type校验的强类型载荷；见schema-migrations第6节六类payload"),
        sa.Column("evidence_json", sa.JSON(), nullable=True, comment="计划依据引用：适用日期核验、活动版本或物流关联证据"),
        sa.Column("status", sa.String(16), nullable=False, comment="计划状态：active、paused、closed"),
        sa.Column("owner_user_id", _UINT, nullable=True, comment="计划负责人；空表示由实时归属服务解析"),
        sa.Column("plan_version", sa.Integer(), nullable=False, comment="计划乐观锁版本；修改按expected_plan_version校验"),
        sa.Column("created_by", _UINT, nullable=False, comment="创建计划的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="计划创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="计划最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_maintenance_plan_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], name="fk_customer_maintenance_plan_owner", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_maintenance_plan_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        comment="客户维护计划表；六类计划（manual/birthday/holiday/campaign/shipping/sample）共用，typed_payload按schema-migrations第6节校验。",
    )
    op.create_index("ix_ark_customer_maintenance_plans_customer_id", "ark_customer_maintenance_plans", ["customer_id"])
    op.create_index("ix_ark_customer_maintenance_plans_plan_type", "ark_customer_maintenance_plans", ["plan_type"])
    op.create_index("ix_ark_customer_maintenance_plans_status", "ark_customer_maintenance_plans", ["status"])

    # ── 维护计划实例 ──
    op.create_table(
        "ark_customer_maintenance_occurrences",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="计划实例ID"),
        sa.Column("plan_id", sa.BigInteger(), nullable=False, comment="所属维护计划ID"),
        sa.Column("occurrence_key", sa.String(160), nullable=False, comment="实例稳定键：计划+发生年/事件/轮次，不含扫描日"),
        sa.Column("work_item_id", sa.BigInteger(), nullable=True, comment="实例关联的经营事项ID"),
        sa.Column("current_action_id", sa.BigInteger(), nullable=True, comment="实例当前指向的行动ID；完成后续在同一事务内更新"),
        sa.Column("occurrence_date", sa.Date(), nullable=False, comment="实例发生的北京时间业务日期"),
        sa.Column("local_date", sa.Date(), nullable=True, comment="客户当地时间的发生日期；辅助提示用"),
        sa.Column("status", sa.String(16), nullable=False, comment="实例状态：planned、due、fulfilled、cancelled"),
        sa.Column("occurrence_version", sa.Integer(), nullable=False, comment="实例乐观锁版本；完成行动时与行动/事项版本一起原子校验"),
        sa.Column("fulfilled_at", sa.DateTime(), nullable=True, comment="该次计划完成执行的北京时间；不代表全部客户事项解决"),
        sa.Column("fulfilled_by", _UINT, nullable=True, comment="完成该次计划的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="实例创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="实例最后更新的北京时间"),
        sa.ForeignKeyConstraint(["plan_id"], ["ark_customer_maintenance_plans.id"], name="fk_customer_maintenance_occ_plan", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["work_item_id"], ["ark_customer_work_items.id"], name="fk_customer_maintenance_occ_work_item", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["current_action_id"], ["ark_customer_actions.id"], name="fk_customer_maintenance_occ_action", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["fulfilled_by"], ["ark_users.id"], name="fk_customer_maintenance_occ_fulfilled_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("plan_id", "occurrence_key", name="uq_customer_maintenance_occurrence_key"),
        comment="维护计划实例表；改约只更新日期不换实例身份，实例始终指向当前后续行动。",
    )
    op.create_index("ix_ark_customer_maintenance_occurrences_plan_id", "ark_customer_maintenance_occurrences", ["plan_id"])
    op.create_index("ix_ark_customer_maintenance_occurrences_occurrence_date", "ark_customer_maintenance_occurrences", ["occurrence_date"])
    op.create_index("ix_ark_customer_maintenance_occurrences_status", "ark_customer_maintenance_occurrences", ["status"])

    # ── 样品事项 ──
    op.create_table(
        "ark_customer_sample_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="样品事项ID"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="样品事项所属存储客户ID"),
        sa.Column("sample_order_id", sa.BigInteger(), nullable=False, comment="样品订单ID；非sample订单入口拒绝"),
        sa.Column("item_set_hash", _HASH64, nullable=False, comment="样品明细集合规范哈希；同样品单不同明细集合区分不同事项"),
        sa.Column("sample_item_ids_json", sa.JSON(), nullable=False, comment="Schema v1样品订单明细ID数组"),
        sa.Column("shipment_link_ids_json", sa.JSON(), nullable=True, comment="Schema v1关联的物流订单关联ID数组；发出/签收来自物流"),
        sa.Column("stage", sa.String(24), nullable=False, comment="样品阶段：ordered、shipped、delivered、awaiting_test、testing、feedback_received、closed"),
        sa.Column("feedback_round", sa.Integer(), nullable=False, comment="反馈轮次；closed为终态，新测试创建新轮次"),
        sa.Column("test_planned_date", sa.Date(), nullable=True, comment="计划测试业务日期；改约更新本字段并保留历史"),
        sa.Column("test_actual_date", sa.Date(), nullable=True, comment="客户明确证据的实际测试日期；签收不自动推进"),
        sa.Column("feedback_received_at", sa.DateTime(), nullable=True, comment="收到客户反馈的北京时间"),
        sa.Column("feedback_text", sa.Text(), nullable=True, comment="客户反馈内容摘录"),
        sa.Column("work_item_id", sa.BigInteger(), nullable=True, comment="样品事项关联的经营事项ID"),
        sa.Column("sample_version", sa.Integer(), nullable=False, comment="样品事项乐观锁版本；改约按expected_sample_version校验"),
        sa.Column("created_by", _UINT, nullable=False, comment="创建样品事项的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="样品事项创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="样品事项最后更新的北京时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["ark_customer_accounts.id"], name="fk_customer_sample_case_customer", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["sample_order_id"], ["ark_customer_orders.id"], name="fk_customer_sample_case_order", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["work_item_id"], ["ark_customer_work_items.id"], name="fk_customer_sample_case_work_item", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_sample_case_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("sample_order_id", "item_set_hash", "feedback_round", name="uq_customer_sample_case_round"),
        comment="样品事项表；阶段ordered→shipped→delivered→awaiting_test→testing→feedback_received→closed，物流只推进发货/签收，测试与反馈须有客户证据。",
    )
    op.create_index("ix_ark_customer_sample_cases_customer_id", "ark_customer_sample_cases", ["customer_id"])
    op.create_index("ix_ark_customer_sample_cases_stage", "ark_customer_sample_cases", ["stage"])

    # ── 物流运单与客户订单的显式关联 ──
    op.create_table(
        "ark_customer_shipment_order_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="物流订单关联ID"),
        sa.Column("shipment_id", sa.BigInteger(), nullable=False, comment="运单跟踪ID（shipment_tracking.id）"),
        sa.Column("order_id", sa.BigInteger(), nullable=False, comment="方舟客户订单ID"),
        sa.Column("order_item_id", sa.BigInteger(), nullable=True, comment="方舟订单明细ID；整单关联允许为空"),
        sa.Column("linked_quantity", sa.String(64), nullable=True, comment="关联数量Decimal字符串；缺数量为unknown，不猜数值"),
        sa.Column("linked_unit", sa.String(32), nullable=True, comment="关联数量单位"),
        sa.Column("link_role", sa.String(24), nullable=False, comment="关联角色：full=整单，partial=部分明细"),
        sa.Column("evidence_json", sa.JSON(), nullable=True, comment="关联确认依据引用；无明确关联不生成客户提醒"),
        sa.Column("state", sa.String(16), nullable=False, comment="关联状态：active、revoked"),
        sa.Column("link_version", sa.Integer(), nullable=False, comment="关联乐观锁版本"),
        sa.Column("created_by", _UINT, nullable=False, comment="确认关联的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="关联创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="关联最后更新的北京时间"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipment_tracking.id"], name="fk_customer_shipment_link_shipment", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["ark_customer_orders.id"], name="fk_customer_shipment_link_order", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["order_item_id"], ["ark_customer_order_items.id"], name="fk_customer_shipment_link_item", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_shipment_link_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("shipment_id", "order_id", "order_item_id", "link_role", name="uq_customer_shipment_order_link"),
        comment="物流运单与客户订单的显式关联表；支持一票多单和一单多票，收件人相似不作为绑定依据。",
    )
    op.create_index("ix_ark_customer_shipment_order_links_shipment_id", "ark_customer_shipment_order_links", ["shipment_id"])
    op.create_index("ix_ark_customer_shipment_order_links_order_id", "ark_customer_shipment_order_links", ["order_id"])
    op.create_index("ix_ark_customer_shipment_order_links_state", "ark_customer_shipment_order_links", ["state"])

    # ── 新品与优惠活动 ──
    op.create_table(
        "ark_customer_campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="活动ID"),
        sa.Column("title", sa.String(200), nullable=False, comment="活动标题"),
        sa.Column("campaign_type", sa.String(24), nullable=False, comment="活动类型：new_product、offer"),
        sa.Column("product_scope_json", sa.JSON(), nullable=False, comment="pcw_campaign_product_scope_v1：适用产品族/型号集合"),
        sa.Column("market_scope_json", sa.JSON(), nullable=True, comment="pcw_campaign_market_scope_v1：适用市场/客户范围"),
        sa.Column("exclusions_json", sa.JSON(), nullable=True, comment="pcw_campaign_exclusions_v1：排除条件；DNC、未处理投诉另由治理链抑制"),
        sa.Column("content_refs_json", sa.JSON(), nullable=True, comment="活动内容引用：素材、文档ID数组"),
        sa.Column("effective_from", sa.DateTime(), nullable=False, comment="活动生效的北京时间"),
        sa.Column("effective_to", sa.DateTime(), nullable=False, comment="活动截止的北京时间；过期为派生态expired不落库"),
        sa.Column("status", sa.String(16), nullable=False, comment="活动状态：draft、active、paused、closed；关闭不重开"),
        sa.Column("audience_rule_version", sa.String(32), nullable=False, comment="受众匹配规则版本；匹配快照带版本"),
        sa.Column("campaign_version", sa.Integer(), nullable=False, comment="活动乐观锁版本；修改/发布/暂停按expected_campaign_version校验"),
        sa.Column("owner_user_id", _UINT, nullable=False, comment="活动负责管理员ID"),
        sa.Column("published_at", sa.DateTime(), nullable=True, comment="首次发布（draft→active）的北京时间"),
        sa.Column("created_by", _UINT, nullable=False, comment="创建活动的方舟用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="活动创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="活动最后更新的北京时间"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], name="fk_customer_campaign_owner", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_customer_campaign_created_by", ondelete="RESTRICT", onupdate="RESTRICT"),
        comment="新品与优惠活动表；管理员维护有效期、适用产品/市场与排除条件，预览匹配带版本，生成任务前实时重校验。",
    )
    op.create_index("ix_ark_customer_campaigns_campaign_type", "ark_customer_campaigns", ["campaign_type"])
    op.create_index("ix_ark_customer_campaigns_status", "ark_customer_campaigns", ["status"])

    # ── 写操作幂等回执 ──
    op.create_table(
        "ark_customer_operation_receipts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="幂等回执ID"),
        sa.Column("actor_user_id", _UINT, nullable=False, comment="操作方舟用户ID；先鉴权再重放"),
        sa.Column("operation_scope", sa.String(64), nullable=False, comment="操作范围：路由+资源域稳定标识"),
        sa.Column("key_hash", _HASH64, nullable=False, comment="Idempotency-Key的SHA-256；不保存原始凭据"),
        sa.Column("request_hash", _HASH64, nullable=False, comment="规范请求JSON（排序键+紧凑分隔符）的SHA-256"),
        sa.Column("result_json", sa.JSON(), nullable=False, comment="首次执行成功返回的业务结果快照；重放原样返回"),
        sa.Column("status", sa.String(16), nullable=False, comment="回执状态：completed、failed"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="回执创建的北京时间"),
        sa.Column("expires_at", sa.DateTime(), nullable=False, comment="回执过期的北京时间；过期后可清理"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["ark_users.id"], name="fk_customer_operation_receipt_actor", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("actor_user_id", "operation_scope", "key_hash", name="uq_customer_operation_receipt"),
        comment="写操作幂等回执表；相同键相同请求哈希重放原结果，相同键不同内容返回IDEMPOTENCY_CONFLICT；保留期覆盖客户端最大重试窗口。",
    )
    op.create_index("ix_ark_customer_operation_receipts_actor_user_id", "ark_customer_operation_receipts", ["actor_user_id"])
    op.create_index("ix_ark_customer_operation_receipts_expires_at", "ark_customer_operation_receipts", ["expires_at"])

    # ── 行动通知投递（transactional outbox）──
    op.create_table(
        "ark_customer_notification_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="通知投递ID"),
        sa.Column("action_id", sa.BigInteger(), nullable=False, comment="通知引用的行动ID；通知已读不改变行动"),
        sa.Column("recipient_user_id", _UINT, nullable=False, comment="接收方舟用户ID"),
        sa.Column("channel", sa.String(24), nullable=False, comment="投递渠道：in_app或已配置外部渠道"),
        sa.Column("purpose", sa.String(32), nullable=False, comment="通知目的：due、overdue、monitor、maintenance或登记值"),
        sa.Column("delivery_key", sa.String(128), nullable=False, comment="投递幂等键：行动+接收人+目的+版本"),
        sa.Column("status", sa.String(16), nullable=False, comment="投递状态：pending、delivered、read、failed"),
        sa.Column("attempts", sa.Integer(), nullable=False, comment="已尝试投递次数"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True, comment="失败补偿下一次重试的北京时间"),
        sa.Column("last_error", sa.String(500), nullable=True, comment="最近投递失败的可行动脱敏说明"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="投递记录创建的北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="投递记录最后更新的北京时间"),
        sa.ForeignKeyConstraint(["action_id"], ["ark_customer_actions.id"], name="fk_customer_notification_action", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["ark_users.id"], name="fk_customer_notification_recipient", ondelete="RESTRICT", onupdate="RESTRICT"),
        sa.UniqueConstraint("delivery_key", name="uq_customer_notification_delivery_key"),
        comment="行动通知投递记录表（transactional outbox）；投递、已读、实际联系与行动完成四个状态分开，投递前重校验当前归属与联系限制。",
    )
    op.create_index("ix_ark_customer_notification_deliveries_action_id", "ark_customer_notification_deliveries", ["action_id"])
    op.create_index("ix_ark_customer_notification_deliveries_recipient_user_id", "ark_customer_notification_deliveries", ["recipient_user_id"])
    op.create_index("ix_ark_customer_notification_deliveries_status", "ark_customer_notification_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("ark_customer_notification_deliveries")
    op.drop_table("ark_customer_operation_receipts")
    op.drop_table("ark_customer_campaigns")
    op.drop_table("ark_customer_shipment_order_links")
    op.drop_table("ark_customer_sample_cases")
    op.drop_table("ark_customer_maintenance_occurrences")
    op.drop_table("ark_customer_maintenance_plans")
    op.drop_table("ark_customer_monitor_event_sources")
    op.drop_table("ark_customer_monitor_events")
    op.drop_table("ark_customer_monitor_subscriptions")
    op.drop_table("ark_customer_reorder_windows")
    op.drop_table("ark_customer_order_batch_map")
    op.drop_table("ark_customer_conversation_analysis_jobs")
    op.drop_table("ark_customer_conversation_binding_events")
    op.drop_table("ark_customer_conversation_bindings")
    op.drop_table("ark_customer_fact_reviews")
    op.drop_table("ark_customer_evaluation_items")
    op.drop_table("ark_customer_evaluation_runs")

    op.drop_constraint("fk_customer_action_work_item", "ark_customer_actions", type_="foreignkey")
    op.drop_constraint("fk_customer_action_parent_action", "ark_customer_actions", type_="foreignkey")
    op.drop_constraint("uq_customer_action_item_round", "ark_customer_actions", type_="unique")
    op.drop_index("ix_ark_customer_actions_owner_status_due", table_name="ark_customer_actions")
    op.drop_index("ix_ark_customer_actions_business_due_at", table_name="ark_customer_actions")
    op.drop_index("ix_ark_customer_actions_work_item_id", table_name="ark_customer_actions")
    op.drop_column("ark_customer_actions", "due_provenance")
    op.drop_column("ark_customer_actions", "business_due_at")
    op.drop_column("ark_customer_actions", "original_due_at")
    op.drop_column("ark_customer_actions", "row_version")
    op.drop_column("ark_customer_actions", "parent_action_id")
    op.drop_column("ark_customer_actions", "action_round")
    op.drop_column("ark_customer_actions", "work_item_id")

    op.drop_table("ark_customer_work_items")
