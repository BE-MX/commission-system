"""Client desk four-table persistence.

Revision ID: 250_client_desk
Revises: 249_followup_revisions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "250_client_desk"
down_revision = "249_followup_revisions"
branch_labels = None
depends_on = None


def upgrade():
    # Freeze a copy of the schema here; do not import application models at migration runtime.
    metadata = sa.MetaData()
    user_type = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
    sa.Table("ark_users", metadata, sa.Column("id", user_type, primary_key=True))
    tables = TABLES
    for name, columns, constraints, indexes in tables:
        table = sa.Table(
            name,
            metadata,
            *[
                sa.Column(
                    n,
                    t,
                    *([extra["computed"]] if "computed" in extra else []),
                    *(
                        [sa.ForeignKey("ark_users.id")]
                        if n in ("user_id", "created_by", "updated_by")
                        else []
                    ),
                    nullable=nullable,
                    primary_key=pk,
                    autoincrement=pk,
                    comment=comment
                )
                for n, t, nullable, pk, comment, extra in columns
            ],
            *[sa.UniqueConstraint(*cols, name=cn) for cn, cols in constraints]
        )
        table.create(op.get_bind())
        for index_name, cols in indexes:
            sa.Index(index_name, *[table.c[c] for c in cols]).create(op.get_bind())


def downgrade():
    for name, _, _, _ in reversed(TABLES):
        op.drop_table(name)


TABLES = [
    (
        "ark_client_desk_states",
        [
            (
                "user_id",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                False,
                False,
                "本人",
                {},
            ),
            ("company_id", sa.BigInteger(), False, False, "OKKI公司", {}),
            ("next_followup_date", sa.Date(), True, False, "人工下次跟进日", {}),
            ("next_followup_remark", sa.Text(), True, False, "下次事项", {}),
            ("manual_version", sa.Integer(), False, False, "人工版本", {}),
            ("brief_md", sa.Text(), True, False, "当前AI画像", {}),
            ("brief_prev_md", sa.Text(), True, False, "上版AI画像", {}),
            ("brief_dependencies", sa.JSON(), True, False, "当前来源依赖", {}),
            ("brief_prev_dependencies", sa.JSON(), True, False, "上版来源依赖", {}),
            (
                "brief_fingerprint",
                sa.String(length=64),
                True,
                False,
                "当前来源指纹",
                {},
            ),
            (
                "brief_prev_fingerprint",
                sa.String(length=64),
                True,
                False,
                "上版来源指纹",
                {},
            ),
            ("brief_at", sa.DateTime(), True, False, "当前画像时间", {}),
            ("brief_prev_at", sa.DateTime(), True, False, "上版画像时间", {}),
            ("last_analyzed_at", sa.DateTime(), True, False, "最近分析", {}),
            ("last_applied_run", sa.JSON(), True, False, "已应用业务日与轮次", {}),
            ("recheck_date", sa.Date(), True, False, "复核日期", {}),
            ("recheck_condition", sa.Text(), True, False, "复核条件", {}),
            ("recheck_count", sa.Integer(), False, False, "无活动复核次数", {}),
            ("activity_watermark", sa.String(length=64), True, False, "活动水位", {}),
            ("rule_cooldowns", sa.JSON(), False, False, "逐规则冷却", {}),
            ("last_touch_at", sa.DateTime(), True, False, "最近可见接触", {}),
            ("last_touch_channel", sa.String(length=24), True, False, "最近渠道", {}),
            ("id", sa.BigInteger(), False, True, "主键", {}),
            ("status", sa.String(length=24), False, False, "状态", {}),
            ("remark", sa.Text(), True, False, "人工备注", {}),
            (
                "created_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "创建人",
                {},
            ),
            (
                "updated_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "修改人",
                {},
            ),
            ("created_at", sa.DateTime(), False, False, "创建北京时间", {}),
            ("updated_at", sa.DateTime(), False, False, "修改北京时间", {}),
        ],
        [("uq_client_desk_state", ("user_id", "company_id"))],
        [("ix_client_desk_due", ("user_id", "next_followup_date"))],
    ),
    (
        "ark_client_desk_followups",
        [
            (
                "user_id",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                False,
                False,
                "本人",
                {},
            ),
            ("company_id", sa.BigInteger(), False, False, "OKKI公司", {}),
            ("channel", sa.String(length=24), False, False, "手工渠道", {}),
            ("content", sa.Text(), False, False, "跟进内容", {}),
            ("happened_at", sa.DateTime(), False, False, "发生北京时间", {}),
            ("suggestion_id", sa.BigInteger(), True, False, "关联建议", {}),
            ("client_request_id", sa.String(length=80), False, False, "请求幂等键", {}),
            ("deleted_at", sa.DateTime(), True, False, "软删除", {}),
            ("id", sa.BigInteger(), False, True, "主键", {}),
            ("status", sa.String(length=24), False, False, "状态", {}),
            ("remark", sa.Text(), True, False, "人工备注", {}),
            (
                "created_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "创建人",
                {},
            ),
            (
                "updated_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "修改人",
                {},
            ),
            ("created_at", sa.DateTime(), False, False, "创建北京时间", {}),
            ("updated_at", sa.DateTime(), False, False, "修改北京时间", {}),
        ],
        [("uq_client_desk_followup_request", ("user_id", "client_request_id"))],
        [
            ("ix_client_desk_followup_user", ("user_id", "happened_at")),
            ("ix_client_desk_followup_company", ("company_id", "happened_at")),
        ],
    ),
    (
        "ark_client_desk_suggestions",
        [
            (
                "user_id",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                False,
                False,
                "本人",
                {},
            ),
            ("company_id", sa.BigInteger(), False, False, "OKKI公司", {}),
            ("biz_date", sa.Date(), False, False, "北京业务日", {}),
            ("run_seq", sa.Integer(), False, False, "0例行1至3手动", {}),
            ("client_request_id", sa.String(length=80), True, False, "手动请求键", {}),
            ("rule_codes", sa.JSON(), False, False, "命中规则", {}),
            ("rule_details", sa.JSON(), False, False, "规则明细", {}),
            (
                "rank_score",
                sa.Numeric(precision=12, scale=4),
                False,
                False,
                "规则分",
                {},
            ),
            ("rule_version", sa.String(length=64), True, False, "规则版本", {}),
            ("snapshot_at", sa.DateTime(), True, False, "快照时间", {}),
            ("snapshot", sa.JSON(), True, False, "确定性快照", {}),
            ("cohort", sa.String(length=24), False, False, "实验分组", {}),
            ("queue_eligible", sa.Boolean(), False, False, "入模资格", {}),
            ("display_eligible", sa.Boolean(), False, False, "展示资格", {}),
            ("disposition", sa.String(length=40), True, False, "资格原因", {}),
            ("lease_token", sa.String(length=64), True, False, "租约令牌", {}),
            ("lease_expires_at", sa.DateTime(), True, False, "租期", {}),
            ("call_started_at", sa.DateTime(), True, False, "可能出站意图", {}),
            ("attempts", sa.Integer(), False, False, "调用次数", {}),
            ("protocol_version", sa.String(length=32), True, False, "协议版本", {}),
            ("protocol_hash", sa.String(length=64), True, False, "协议哈希", {}),
            ("pack_hash", sa.String(length=64), True, False, "资料包哈希", {}),
            ("source_dependencies", sa.JSON(), True, False, "全部来源依赖", {}),
            ("token_usage", sa.JSON(), True, False, "token用量", {}),
            ("error_code", sa.String(length=64), True, False, "无正文错误码", {}),
            ("priority", sa.String(length=16), True, False, "优先级", {}),
            ("reason", sa.Text(), True, False, "原因", {}),
            ("strategy", sa.Text(), True, False, "策略", {}),
            ("check_before_reply", sa.JSON(), True, False, "先查事项", {}),
            ("talking_points", sa.JSON(), True, False, "要点", {}),
            ("draft_message", sa.Text(), True, False, "草稿", {}),
            ("cites", sa.JSON(), True, False, "引用", {}),
            ("grade_hint", sa.JSON(), True, False, "等级建议", {}),
            ("needs_review", sa.Boolean(), False, False, "需核对", {}),
            ("shown_at", sa.DateTime(), True, False, "首次展示", {}),
            ("shown_channel", sa.String(length=24), True, False, "首次渠道", {}),
            ("quality_feedback", sa.String(length=16), True, False, "有用或没用", {}),
            ("feedback_at", sa.DateTime(), True, False, "人工反馈时间", {}),
            ("snoozed_until", sa.Date(), True, False, "稍后日期", {}),
            ("done_at", sa.DateTime(), True, False, "完成发生时间", {}),
            ("done_source", sa.String(length=24), True, False, "完成来源", {}),
            ("report_key", sa.String(length=120), True, False, "冻结早报键", {}),
            ("report_recipient", sa.String(length=128), True, False, "收件人", {}),
            ("report_items", sa.JSON(), True, False, "冻结建议与动作", {}),
            ("report_hash", sa.String(length=64), True, False, "内容摘要", {}),
            ("send_status", sa.String(length=24), True, False, "发送状态", {}),
            ("reserved_at", sa.DateTime(), True, False, "发送意图", {}),
            ("accepted_at", sa.DateTime(), True, False, "受理时间", {}),
            ("opened_at", sa.DateTime(), True, False, "首次有效打开", {}),
            ("report_nonces", sa.JSON(), True, False, "nonce摘要与消费时间", {}),
            ("provider_receipt", sa.String(length=255), True, False, "供应商回执", {}),
            ("id", sa.BigInteger(), False, True, "主键", {}),
            ("status", sa.String(length=24), False, False, "状态", {}),
            ("remark", sa.Text(), True, False, "人工备注", {}),
            (
                "created_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "创建人",
                {},
            ),
            (
                "updated_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "修改人",
                {},
            ),
            ("created_at", sa.DateTime(), False, False, "创建北京时间", {}),
            ("updated_at", sa.DateTime(), False, False, "修改北京时间", {}),
        ],
        [
            (
                "uq_client_desk_suggestion_day",
                ("user_id", "biz_date", "company_id", "run_seq"),
            ),
            ("uq_client_desk_suggestion_request", ("user_id", "client_request_id")),
            (None, ("report_key",)),
        ],
        [
            ("ix_client_desk_rank", ("user_id", "biz_date", "rank_score")),
            ("ix_client_desk_queue", ("status", "queue_eligible", "lease_expires_at")),
        ],
    ),
    (
        "ark_client_desk_wa_links",
        [
            ("account_uid", sa.String(length=80), False, False, "账号", {}),
            ("conversation_uid", sa.String(length=120), False, False, "会话", {}),
            ("company_id", sa.BigInteger(), True, False, "OKKI公司；忽略为空", {}),
            (
                "link_type",
                sa.String(length=16),
                False,
                False,
                "linked/ignored/imported",
                {},
            ),
            ("deleted_at", sa.DateTime(), True, False, "撤销时间", {}),
            (
                "active_slot",
                sa.Integer(),
                True,
                False,
                "有效唯一槽",
                {
                    "computed": sa.Computed(
                        "CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END"
                    )
                },
            ),
            ("id", sa.BigInteger(), False, True, "主键", {}),
            ("status", sa.String(length=24), False, False, "状态", {}),
            ("remark", sa.Text(), True, False, "人工备注", {}),
            (
                "created_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "创建人",
                {},
            ),
            (
                "updated_by",
                sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                True,
                False,
                "修改人",
                {},
            ),
            ("created_at", sa.DateTime(), False, False, "创建北京时间", {}),
            ("updated_at", sa.DateTime(), False, False, "修改北京时间", {}),
        ],
        [
            (
                "uq_client_desk_active_link",
                ("account_uid", "conversation_uid", "active_slot"),
            )
        ],
        [("ix_client_desk_link_company", ("company_id", "active_slot"))],
    ),
]
