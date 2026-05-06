"""设计预约 — SQLAlchemy 数据模型"""

from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Text, JSON, Boolean,
    Enum as SAEnum, Index, UniqueConstraint, ForeignKey, CHAR,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class DesignDesigner(Base):
    __tablename__ = "design_designer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="设计师姓名")
    dingtalk_id = Column(String(64), nullable=True, comment="钉钉ID")
    email = Column(String(128), nullable=True, comment="邮箱")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1", comment="是否启用")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")


class DesignScheduleRequest(Base):
    __tablename__ = "design_schedule_request"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_no = Column(String(32), nullable=False, unique=True, comment="申请单号")
    customer_name = Column(String(128), nullable=False, comment="客户名称")
    customer_level = Column(String(64), nullable=True, comment="客户等级(字典code)")
    salesperson_id = Column(Integer, nullable=False, comment="业务员ID")
    salesperson_name = Column(String(64), nullable=False, comment="业务员姓名")
    shoot_type = Column(
        String(255), nullable=False,
        comment="拍摄类型(字典code，多选用逗号分隔)",
    )
    shoot_type_remark = Column(String(256), nullable=True, comment="拍摄类型备注")
    expect_start_date = Column(Date, nullable=False, comment="期望开始日期")
    expect_start_period = Column(String(2), nullable=True, comment="期望开始时段(am/pm)")
    expect_end_date = Column(Date, nullable=False, comment="期望结束日期")
    expect_end_period = Column(String(2), nullable=True, comment="期望结束时段(am/pm)")
    priority = Column(
        SAEnum("normal", "urgent", name="priority_enum"),
        nullable=False, default="normal", server_default="normal", comment="优先级",
    )
    remark = Column(Text, nullable=True, comment="备注")
    status = Column(
        SAEnum("pending_audit", "pending_design", "scheduled", "in_progress",
               "completed", "rejected", "cancelled", name="request_status_enum"),
        nullable=False, default="pending_audit", server_default="pending_audit",
        comment="状态",
    )
    conflict_detail = Column(JSON, nullable=True, comment="冲突详情")
    assigned_designer_id = Column(Integer, nullable=True, comment="指派设计师ID")
    actual_start_date = Column(Date, nullable=True, comment="实际开始日期")
    actual_start_period = Column(String(2), nullable=True, comment="实际开始时段(am/pm)")
    actual_end_date = Column(Date, nullable=True, comment="实际结束日期")
    actual_end_period = Column(String(2), nullable=True, comment="实际结束时段(am/pm)")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    tasks = relationship("DesignScheduleTask", back_populates="request", lazy="selectin")

    __table_args__ = (
        Index("uk_request_no", "request_no", unique=True),
        Index("idx_salesperson_id", "salesperson_id"),
        Index("idx_status", "status"),
        Index("idx_expect_date", "expect_start_date", "expect_end_date"),
        Index("idx_created_at", "created_at"),
    )


class DesignScheduleTask(Base):
    __tablename__ = "design_schedule_task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("design_schedule_request.id"), nullable=False, comment="关联申请ID")
    task_no = Column(String(32), nullable=False, unique=True, comment="任务编号")
    designer_id = Column(Integer, nullable=False, comment="设计师ID")
    task_name = Column(String(256), nullable=True, comment="任务名称")
    customer_name = Column(String(128), nullable=True, comment="客户名称")
    salesperson_name = Column(String(64), nullable=True, comment="业务员姓名")
    shoot_type = Column(
        String(255), nullable=True,
        comment="拍摄类型(字典code，多选用逗号分隔)",
    )
    priority = Column(
        SAEnum("normal", "urgent", name="priority_enum"),
        nullable=True, comment="优先级",
    )
    plan_start_date = Column(Date, nullable=True, comment="计划开始日期")
    plan_start_period = Column(String(2), nullable=True, comment="计划开始时段(am/pm)")
    plan_end_date = Column(Date, nullable=True, comment="计划结束日期")
    plan_end_period = Column(String(2), nullable=True, comment="计划结束时段(am/pm)")
    actual_start_date = Column(Date, nullable=True, comment="实际开始日期")
    actual_start_period = Column(String(2), nullable=True, comment="实际开始时段(am/pm)")
    actual_end_date = Column(Date, nullable=True, comment="实际结束日期")
    actual_end_period = Column(String(2), nullable=True, comment="实际结束时段(am/pm)")
    status = Column(
        SAEnum("pending_design", "scheduled", "in_progress", "completed", "cancelled",
               name="task_status_enum"),
        nullable=False, default="pending_design", server_default="pending_design",
        comment="任务状态",
    )
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    request = relationship("DesignScheduleRequest", back_populates="tasks")

    __table_args__ = (
        Index("uk_task_no", "task_no", unique=True),
        Index("idx_request_id", "request_id"),
        Index("idx_designer_id", "designer_id"),
        Index("idx_plan_date", "plan_start_date", "plan_end_date"),
        Index("idx_status", "status"),
    )


class DesignUnavailableDate(Base):
    __tablename__ = "design_unavailable_date"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, comment="不可用日期")
    period = Column(String(2), nullable=True, comment="时段(am/pm, NULL=全天)")
    reason = Column(String(256), nullable=True, comment="原因")
    created_by = Column(Integer, nullable=True, comment="创建人ID")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("date", "period", name="uq_unavailable_date_period"),
    )


class DesignCapacityConfig(Base):
    __tablename__ = "design_capacity_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_date = Column(Date, nullable=True, comment="配置日期（NULL=全局）")
    designer_id = Column(Integer, nullable=True, comment="设计师ID（NULL=全局）")
    period = Column(String(2), nullable=True, comment="时段(am/pm, NULL=全天)")
    max_parallel_tasks = Column(Integer, nullable=False, default=3, server_default="3", comment="最大并行任务数")
    scheduling_mode = Column(
        SAEnum("pool", "individual", name="scheduling_mode_enum"),
        nullable=False, default="pool", server_default="pool", comment="排期模式",
    )
    updated_by = Column(Integer, nullable=True, comment="更新人ID")
    updated_at = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("config_date", "designer_id", "period", name="uq_config_date_designer_period"),
    )


class DesignAuditLog(Base):
    __tablename__ = "design_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, nullable=False, comment="关联申请ID")
    task_id = Column(Integer, nullable=True, comment="关联任务ID")
    operator_id = Column(Integer, nullable=False, comment="操作人ID")
    operator_name = Column(String(64), nullable=False, comment="操作人姓名")
    operator_role = Column(
        SAEnum("salesperson", "supervisor", "design_staff", name="operator_role_enum"),
        nullable=False, comment="操作人角色",
    )
    action = Column(
        SAEnum("submit", "approve", "reject", "confirm", "start", "complete",
               "cancel", "reschedule", "set_unavailable", "remove_unavailable",
               "update_capacity", name="audit_action_enum"),
        nullable=False, comment="操作动作",
    )
    from_status = Column(String(32), nullable=True, comment="原状态")
    to_status = Column(String(32), nullable=True, comment="目标状态")
    comment = Column(Text, nullable=True, comment="操作备注")
    snapshot = Column(JSON, nullable=True, comment="快照数据")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")


class DesignRequestSeq(Base):
    __tablename__ = "design_request_seq"

    date_key = Column(CHAR(8), primary_key=True, comment="日期键 YYYYMMDD")
    last_seq = Column(Integer, nullable=False, default=0, server_default="0", comment="最后序号")
