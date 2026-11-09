"""Customer followup collaboration, scope and evidence."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "255_followup_collaboration"
down_revision = "254_ai_provider_runtime"
branch_labels = None
depends_on = None

_UINT = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_CUSTOMER = "ark_domestic_customers.id"
_USER = "ark_users.id"
_RESP = "ark_dom_followup_responsibilities"
_SCOPE = "ark_dom_followup_scopes"
_COLLAB = "ark_dom_followup_collaborators"
_HANDOFF = "ark_dom_followup_handoffs"
_EVENT = "ark_dom_followup_collab_events"
_PROFILE = "ark_dom_followup_customer_profiles"
_FOLLOWUP = "ark_domestic_followups"
_TASK = "ark_domestic_followup_tasks"
_DICT_SEEDS = {
    "domestic_followup_result": ("未接通", "未回复", "有效沟通", "已报价", "已寄样", "客户拒绝", "其他"),
    "domestic_followup_obstacle": ("价格", "产品适配", "采购时机", "决策人", "已有供应商", "信任不足", "其他"),
}


def _customer(primary=False):
    return sa.Column("customer_id", sa.Integer(), sa.ForeignKey(_CUSTOMER), nullable=False, primary_key=primary, comment="内贸客户ID")


def _user(name, comment, nullable=True, primary=False):
    return sa.Column(name, _UINT, sa.ForeignKey(_USER), nullable=nullable and not primary, primary_key=primary, comment=comment)


def _seed_dicts():
    dictionary = sa.table("sys_dict", sa.column("type"), sa.column("code"), sa.column("label"),
                          sa.column("sort"), sa.column("is_active"), sa.column("created_at"), sa.column("updated_at"))
    for kind, labels in _DICT_SEEDS.items():
        for index, label in enumerate(labels):
            exists = sa.exists().where(dictionary.c.type == kind, dictionary.c.code == label)
            entry = sa.select(
                sa.literal(kind), sa.literal(label), sa.literal(label), sa.literal(index * 10),
                sa.literal(True), sa.func.current_timestamp(), sa.func.current_timestamp(),
            ).where(~exists)
            op.execute(dictionary.insert().from_select(
                ["type", "code", "label", "sort", "is_active", "created_at", "updated_at"], entry,
            ))


def upgrade():
    op.create_table(
        _RESP, _customer(primary=True), _user("owner_user_id", "当前主要跟进人"),
        sa.Column("status", sa.String(16), nullable=False, comment="当前协作状态"),
        sa.Column("stage", sa.String(24), comment="当前开发进度"),
        sa.Column("version", sa.Integer(), nullable=False, comment="乐观锁版本"),
        sa.Column("last_progress_at", sa.DateTime(), comment="最近有效推进时间（北京时间）"),
        sa.Column("next_plan_date", sa.Date(), comment="当前承诺的下次开发安排（北京日期）"),
        sa.Column("allow_future_contact", sa.Boolean(), comment="停止开发后是否允许未来联系"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="最后更新时间（北京时间）"),
    )
    op.create_index(f"ix_{_RESP}_owner_user_id", _RESP, ["owner_user_id"])
    op.create_table(
        _SCOPE, sa.Column("id", _ID, primary_key=True, comment="主键"), _user("user_id", "授权成员或协作人ID", nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey(_CUSTOMER), comment="内贸客户ID"),
        sa.Column("province", sa.String(64), comment="授权省份，客户级授权为空"), sa.Column("city", sa.String(64), comment="授权城市，空表示省内全市"),
        sa.Column("scope_key", sa.String(132), nullable=False, comment="每个成员的授权去重键（客户或地区）"),
        _user("added_by_user_id", "创建授权或协作关系的用户", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.UniqueConstraint("user_id", "scope_key", name="uq_dom_fu_scope_member"),
    )
    op.create_index(f"ix_{_SCOPE}_customer_id", _SCOPE, ["customer_id"])
    op.create_index("ix_dom_fu_scope_region", _SCOPE, ["province", "city"])
    op.create_table(
        _COLLAB, _customer(primary=True), _user("user_id", "授权成员或协作人ID", primary=True),
        _user("added_by_user_id", "创建授权或协作关系的用户", nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
    )
    op.create_index(f"ix_{_COLLAB}_user_id", _COLLAB, ["user_id"])
    op.create_table(
        _HANDOFF, sa.Column("id", _ID, primary_key=True, comment="主键"), _customer(),
        _user("from_user_id", "原跟进负责人", nullable=False), _user("recipient_user_id", "拟接收的新负责人", nullable=False),
        _user("requester_user_id", "发起交接或接手申请的用户", nullable=False),
        sa.Column("kind", sa.String(12), nullable=False, comment="交接类型（发起交接或申请接手）"), sa.Column("status", sa.String(16), nullable=False, comment="交接单处理状态"),
        sa.Column("pending_marker", sa.Integer(), comment="待处理时为1，其余为空，限制每客户仅一单待处理"),
        sa.Column("responsibility_version", sa.Integer(), nullable=False, comment="交接或事件对应的责任版本"),
        sa.Column("version", sa.Integer(), nullable=False, comment="乐观锁版本"),
        sa.Column("reason", sa.String(500), nullable=False, comment="操作原因"), sa.Column("summary", sa.Text(), comment="经人员确认的交接摘要"),
        sa.Column("obstacle", sa.String(500), comment="当前推进障碍"), sa.Column("commitment", sa.String(500), comment="已经向客户承诺的事项"),
        sa.Column("next_step", sa.String(500), comment="接续推进的建议"), sa.Column("tasks", sa.JSON(), nullable=False, comment="所选待办、处理决定与漂移校验快照"),
        sa.Column("selected_record_ids", sa.JSON(), nullable=False, comment="选入交接包的已确认记录ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"), sa.Column("handled_at", sa.DateTime(), comment="处理时间（北京时间）"),
        _user("handled_by_user_id", "处理交接的用户"), sa.Column("handling_reason", sa.String(500), comment="交接处理说明"),
        sa.UniqueConstraint("customer_id", "pending_marker", name="uq_dom_fu_handoff_pending"),
    )
    op.create_index("ix_dom_fu_handoff_recipient", _HANDOFF, ["recipient_user_id", "status"])
    op.create_table(
        _EVENT, sa.Column("id", _ID, primary_key=True, comment="主键"), _customer(),
        _user("actor_user_id", "执行操作的用户", nullable=False), sa.Column("action", sa.String(24), nullable=False, comment="协作审计事件动作"),
        sa.Column("idempotency_key", sa.String(64), comment="同一客户与操作者的幂等键"), sa.Column("request_hash", sa.String(64), comment="幂等请求的参数哈希"),
        sa.Column("handoff_id", _ID, sa.ForeignKey(f"{_HANDOFF}.id"), comment="关联交接单ID"),
        _user("from_user_id", "原跟进负责人"), _user("to_user_id", "变更后的主要跟进人"),
        sa.Column("responsibility_version", sa.Integer(), nullable=False, comment="交接或事件对应的责任版本"),
        sa.Column("reason", sa.String(500), comment="操作原因"), sa.Column("details", sa.JSON(), comment="事件的结构化补充证据"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
        sa.UniqueConstraint("customer_id", "actor_user_id", "idempotency_key", name="uq_dom_fu_collab_request"),
    )
    op.create_index("ix_dom_fu_collab_customer", _EVENT, ["customer_id", "id"])
    op.create_table(
        _PROFILE, _customer(primary=True), sa.Column("wechat", sa.String(120), comment="客户微信号"),
        sa.Column("deal_status", sa.String(16), comment="人工核实的成交结论"), sa.Column("deal_evidence", sa.Text(), comment="人工核实成交时提供的依据"),
        _user("deal_verified_by_user_id", "成交核实人"), sa.Column("deal_verified_at", sa.DateTime(), comment="成交核实时间（北京时间）"),
    )
    op.add_column(_FOLLOWUP, sa.Column("result_code", sa.String(32), comment="本次跟进结果字典码"))
    op.add_column(_FOLLOWUP, sa.Column("obstacles", sa.JSON(), comment="本次跟进的障碍字典码集合"))
    op.add_column(_FOLLOWUP, sa.Column("evidence_kind", sa.String(24), comment="沟通依据类型"))
    op.add_column(_FOLLOWUP, sa.Column("shared_summary", sa.Text(), comment="经人员确认的共享摘要"))
    op.add_column(_FOLLOWUP, sa.Column("effective_progress", sa.Boolean(), nullable=False, server_default=sa.false(), comment="业务员确认有有效推进"))
    op.add_column(_FOLLOWUP, sa.Column("responsibility_version", sa.Integer(), comment="交接或事件对应的责任版本"))
    op.add_column(_TASK, sa.Column("purpose", sa.String(16), comment="计划用途（开发、维护、其他或历史未分类）"))
    _seed_dicts()


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Followup collaboration downgrade requires a live data-preservation check")
    bind = op.get_bind()
    for table in (_PROFILE, _EVENT, _HANDOFF, _COLLAB, _SCOPE, _RESP):
        if bind.scalar(sa.text(f"SELECT 1 FROM {table} LIMIT 1")):
            raise RuntimeError(f"Followup collaboration data exists in {table}; preserve it before downgrade")
    json_length = "json_array_length" if bind.dialect.name == "sqlite" else "JSON_LENGTH"
    if bind.scalar(sa.text(
        f"SELECT 1 FROM {_FOLLOWUP} WHERE result_code IS NOT NULL OR evidence_kind IS NOT NULL "
        "OR shared_summary IS NOT NULL OR effective_progress = TRUE OR responsibility_version IS NOT NULL "
        "OR (obstacles IS NOT NULL AND LOWER(JSON_TYPE(obstacles)) <> 'null' "
        f"AND {json_length}(obstacles) > 0) LIMIT 1"
    )):
        raise RuntimeError("Structured followup evidence exists; preserve it before downgrade")
    if bind.scalar(sa.text(f"SELECT 1 FROM {_TASK} WHERE purpose IS NOT NULL LIMIT 1")):
        raise RuntimeError("Followup task purposes exist; preserve them before downgrade")
    if bind.scalar(sa.text(
        "SELECT 1 FROM ark_domestic_followup_config WHERE `key` = 'collaboration_pending_handoff_days' LIMIT 1"
    )):
        raise RuntimeError("Followup collaboration settings exist; preserve them before downgrade")
    op.drop_column(_TASK, "purpose")
    for name in ("responsibility_version", "effective_progress", "shared_summary", "evidence_kind", "obstacles",
                 "result_code"):
        op.drop_column(_FOLLOWUP, name)
    for table in (_PROFILE, _EVENT, _HANDOFF, _COLLAB, _SCOPE, _RESP):
        op.drop_table(table)
