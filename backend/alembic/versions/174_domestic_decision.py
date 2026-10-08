"""Domestic decision state and explicit permissions; no legacy role grants."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "174_domestic_decision"
down_revision = "173_task_center"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

PERMISSIONS = [
    ("domestic_decision:read", "domestic_decision", "read", "内贸经营决策台", "page"),
    ("domestic_decision:read_all", "domestic_decision", "read_all", "全部内贸客户经营范围", "data"),
    ("domestic_decision_finance:read", "domestic_decision_finance", "read", "内贸经营资金阅读", "action"),
    ("domestic_decision_action:write", "domestic_decision_action", "write", "内贸经营行动记录", "action"),
    ("domestic_decision_report:write", "domestic_decision_report", "write", "内贸经营简报与导出", "action"),
    ("domestic_decision:admin", "domestic_decision", "admin", "内贸分析规则与映射", "action"),
]

def upgrade():
    op.create_table(
        "ark_domestic_analysis_attr_mappings",
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('property', sa.String(32), nullable=False, comment='分析属性'),
        sa.Column('product_type', sa.String(16), nullable=False, server_default='', comment='产品类型；空值表示通用映射'),
        sa.Column('raw_value', sa.String(255), nullable=False, comment='原始值'),
        sa.Column('standard_value', sa.String(255), nullable=False, comment='人工审核的标准值'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1', comment='乐观并发版本'),
        sa.Column('updated_by', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='最后维护人'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间（北京时）'),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间（北京时）'),
        sa.UniqueConstraint('property', 'product_type', 'raw_value', name='uq_dom_analysis_mapping'),
    )
    op.create_table(
        "ark_domestic_analysis_config",
        sa.Column('key', sa.String(64), primary_key=True, comment='配置键'),
        sa.Column('value', sa.JSON, nullable=False, comment='配置值'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1', comment='乐观并发版本'),
        sa.Column('updated_by', USER_ID, sa.ForeignKey('ark_users.id'), nullable=True, comment='最后维护人'),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间（北京时）'),
    )
    op.create_table(
        "ark_domestic_analysis_events",
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('source_event_key', sa.String(64), nullable=False, unique=True, comment='稳定事件幂等键'),
        sa.Column('entity_type', sa.String(24), nullable=False, comment='实体类型'),
        sa.Column('entity_id', sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False, comment='源实体编号；包含大整数账本编号'),
        sa.Column('customer_id', sa.Integer, nullable=True, comment='客户编号'),
        sa.Column('order_id', sa.Integer, nullable=True, comment='订单编号'),
        sa.Column('event_type', sa.String(32), nullable=False, comment='创建、变更或删除'),
        sa.Column('business_date', sa.Date, nullable=True, comment='订单业务日期'),
        sa.Column('before', sa.JSON, nullable=True, comment='变更前必要字段快照'),
        sa.Column('after', sa.JSON, nullable=True, comment='变更后必要字段快照'),
        sa.Column('owner_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=True, comment='归属或创建用户'),
        sa.Column('actor_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=True, comment='业务操作人；自动任务可为空'),
        sa.Column('occurred_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='事件时间（北京时）'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1', comment='乐观并发版本'),
    )
    op.create_index('idx_dom_analysis_event_customer', 'ark_domestic_analysis_events', ['customer_id', 'id'])
    op.create_index('idx_dom_analysis_event_order', 'ark_domestic_analysis_events', ['order_id', 'id'])
    op.create_table(
        "ark_domestic_analysis_runs",
        sa.Column('id', sa.String(36), primary_key=True, comment='主键'),
        sa.Column('owner_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='归属或创建用户'),
        sa.Column('query_json', sa.JSON, nullable=False, comment='验证后的查询条件'),
        sa.Column('result_json', sa.JSON, nullable=False, comment='固定结果快照'),
        sa.Column('scope_customer_ids', sa.JSON, nullable=False, comment='生成时授权客户集合；读取再次校验'),
        sa.Column('includes_finance', sa.Integer, nullable=False, server_default='0', comment='是否包含资金信息'),
        sa.Column('data_version', sa.String(64), nullable=False, comment='事实与口径指纹'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间（北京时）'),
        sa.Column('expires_at', sa.DateTime, nullable=False, comment='交互证据到期时间（北京时）'),
    )
    op.create_index('idx_dom_analysis_run_owner', 'ark_domestic_analysis_runs', ['owner_user_id', 'created_at'])
    op.create_table(
        "ark_domestic_analysis_views",
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('owner_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='归属或创建用户'),
        sa.Column('name', sa.String(80), nullable=False, comment='视图名称'),
        sa.Column('query_json', sa.JSON, nullable=False, comment='验证后的查询条件'),
        sa.Column('time_mode', sa.String(16), nullable=False, server_default='rolling', comment='滚动或固定日期模式'),
        sa.Column('shared', sa.Integer, nullable=False, server_default='0', comment='仅分享查询条件'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1', comment='乐观并发版本'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间（北京时）'),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间（北京时）'),
    )
    op.create_index('idx_dom_analysis_view_owner', 'ark_domestic_analysis_views', ['owner_user_id'])
    op.create_table(
        "ark_domestic_analysis_actions",
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('owner_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='归属或创建用户'),
        sa.Column('assignee_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='行动负责人'),
        sa.Column('customer_id', sa.Integer, sa.ForeignKey('ark_domestic_customers.id'), nullable=False, comment='客户编号'),
        sa.Column('source_key', sa.String(64), nullable=False, comment='行动请求幂等指纹'),
        sa.Column('request_key', sa.String(64), nullable=False, comment='首次认领请求幂等键'),
        sa.Column('request_hash', sa.String(64), nullable=False, comment='首次认领请求内容指纹'),
        sa.Column('rule_key', sa.String(64), nullable=False, comment='触发规则编号'),
        sa.Column('title', sa.String(200), nullable=False, comment='行动标题'),
        sa.Column('evidence_json', sa.JSON, nullable=False, comment='生成时固定证据'),
        sa.Column('trigger_json', sa.JSON, nullable=False, comment='条件指纹与资金权限标识'),
        sa.Column('due_date', sa.Date, nullable=False, comment='期限（北京日期）'),
        sa.Column('status', sa.String(24), nullable=False, server_default='todo', comment='行动或任务状态'),
        sa.Column('result', sa.Text, nullable=True, comment='实际跟进结果说明'),
        sa.Column('result_type', sa.String(32), nullable=True, comment='实际结果分类；不代替订单或入账'),
        sa.Column('condition_changed', sa.Integer, nullable=False, server_default='0', comment='触发条件已变化'),
        sa.Column('version', sa.Integer, nullable=False, server_default='1', comment='乐观并发版本'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间（北京时）'),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间（北京时）'),
        sa.UniqueConstraint('owner_user_id', 'source_key', name='uq_dom_analysis_action_source'),
        sa.UniqueConstraint('owner_user_id', 'request_key', name='uq_dom_analysis_action_request'),
    )
    op.create_index('idx_dom_analysis_action_due', 'ark_domestic_analysis_actions', ['assignee_user_id', 'status', 'due_date'])
    op.create_table(
        "ark_domestic_analysis_jobs",
        sa.Column('id', sa.String(36), primary_key=True, comment='主键'),
        sa.Column('kind', sa.String(16), nullable=False, comment='简报或导出'),
        sa.Column('owner_user_id', USER_ID, sa.ForeignKey('ark_users.id'), nullable=False, comment='归属或创建用户'),
        sa.Column('request_key', sa.String(64), nullable=False, comment='用户请求幂等键'),
        sa.Column('request_hash', sa.String(64), nullable=False, comment='请求内容指纹'),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('ark_domestic_analysis_runs.id'), nullable=False, comment='固定分析快照'),
        sa.Column('status', sa.String(16), nullable=False, server_default='queued', comment='行动或任务状态'),
        sa.Column('source', sa.String(16), nullable=True, comment='AI、规则或快照'),
        sa.Column('result_json', sa.JSON, nullable=True, comment='固定结果快照'),
        sa.Column('error_message', sa.String(500), nullable=True, comment='失败说明'),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间（北京时）'),
        sa.Column('started_at', sa.DateTime, nullable=True, comment='开始时间（北京时）'),
        sa.Column('finished_at', sa.DateTime, nullable=True, comment='结束时间（北京时）'),
        sa.UniqueConstraint('owner_user_id', 'kind', 'request_key', name='uq_dom_analysis_job_request'),
    )
    op.create_index('idx_dom_analysis_job_status', 'ark_domestic_analysis_jobs', ['status', 'created_at'])
    permissions = sa.table("ark_permissions", sa.column("code"), sa.column("module"), sa.column("action"), sa.column("label"), sa.column("kind"), sa.column("is_legacy"), sa.column("sort"))
    bind = op.get_bind()
    for code, module, action, label, kind in PERMISSIONS:
        if not bind.execute(sa.select(permissions.c.code).where(permissions.c.code == code)).first():
            bind.execute(permissions.insert().values(code=code, module=module, action=action, label=label, kind=kind, is_legacy=0, sort=0))
    config = sa.table("ark_domestic_analysis_config", sa.column("key"), sa.column("value", sa.JSON), sa.column("version"))
    bind.execute(config.insert().values(key="ai_hypothesis_options", version=1, value=[
        {"code": "purchase_plan", "label": "可能与门店集中采购计划有关，需要核对采购背景"},
        {"code": "product_mix", "label": "可能与门店产品结构或服务需求变化有关，需要询问实际需求"},
        {"code": "record_gap", "label": "也可能受到历史记录或属性覆盖变化影响，需要核对证据完整性"},
        {"code": "service_context", "label": "可能存在尚未记录的服务反馈，需要先了解门店情况"},
    ]))


def downgrade():
    raise RuntimeError("Domestic decision snapshots, actions and transaction events are audit data; use a forward migration")
