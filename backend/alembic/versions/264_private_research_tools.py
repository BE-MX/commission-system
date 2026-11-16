"""Schedule private research by priority and persist provider calls.

Revision ID: 264_private_research_tools
Revises: 263_customer_owner_claimed_at
"""

import sqlalchemy as sa
from alembic import op

revision = "264_private_research_tools"
down_revision = "263_customer_owner_claimed_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ark_customer_research_tasks",
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False,
                  comment="调度优先级，私海按需背调优先"),
    )
    op.create_index("ix_customer_research_claim_priority", "ark_customer_research_tasks", ["priority", "created_at", "id"])
    table = "ark_customer_research_tool_calls"
    op.create_table(
        table,
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, comment="工具调用编号"),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_customer_research_tasks.id"), nullable=False, comment="所属研究任务"),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("ark_agent_runs.id"), nullable=False, comment="所属研究运行"),
        sa.Column("lease_generation", sa.Integer(), nullable=False, comment="领取该运行时的租约代次"),
        sa.Column("tool", sa.String(20), nullable=False, comment="工具：用户名扫描或付费查询"),
        sa.Column("operation", sa.String(32), nullable=False, comment="工具注册的只读操作"),
        sa.Column("idempotency_key", sa.String(96), nullable=False, comment="任务运行内的调用幂等键"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="规范化请求摘要"),
        sa.Column("target", sa.String(512), nullable=False, comment="经校验的用户名、主页或域名"),
        sa.Column("gap", sa.String(32), comment="触发付费查询的关键缺口"),
        sa.Column("free_search", sa.JSON(), comment="用户名扫描前声明的免费查询与结果"),
        sa.Column("scan_call_id", sa.BigInteger(), sa.ForeignKey(f"{table}.id"), comment="付费查询对应的扫描调用"),
        sa.Column("status", sa.String(24), nullable=False, comment="调用阶段；不确定状态不重发"),
        sa.Column("reserved_microusd", sa.Integer(), nullable=False, comment="调用前预算预占，单位百万分之一美元"),
        sa.Column("charged_microusd", sa.Integer(), comment="已确认的实际花费，空值表示未结算"),
        sa.Column("provider_run_id", sa.String(64), comment="用于只读轮询的供应商运行编号"),
        sa.Column("response_json", sa.JSON(), comment="原始响应与后端提取的待绑定候选"),
        sa.Column("evidence_refs", sa.JSON(), comment="已确认的候选编号和事实写入回执"),
        sa.Column("error_code", sa.String(64), comment="不含凭据或原始请求的错误代码"),
        sa.Column("requested_at", sa.DateTime(), nullable=False, comment="提交请求的北京时间"),
        sa.Column("started_at", sa.DateTime(), comment="开始处理的北京时间"),
        sa.Column("finished_at", sa.DateTime(), comment="完成调用的北京时间"),
        sa.UniqueConstraint("task_id", "run_id", "idempotency_key", name="uq_research_tool_idempotency"),
    )
    op.create_index("ix_research_tool_dispatch", table, ["status", "id"])
    op.create_index("ix_research_tool_spend", table, ["tool", "requested_at"])


def downgrade():
    op.drop_table("ark_customer_research_tool_calls")
    op.drop_index("ix_customer_research_claim_priority", table_name="ark_customer_research_tasks")
    op.drop_column("ark_customer_research_tasks", "priority")
