"""Persistent operation audit and scheduler policy state."""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, func
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
