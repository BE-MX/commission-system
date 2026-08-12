"""Persistent operation audit, scheduler history, and runtime heartbeat state."""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects import mysql

from app.auth import models as _auth_models  # noqa: F401 - register ark_users
from app.core.database import Base

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class OperationAudit(Base):
    __tablename__ = "ark_operation_audits"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    actor_user_id = Column(USER_ID, nullable=True, comment="操作人方舟用户ID")
    actor_name = Column(String(80), nullable=False, comment="操作人名称快照")
    source_ip = Column(String(45), nullable=True, comment="可信代理来源IP")
    instance_id = Column(String(255), nullable=False, comment="目标实例hostname")
    action = Column(String(20), nullable=False, comment="任务控制动作")
    job_id = Column(String(100), nullable=False, comment="稳定任务ID")
    result = Column(String(20), nullable=False, comment="requested/accepted/rejected/failed")
    detail = Column(String(255), nullable=True, comment="非敏感结果摘要")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="操作时间")

    __table_args__ = (
        Index("idx_operations_audit_job_time", "job_id", "created_at"),
        {"comment": "运行中心任务控制审计"},
    )


class SchedulerJobPolicy(Base):
    __tablename__ = "ark_scheduler_job_policies"

    instance_id = Column(String(255), primary_key=True, comment="目标实例hostname")
    job_id = Column(String(100), primary_key=True, comment="稳定任务ID")
    paused = Column(Integer, nullable=False, default=0, server_default="0", comment="1=跨重启保持暂停")
    updated_by = Column(USER_ID, nullable=True, comment="最近操作人方舟用户ID")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = {"comment": "定时任务持久暂停策略"}


class JobRun(Base):
    __tablename__ = "ark_job_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    execution_key = Column(String(64), nullable=False, comment="实例+任务+计划时间的SHA-256键")
    instance_id = Column(String(255), nullable=False, comment="执行实例hostname")
    job_id = Column(String(100), nullable=False, comment="稳定任务ID")
    planned_at = Column(DateTime, nullable=False, comment="计划执行时间UTC")
    started_at = Column(DateTime, nullable=True, comment="实际开始时间UTC")
    finished_at = Column(DateTime, nullable=True, comment="结束时间UTC")
    status = Column(String(20), nullable=False, comment="running/success/failed/missed/skipped")
    duration_ms = Column(Integer, nullable=True, comment="执行耗时毫秒")
    error_digest = Column(String(255), nullable=True, comment="不含异常消息的错误摘要")
    triggered_by = Column(String(80), nullable=False, comment="scheduler或人工操作人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("execution_key", name="uq_job_runs_execution_key"),
        Index("idx_job_runs_job_started", "job_id", "started_at"),
        Index("idx_job_runs_status_started", "status", "started_at"),
        {"comment": "定时任务持久运行结果"},
    )


class RuntimeInstance(Base):
    __tablename__ = "ark_runtime_instances"

    service_id = Column(String(100), primary_key=True, comment="稳定服务ID")
    instance_id = Column(String(255), primary_key=True, comment="云端或本地实例ID")
    service_name = Column(String(120), nullable=False, comment="服务中文名称")
    environment = Column(String(80), nullable=False, comment="运行环境")
    version = Column(String(80), nullable=True, comment="部署版本")
    status = Column(String(20), nullable=False, comment="healthy/degraded")
    started_at = Column(DateTime, nullable=False, comment="实例启动时间UTC")
    last_activity_at = Column(DateTime, nullable=True, comment="最近业务活动时间UTC")
    last_heartbeat_at = Column(DateTime, nullable=False, comment="最近心跳接收时间UTC")
    capabilities = Column(JSON, nullable=True, comment="能力名称数组")
    dependencies = Column(JSON, nullable=True, comment="依赖服务名称数组")
    consecutive_misses = Column(Integer, nullable=False, default=0, server_default="0", comment="连续预计失联周期")
    alerted_at = Column(DateTime, nullable=True, comment="本轮失联告警时间UTC")
    retired_at = Column(DateTime, nullable=True, comment="自动退役时间UTC；恢复心跳后清空")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_runtime_instances_heartbeat", "last_heartbeat_at"),
        {"comment": "跨服务器运行实例最新状态"},
    )


class RuntimeHeartbeat(Base):
    __tablename__ = "ark_runtime_heartbeats"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    service_id = Column(String(100), nullable=False, comment="稳定服务ID")
    instance_id = Column(String(255), nullable=False, comment="上报实例ID")
    reported_status = Column(String(20), nullable=False, comment="上报的healthy/degraded")
    last_activity_at = Column(DateTime, nullable=True, comment="上报的最近业务活动时间UTC")
    received_at = Column(DateTime, nullable=False, server_default=func.now(), comment="心跳接收时间UTC")

    __table_args__ = (
        Index("idx_runtime_heartbeats_service_time", "service_id", "received_at"),
        Index("idx_runtime_heartbeats_received", "received_at"),
        {"comment": "跨服务器运行实例心跳历史"},
    )
