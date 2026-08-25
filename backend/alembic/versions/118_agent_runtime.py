"""add governed agent runtime control plane

Revision ID: 118_agent_runtime
Revises: 117_sales_pool_dedupe
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "118_agent_runtime"
down_revision = "117_sales_pool_dedupe"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
LONG_TEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
MEDIUM_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in _inspector().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {item["name"] for item in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_table("ark_agent_profiles"):
        op.create_table(
            "ark_agent_profiles",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("profile_key", sa.String(64), nullable=False, comment="稳定Profile业务键"),
            sa.Column("version", sa.Integer(), nullable=False, comment="不可变配置版本"),
            sa.Column("name", sa.String(120), nullable=False, comment="显示名称"),
            sa.Column("description", sa.String(500), nullable=True, comment="能力与边界说明"),
            sa.Column("runtime", sa.String(32), nullable=False, comment="dsh/openclaw/native"),
            sa.Column("mode", sa.String(20), nullable=False, comment="interactive/scheduled/shadow"),
            sa.Column("model_preset", sa.String(64), nullable=False, comment="方舟AI Preset名称"),
            sa.Column("system_prompt", LONG_TEXT, nullable=False, comment="该版本系统提示词"),
            sa.Column("prompt_hash", sa.String(64), nullable=False, comment="系统提示词SHA-256"),
            sa.Column("skill_manifest", sa.JSON(), nullable=False, comment="Skill及版本清单"),
            sa.Column("tool_allowlist", sa.JSON(), nullable=False, comment="允许工具名列表"),
            sa.Column("limits_json", sa.JSON(), nullable=False, comment="步数/并发/Token/超时限制"),
            sa.Column("policy_json", sa.JSON(), nullable=False, comment="数据与执行策略"),
            sa.Column("output_schema", sa.JSON(), nullable=False, comment="成果JSON Schema"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active", comment="active/inactive"),
            sa.Column("created_by", USER_ID, nullable=True, comment="创建人方舟用户ID"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], name="fk_agent_profile_creator", ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("profile_key", "version", name="uq_agent_profile_key_version"),
            comment="Agent不可变配置版本",
        )
        op.create_index("idx_agent_profile_status", "ark_agent_profiles", ["status", "profile_key", "version"])

    if not _has_table("ark_agent_sessions"):
        op.create_table(
            "ark_agent_sessions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("owner_user_id", USER_ID, nullable=False, comment="会话所有人"),
            sa.Column("profile_id", sa.BigInteger(), nullable=False, comment="固定Profile版本"),
            sa.Column("title", sa.String(255), nullable=False, comment="会话标题"),
            sa.Column("context_type", sa.String(40), nullable=True, comment="customer/order/search_job等"),
            sa.Column("context_id", sa.String(128), nullable=True, comment="业务对象稳定ID"),
            sa.Column("runtime_session_id", sa.String(255), nullable=True, comment="Runtime会话ID"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active", comment="active/archived"),
            sa.Column("last_event_seq", sa.Integer(), nullable=False, server_default="0", comment="会话最新事件序号投影"),
            sa.Column("summary_json", sa.JSON(), nullable=True, comment="脱敏会话摘要投影"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], name="fk_agent_session_owner", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["profile_id"], ["ark_agent_profiles.id"], name="fk_agent_session_profile", ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            comment="Agent业务会话",
        )
        op.create_index("idx_agent_session_owner", "ark_agent_sessions", ["owner_user_id", "status", "updated_at"])
        op.create_index("idx_agent_session_context", "ark_agent_sessions", ["context_type", "context_id"])

    if not _has_table("ark_agent_runs"):
        op.create_table(
            "ark_agent_runs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("session_id", sa.BigInteger(), nullable=False, comment="所属Agent会话"),
            sa.Column("profile_id", sa.BigInteger(), nullable=False, comment="执行时固定Profile版本"),
            sa.Column("owner_user_id", USER_ID, nullable=False, comment="任务数据权限主体"),
            sa.Column("idempotency_key", sa.String(128), nullable=False, comment="用户范围内创建幂等键"),
            sa.Column("trigger_type", sa.String(32), nullable=False, comment="user/business_event/schedule/shadow"),
            sa.Column("source_runtime", sa.String(32), nullable=False, comment="dsh/openclaw/native"),
            sa.Column("mode", sa.String(20), nullable=False, comment="interactive/scheduled/shadow"),
            sa.Column("business_ref_type", sa.String(40), nullable=True, comment="客户/订单/搜索任务等引用类型"),
            sa.Column("business_ref_id", sa.String(128), nullable=True, comment="业务引用稳定ID"),
            sa.Column("input_json", sa.JSON(), nullable=False, comment="用户输入与安全参数"),
            sa.Column("context_snapshot", sa.JSON(), nullable=False, comment="权限与业务上下文冻结快照"),
            sa.Column("status", sa.String(24), nullable=False, server_default="queued", comment="Agent Run状态"),
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false(), comment="用户请求取消"),
            sa.Column("claimed_by", sa.String(128), nullable=True, comment="Worker实例ID"),
            sa.Column("lease_token_hash", sa.String(64), nullable=True, comment="租约令牌SHA-256"),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True, comment="租约过期时间"),
            sa.Column("runtime_run_id", sa.String(255), nullable=True, comment="Runtime任务ID"),
            sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0", comment="领取次数"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3", comment="最大领取次数"),
            sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0", comment="已使用Agent步骤"),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0", comment="输入Token"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0", comment="输出Token"),
            sa.Column("cost_usd", sa.Numeric(14, 6), nullable=False, server_default="0", comment="估算模型成本USD"),
            sa.Column("error_code", sa.String(64), nullable=True, comment="稳定错误码"),
            sa.Column("error_message", sa.String(1000), nullable=True, comment="脱敏可行动错误"),
            sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始执行时间"),
            sa.Column("completed_at", sa.DateTime(), nullable=True, comment="进入终态时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["session_id"], ["ark_agent_sessions.id"], name="fk_agent_run_session", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["profile_id"], ["ark_agent_profiles.id"], name="fk_agent_run_profile", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], name="fk_agent_run_owner", ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_agent_run_owner_idem"),
            comment="Agent单次任务与租约状态",
        )
        op.create_index("idx_agent_run_claim", "ark_agent_runs", ["status", "lease_expires_at", "created_at"])
        op.create_index("idx_agent_run_owner", "ark_agent_runs", ["owner_user_id", "updated_at"])
        op.create_index("idx_agent_run_business", "ark_agent_runs", ["business_ref_type", "business_ref_id"])

    if not _has_table("ark_agent_events"):
        op.create_table(
            "ark_agent_events",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("run_id", sa.BigInteger(), nullable=False, comment="Agent Run"),
            sa.Column("session_id", sa.BigInteger(), nullable=False, comment="Agent Session"),
            sa.Column("sequence_no", sa.Integer(), nullable=False, comment="Run内单调递增序号"),
            sa.Column("event_id", sa.String(128), nullable=False, comment="Runtime幂等事件ID"),
            sa.Column("event_type", sa.String(64), nullable=False, comment="标准事件类型"),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1", comment="事件Schema版本"),
            sa.Column("actor_type", sa.String(32), nullable=False, comment="user/control_plane/runtime/model/tool"),
            sa.Column("visibility", sa.String(16), nullable=False, server_default="user", comment="user/admin/secret"),
            sa.Column("payload_json", sa.JSON(), nullable=False, comment="标准化脱敏载荷"),
            sa.Column("raw_payload_cipher", MEDIUM_TEXT, nullable=True, comment="可选原始载荷密文"),
            sa.Column("source_event_ids", sa.JSON(), nullable=False, comment="来源事件ID列表"),
            sa.Column("payload_sha256", sa.String(64), nullable=False, comment="标准化载荷SHA-256"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="事件时间"),
            sa.ForeignKeyConstraint(["run_id"], ["ark_agent_runs.id"], name="fk_agent_event_run", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["session_id"], ["ark_agent_sessions.id"], name="fk_agent_event_session", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "sequence_no", name="uq_agent_event_run_seq"),
            sa.UniqueConstraint("run_id", "event_id", name="uq_agent_event_run_event"),
            comment="Agent追加式运行事件",
        )
        op.create_index("idx_agent_event_session", "ark_agent_events", ["session_id", "created_at"])
        op.create_index("idx_agent_event_type", "ark_agent_events", ["event_type", "created_at"])

    if not _has_table("ark_agent_artifacts"):
        op.create_table(
            "ark_agent_artifacts",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("run_id", sa.BigInteger(), nullable=False, comment="来源Agent Run"),
            sa.Column("artifact_type", sa.String(64), nullable=False, comment="copilot_answer/customer_action_card/shadow_candidates等"),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1", comment="成果Schema版本"),
            sa.Column("title", sa.String(255), nullable=True, comment="成果标题"),
            sa.Column("content_json", sa.JSON(), nullable=False, comment="结构化成果"),
            sa.Column("evidence_json", sa.JSON(), nullable=False, comment="可验证证据引用"),
            sa.Column("content_sha256", sa.String(64), nullable=False, comment="规范化成果SHA-256"),
            sa.Column("validation_status", sa.String(20), nullable=False, server_default="pending", comment="pending/valid/invalid"),
            sa.Column("validation_errors", sa.JSON(), nullable=False, comment="结构或证据校验错误"),
            sa.Column("decision_status", sa.String(20), nullable=False, server_default="draft", comment="draft/accepted/rejected"),
            sa.Column("decided_by", USER_ID, nullable=True, comment="接受或拒绝用户"),
            sa.Column("decided_at", sa.DateTime(), nullable=True, comment="决策时间"),
            sa.Column("feedback_note", sa.String(1000), nullable=True, comment="用户反馈"),
            sa.Column("business_ref_type", sa.String(40), nullable=True, comment="投影后的业务引用类型"),
            sa.Column("business_ref_id", sa.String(128), nullable=True, comment="投影后的业务引用ID"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["run_id"], ["ark_agent_runs.id"], name="fk_agent_artifact_run", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["decided_by"], ["ark_users.id"], name="fk_agent_artifact_decider", ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "artifact_type", "content_sha256", name="uq_agent_artifact_content"),
            comment="Agent结构化成果与业务决策",
        )
        op.create_index("idx_agent_artifact_run", "ark_agent_artifacts", ["run_id", "artifact_type"])
        op.create_index("idx_agent_artifact_decision", "ark_agent_artifacts", ["decision_status", "created_at"])

    if _has_table("ark_customer_actions"):
        if not _has_column("ark_customer_actions", "source_type"):
            op.add_column("ark_customer_actions", sa.Column("source_type", sa.String(20), nullable=False, server_default="rule", comment="rule/dsh/manual"))
        if not _has_column("ark_customer_actions", "source_run_id"):
            op.add_column("ark_customer_actions", sa.Column("source_run_id", sa.BigInteger(), nullable=True, comment="来源Agent Run ID"))
        if not _has_column("ark_customer_actions", "source_fingerprint"):
            op.add_column("ark_customer_actions", sa.Column("source_fingerprint", sa.String(64), nullable=True, comment="行动生成幂等指纹"))
        if not _has_column("ark_customer_actions", "policy_version"):
            op.add_column("ark_customer_actions", sa.Column("policy_version", sa.String(32), nullable=True, comment="行动策略版本"))
        if not _has_column("ark_customer_actions", "evidence_status"):
            op.add_column("ark_customer_actions", sa.Column("evidence_status", sa.String(20), nullable=False, server_default="unverified", comment="unverified/valid/invalid"))
        if not _has_column("ark_customer_actions", "generated_at"):
            op.add_column("ark_customer_actions", sa.Column("generated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="本版本生成时间"))
        if not _has_index("ark_customer_actions", "uq_customer_action_fingerprint"):
            op.create_index("uq_customer_action_fingerprint", "ark_customer_actions", ["source_fingerprint"], unique=True)
        if not _has_index("ark_customer_actions", "idx_customer_action_run"):
            op.create_index("idx_customer_action_run", "ark_customer_actions", ["source_run_id"])


def downgrade() -> None:
    if _has_table("ark_customer_actions"):
        if _has_index("ark_customer_actions", "idx_customer_action_run"):
            op.drop_index("idx_customer_action_run", table_name="ark_customer_actions")
        if _has_index("ark_customer_actions", "uq_customer_action_fingerprint"):
            op.drop_index("uq_customer_action_fingerprint", table_name="ark_customer_actions")
        for column in (
            "generated_at",
            "evidence_status",
            "policy_version",
            "source_fingerprint",
            "source_run_id",
            "source_type",
        ):
            if _has_column("ark_customer_actions", column):
                op.drop_column("ark_customer_actions", column)
    for table in (
        "ark_agent_artifacts",
        "ark_agent_events",
        "ark_agent_runs",
        "ark_agent_sessions",
        "ark_agent_profiles",
    ):
        if _has_table(table):
            op.drop_table(table)
