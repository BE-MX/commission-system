"""员工属性历史、主管关系历史模型"""

from sqlalchemy import (
    Column, BigInteger, String, Date, Boolean, DateTime, Enum,
    Index, func,
)
from app.core.database import Base


class EmployeeAttributeHistory(Base):
    """员工属性历史表：记录业务员的开发/分配属性变更"""
    __tablename__ = "employee_attribute_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    employee_id = Column(String(64), nullable=False, comment="关联业务库员工ID")
    attribute_type = Column(
        Enum("develop", "distribute", name="attribute_type_enum"),
        nullable=False, comment="开发/分配",
    )
    effective_start = Column(Date, nullable=False, comment="生效开始时间")
    effective_end = Column(Date, nullable=True, comment="生效结束时间，NULL表示当前有效")
    is_current = Column(Boolean, default=True, comment="是否当前有效")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_employee_attr_emp_current", "employee_id", "is_current"),
    )


class SupervisorRelationHistory(Base):
    """业务员-主管关系历史表"""
    __tablename__ = "supervisor_relation_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    salesperson_id = Column(String(64), nullable=False, comment="业务员ID")
    supervisor_id = Column(String(64), nullable=False, comment="一级主管ID")
    second_supervisor_id = Column(String(64), nullable=True, comment="二级主管ID")
    effective_start = Column(Date, nullable=False)
    effective_end = Column(Date, nullable=True)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_supervisor_rel_sp_current", "salesperson_id", "is_current"),
    )
