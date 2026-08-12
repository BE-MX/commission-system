"""Add persistent job runs and cross-server runtime heartbeats.

Revision ID: 111_runtime_observability
Revises: 110_operations_governance
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "111_runtime_observability"
down_revision = "110_operations_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_job_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("execution_key", sa.String(length=64), nullable=False, comment="实例+任务+计划时间的SHA-256键"),
        sa.Column("instance_id", sa.String(length=255), nullable=False, comment="执行实例hostname"),
        sa.Column("job_id", sa.String(length=100), nullable=False, comment="稳定任务ID"),
        sa.Column("planned_at", sa.DateTime(), nullable=False, comment="计划执行时间UTC"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="实际开始时间UTC"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="结束时间UTC"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="运行结果"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="执行耗时毫秒"),
        sa.Column("error_digest", sa.String(length=255), nullable=True, comment="不含异常消息的错误摘要"),
        sa.Column("triggered_by", sa.String(length=80), nullable=False, comment="scheduler或人工操作人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_key", name="uq_job_runs_execution_key"),
        comment="定时任务持久运行结果",
    )
    op.create_index("idx_job_runs_job_started", "ark_job_runs", ["job_id", "started_at"])
    op.create_index("idx_job_runs_status_started", "ark_job_runs", ["status", "started_at"])

    op.create_table(
        "ark_runtime_instances",
        sa.Column("service_id", sa.String(length=100), nullable=False, comment="稳定服务ID"),
        sa.Column("instance_id", sa.String(length=255), nullable=False, comment="云端或本地实例ID"),
        sa.Column("service_name", sa.String(length=120), nullable=False, comment="服务中文名称"),
        sa.Column("environment", sa.String(length=80), nullable=False, comment="运行环境"),
        sa.Column("version", sa.String(length=80), nullable=True, comment="部署版本"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="healthy/degraded"),
        sa.Column("started_at", sa.DateTime(), nullable=False, comment="实例启动时间UTC"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True, comment="最近业务活动时间UTC"),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False, comment="最近心跳接收时间UTC"),
        sa.Column("capabilities", sa.JSON(), nullable=True, comment="能力名称数组"),
        sa.Column("dependencies", sa.JSON(), nullable=True, comment="依赖服务名称数组"),
        sa.Column("consecutive_misses", sa.Integer(), nullable=False, server_default="0", comment="连续预计失联周期"),
        sa.Column("alerted_at", sa.DateTime(), nullable=True, comment="本轮失联告警时间UTC"),
        sa.Column("retired_at", sa.DateTime(), nullable=True, comment="自动退役时间UTC；恢复心跳后清空"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("service_id", "instance_id"),
        comment="跨服务器运行实例最新状态",
    )
    op.create_index("idx_runtime_instances_heartbeat", "ark_runtime_instances", ["last_heartbeat_at"])

    op.create_table(
        "ark_runtime_heartbeats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("service_id", sa.String(length=100), nullable=False, comment="稳定服务ID"),
        sa.Column("instance_id", sa.String(length=255), nullable=False, comment="上报实例ID"),
        sa.Column("reported_status", sa.String(length=20), nullable=False, comment="上报的healthy/degraded"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True, comment="上报的最近业务活动时间UTC"),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="心跳接收时间UTC"),
        sa.PrimaryKeyConstraint("id"),
        comment="跨服务器运行实例心跳历史",
    )
    op.create_index("idx_runtime_heartbeats_service_time", "ark_runtime_heartbeats", ["service_id", "received_at"])
    op.create_index("idx_runtime_heartbeats_received", "ark_runtime_heartbeats", ["received_at"])


def downgrade() -> None:
    op.drop_index("idx_runtime_heartbeats_received", table_name="ark_runtime_heartbeats")
    op.drop_index("idx_runtime_heartbeats_service_time", table_name="ark_runtime_heartbeats")
    op.drop_table("ark_runtime_heartbeats")
    op.drop_index("idx_runtime_instances_heartbeat", table_name="ark_runtime_instances")
    op.drop_table("ark_runtime_instances")
    op.drop_index("idx_job_runs_status_started", table_name="ark_job_runs")
    op.drop_index("idx_job_runs_job_started", table_name="ark_job_runs")
    op.drop_table("ark_job_runs")
