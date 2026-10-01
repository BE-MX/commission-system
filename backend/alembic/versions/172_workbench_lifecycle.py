"""Customer workbench lifecycle and daily admissions. Freeze all item writers before upgrade.

Historical resolved rows stay historical and are excluded from verified result counts.
This snapshot does not import application ORM definitions at migration runtime.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '172_workbench_lifecycle'
down_revision = '171_customer_tag_display_value'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ark_customer_actions') as batch:
        batch.add_column(sa.Column('execution_mode', sa.String(length=16), nullable=True, comment='执行权所属：manual、agent、source_module'))
        batch.add_column(sa.Column('source_task_ref', sa.JSON(), nullable=True, comment='源模块任务domain/id/revision引用；不复制源任务状态'))
        batch.add_column(sa.Column('required_for_resolution', sa.Boolean(), nullable=True, comment='是否属于事项目标必须验收的行动'))
    op.get_bind().execute(sa.text("UPDATE ark_customer_actions SET execution_mode = 'manual', required_for_resolution = 0"))
    with op.batch_alter_table('ark_customer_actions') as batch:
        batch.alter_column('execution_mode', existing_type=sa.String(length=16), nullable=False)
        batch.alter_column('required_for_resolution', existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table('ark_customer_work_items') as batch:
        batch.add_column(sa.Column('goal_type', sa.String(length=32), nullable=True, comment='结果验收目标类型；历史数据沿用work_type并标记未核实'))
        batch.add_column(sa.Column('goal_definition', sa.Text(), nullable=True, comment='需要持续达成的目标及约束'))
        batch.add_column(sa.Column('resolution_policy_version', sa.String(length=32), nullable=True, comment='事项结果验收规则版本'))
        batch.add_column(sa.Column('owner_user_id', mysql.INTEGER(unsigned=True), nullable=True, comment='当前经营负责人；行动执行人独立维护'))
        batch.add_column(sa.Column('waiting_kind', sa.String(length=16), nullable=True, comment='等待对象：customer/colleague/source'))
        batch.add_column(sa.Column('review_at', sa.DateTime(), nullable=True, comment='下一次内部核验的北京时间；不等于再次发送'))
        batch.add_column(sa.Column('pause_reason', sa.String(length=1000), nullable=True, comment='人工暂停的具体原因'))
        batch.add_column(sa.Column('resume_condition', sa.String(length=1000), nullable=True, comment='人工恢复条件；满足条件不自动执行'))
        batch.add_column(sa.Column('paused_state', sa.String(length=24), nullable=True, comment='暂停前的业务状态；恢复时需重新核验'))
        batch.add_column(sa.Column('source_revision', sa.Integer(), nullable=True, comment='事项相关来源的输入版本，失效或新事实递增'))
        batch.add_column(sa.Column('source_valid', sa.Boolean(), nullable=True, comment='当前方案来源是否仍然有效'))
        batch.add_column(sa.Column('result_validity', sa.String(length=24), nullable=True, comment='结果有效性：pending/verified/review_required/legacy_unverified'))
        batch.add_column(sa.Column('resolution_summary', sa.Text(), nullable=True, comment='当前结果摘要；历史结果保留在不可变事件中'))
        batch.add_column(sa.Column('resolution_evidence', sa.JSON(), nullable=True, comment='已校验结果证据引用和版本'))
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE ark_customer_work_items SET goal_type = work_type, resolution_policy_version = 'workbench_v2', source_revision = 1, source_valid = 1, result_validity = CASE WHEN state = 'resolved' THEN 'legacy_unverified' ELSE 'pending' END, resolution_evidence = '[]'"))
    bind.execute(sa.text("UPDATE ark_customer_work_items SET waiting_kind = 'customer', state = 'waiting' WHERE state = 'awaiting_reply'"))
    bind.execute(sa.text("UPDATE ark_customer_work_items SET owner_user_id = (SELECT MIN(user_id) FROM ark_customer_assignments WHERE customer_id = COALESCE((SELECT current_customer_id FROM ark_customer_object_ownerships WHERE object_type = 'work_item' AND object_id = ark_customer_work_items.id), ark_customer_work_items.customer_id) AND assignment_role = 'primary' AND assignment_status = 'active' AND effective_to IS NULL AND (effective_from IS NULL OR effective_from <= CURRENT_TIMESTAMP) HAVING COUNT(*) = 1)"))
    with op.batch_alter_table('ark_customer_work_items') as batch:
        batch.alter_column('goal_type', existing_type=sa.String(length=32), nullable=False)
        batch.alter_column('resolution_policy_version', existing_type=sa.String(length=32), nullable=False)
        batch.alter_column('source_revision', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('source_valid', existing_type=sa.Boolean(), nullable=False)
        batch.alter_column('result_validity', existing_type=sa.String(length=24), nullable=False)
        batch.alter_column('resolution_evidence', existing_type=sa.JSON(), nullable=False)
        batch.create_foreign_key('fk_work_item_owner', 'ark_users', ['owner_user_id'], ['id'], ondelete='RESTRICT', onupdate='RESTRICT')
        batch.create_index('ix_ark_customer_work_items_owner_user_id', ['owner_user_id'])
        batch.create_index('ix_ark_customer_work_items_review_at', ['review_at'])
    op.create_table('ark_customer_work_item_events',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='事件ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('actor_user_id', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=True, comment='操作人；确定性来源消费可为空'),
        sa.Column('event_type', sa.String(length=32), nullable=False, comment='事件类型'),
        sa.Column('from_state', sa.String(length=24), nullable=False, comment='操作前状态'),
        sa.Column('to_state', sa.String(length=24), nullable=False, comment='操作后状态'),
        sa.Column('reason', sa.Text(), nullable=False, comment='原因、实际结果或来源变化说明'),
        sa.Column('evidence_refs', sa.JSON(), nullable=False, comment='已校验且保留版本的证据引用'),
        sa.Column('input_revision', sa.Integer(), nullable=False, comment='本次登记依赖的事项输入版本'),
        sa.Column('item_version', sa.Integer(), nullable=False, comment='事件提交后的事项版本'),
        sa.Column('payload_json', sa.JSON(), nullable=False, comment='事件结构化附加内容，包含历史结果与可逆登记前态'),
        sa.Column('occurred_at', sa.DateTime(), nullable=False, comment='事件发生的北京时间'),
        comment='经营事项不可变事件：状态、结果、重开、纠正与来源版本；不能删除外部事实。',
    )
    op.create_index('ix_ark_customer_work_item_events_event_type', 'ark_customer_work_item_events', ['event_type'])
    op.create_index('ix_ark_customer_work_item_events_item_id', 'ark_customer_work_item_events', ['item_id'])
    op.create_index('ix_ark_customer_work_item_events_occurred_at', 'ark_customer_work_item_events', ['occurred_at'])
    op.create_table('ark_customer_work_item_dependencies',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='依赖ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('source_domain', sa.String(length=24), nullable=False, comment='来源：action/shipment/design等登记域'),
        sa.Column('source_id', sa.String(length=64), nullable=False, comment='源对象持久ID'),
        sa.Column('title', sa.String(length=500), nullable=False, comment='必要交付内容，不复制无权查看的价格或沟通'),
        sa.Column('required', sa.Boolean(), nullable=False, comment='是否必须在解决前验收'),
        sa.Column('observed_status', sa.String(length=32), nullable=False, comment='最近核验状态；不可用不得冒充完成'),
        sa.Column('observed_revision', sa.String(length=64), nullable=True, comment='最近核验的源版本'),
        sa.Column('source_valid', sa.Boolean(), nullable=False, comment='最近观察是否仍有效'),
        sa.Column('observed_at', sa.DateTime(), nullable=True, comment='来源最近核验的北京时间'),
        sa.UniqueConstraint('item_id', 'source_domain', 'source_id', name='uq_work_item_dependency_source'),
        comment='事项所需的责任行动/源任务；源模块仍拥有执行事实写入权。',
    )
    op.create_index('ix_ark_customer_work_item_dependencies_item_id', 'ark_customer_work_item_dependencies', ['item_id'])
    op.create_table('ark_customer_delegations',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='委派ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('actor_user_id', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='执行登记的方舟用户ID'),
        sa.Column('goal', sa.Text(), nullable=False, comment='这次委派要达成的明确目标'),
        sa.Column('scope_json', sa.JSON(), nullable=False, comment='只读/产物准备工具范围与当前授权快照'),
        sa.Column('status', sa.String(length=24), nullable=False, comment='active/waiting/needs_decision/blocked/paused/cancelled/completed'),
        sa.Column('generation', sa.Integer(), nullable=False, comment='取消/恢复令牌；旧代次不得执行新动作'),
        sa.Column('input_revision', sa.Integer(), nullable=False, comment='委派读取的事项来源版本'),
        sa.Column('row_version', sa.Integer(), nullable=False, comment='委派乐观锁版本'),
        sa.Column('review_at', sa.DateTime(), nullable=True, comment='继续核验的北京时间'),
        sa.Column('last_run_id', sa.BigInteger(), sa.ForeignKey('ark_agent_runs.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=True, comment='最近受控运行ID；终态Run不能复活'),
        sa.Column('pause_origin', sa.String(length=16), nullable=True, comment='item或manual；恢复事项不复活独立手动暂停'),
        sa.Column('pause_reason', sa.String(length=1000), nullable=True, comment='暂停、终止或受阻原因'),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False, comment='在途Run停止请求；不是已经停止的证明'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建北京时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新北京时间'),
        comment='事项授权范围内持续委派；多个Run受generation与事项生命周期共同约束。',
    )
    op.create_index('ix_ark_customer_delegations_actor_user_id', 'ark_customer_delegations', ['actor_user_id'])
    op.create_index('ix_ark_customer_delegations_item_id', 'ark_customer_delegations', ['item_id'])
    op.create_index('ix_ark_customer_delegations_status', 'ark_customer_delegations', ['status'])
    op.create_table('ark_customer_daily_plans',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='日计划ID'),
        sa.Column('actor_user_id', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='执行登记的方舟用户ID'),
        sa.Column('business_date', sa.Date(), nullable=False, comment='北京时间业务日期'),
        sa.Column('policy_version', sa.String(length=32), nullable=False, comment='入选策略版本；不构成日计划身份'),
        sa.Column('budget', sa.Integer(), nullable=False, comment='今日普通事项容量，显式增额另有审计'),
        sa.Column('focus', sa.String(length=24), nullable=False, comment='个人经营重点，仅调整同优先级排序'),
        sa.Column('row_version', sa.Integer(), nullable=False, comment='日计划乐观锁版本'),
        sa.Column('initialized', sa.Boolean(), nullable=False, comment='已执行首次普通入选，空清单也不得无限补位'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建北京时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新北京时间'),
        sa.UniqueConstraint('actor_user_id', 'business_date', name='uq_workbench_plan_actor_day'),
        comment='北京业务日普通事项容量账本，完成/策略切换不释放已领取预算。',
    )
    op.create_index('ix_ark_customer_daily_plans_actor_user_id', 'ark_customer_daily_plans', ['actor_user_id'])
    op.create_index('ix_ark_customer_daily_plans_business_date', 'ark_customer_daily_plans', ['business_date'])
    op.create_table('ark_customer_daily_admissions',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='入选ID'),
        sa.Column('plan_id', sa.BigInteger(), sa.ForeignKey('ark_customer_daily_plans.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='日计划ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('admission_type', sa.String(length=24), nullable=False, comment='ordinary/manual_extra/urgent_override'),
        sa.Column('reason', sa.String(length=1000), nullable=False, comment='入选/紧急新增/主动增额的依据'),
        sa.Column('budget_before', sa.Integer(), nullable=False, comment='操作前普通容量'),
        sa.Column('budget_after', sa.Integer(), nullable=False, comment='操作后普通容量'),
        sa.Column('admitted_at', sa.DateTime(), nullable=False, comment='实际入选的北京时间'),
        sa.UniqueConstraint('plan_id', 'item_id', name='uq_workbench_plan_item'),
        comment='当日已领取事项集合；完成、暂停、重开均不退还或重复消费容量。',
    )
    op.create_index('ix_ark_customer_daily_admissions_item_id', 'ark_customer_daily_admissions', ['item_id'])
    op.create_index('ix_ark_customer_daily_admissions_plan_id', 'ark_customer_daily_admissions', ['plan_id'])
    op.create_table('ark_customer_work_item_feedback',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='反馈ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('actor_user_id', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='执行登记的方舟用户ID'),
        sa.Column('target_id', sa.String(length=64), nullable=False, comment='被评价的建议/事实/行动ID'),
        sa.Column('target_revision', sa.Integer(), nullable=False, comment='被评价内容版本'),
        sa.Column('dimension', sa.String(length=24), nullable=False, comment='accuracy/applicability/adoption'),
        sa.Column('decision', sa.String(length=8), nullable=False, comment='yes/no；不是模型整体准确率或经营收益'),
        sa.Column('reason', sa.String(length=1000), nullable=True, comment='反馈原因'),
        sa.Column('evidence_refs', sa.JSON(), nullable=False, comment='纠错依据引用'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新北京时间'),
        sa.UniqueConstraint('item_id', 'target_id', 'target_revision', 'actor_user_id', 'dimension', name='uq_work_item_feedback_dimension'),
        comment='事实准确、建议适用与实际采纳分别评价，重复点击不增加样本量。',
    )
    op.create_index('ix_ark_customer_work_item_feedback_actor_user_id', 'ark_customer_work_item_feedback', ['actor_user_id'])
    op.create_index('ix_ark_customer_work_item_feedback_item_id', 'ark_customer_work_item_feedback', ['item_id'])
    op.create_table('ark_customer_work_item_source_deliveries',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='消费ID'),
        sa.Column('item_id', sa.BigInteger(), sa.ForeignKey('ark_customer_work_items.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False, comment='经营事项ID；通过事项解析当前客户与权限'),
        sa.Column('source_domain', sa.String(length=24), nullable=False, comment='登记来源域'),
        sa.Column('source_event_id', sa.String(length=64), nullable=False, comment='来源持久事件ID'),
        sa.Column('source_revision', sa.Integer(), nullable=False, comment='来源版本，旧版本不得覆盖新事实'),
        sa.Column('processed_at', sa.DateTime(), nullable=False, comment='消费北京时间'),
        sa.UniqueConstraint('source_domain', 'source_event_id', 'source_revision', 'item_id', name='uq_work_item_source_delivery'),
        comment='源事件至少一次消费的版本化去重记录，跨日不创建副本事项。',
    )
    op.create_index('ix_ark_customer_work_item_source_deliveries_item_id', 'ark_customer_work_item_source_deliveries', ['item_id'])


def downgrade():
    raise RuntimeError('Workbench lifecycle contains durable results and admissions; use a schema-compatible forward repair, never delete business audit data')
