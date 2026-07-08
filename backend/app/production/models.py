"""生产报工 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy import Index

from app.core.database import Base


class Process(Base):
    """工序基础表"""

    __tablename__ = "process"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), nullable=False, unique=True, comment="工序名称")
    description = Column(String(500), nullable=True, comment="工序描述/备注")
    sort_order = Column(Integer, nullable=False, default=0, comment="展示排序权重")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=禁用,1=启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_process_status", "status"),
        {"comment": "工序基础表"},
    )


class ProcessRoute(Base):
    """工序路线表"""

    __tablename__ = "process_route"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), nullable=False, unique=True, comment="路线名称")
    description = Column(String(500), nullable=True, comment="路线描述")
    status = Column(SmallInteger, nullable=False, default=1, comment="0=禁用,1=启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_route_status", "status"),
        {"comment": "工序路线表"},
    )


class ProcessRouteStep(Base):
    """工序路线明细表"""

    __tablename__ = "process_route_step"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="CASCADE"), nullable=False, comment="关联路线ID（关联 process_route.id）")
    process_id = Column(Integer, ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, comment="关联工序ID（关联 process.id）")
    step_order = Column(SmallInteger, nullable=False, comment="执行顺序,从1开始")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("route_id", "step_order", name="uk_route_step"),
        UniqueConstraint("route_id", "process_id", name="uk_route_process"),
        Index("idx_step_route_id", "route_id"),
        Index("idx_step_process_id", "process_id"),
        {"comment": "工序路线明细表"},
    )


class ProductProcessRoute(Base):
    """产品工序路线绑定表"""

    __tablename__ = "product_process_route"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    product_id = Column(BigInteger, nullable=False, unique=True, comment="产品ID")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"), nullable=False, comment="关联路线ID（关联 process_route.id）")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_ppr_route_id", "route_id"),
        {"comment": "产品工序路线绑定表"},
    )


class OrderProductProcessProgress(Base):
    """订单产品工序进度表（核心状态表）"""

    __tablename__ = "order_product_process_progress"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_product_id = Column(
        Integer,
        ForeignKey("ark_production_order_items.id", ondelete="CASCADE"),
        nullable=False, comment="关联 ark_production_order_items.id",
    )
    process_id = Column(Integer, ForeignKey("process.id", ondelete="RESTRICT"), nullable=False, comment="关联工序ID（关联 process.id）")
    route_id = Column(Integer, ForeignKey("process_route.id", ondelete="RESTRICT"), nullable=False, comment="冗余路线ID")
    step_order = Column(SmallInteger, nullable=False, comment="工序顺序")
    status = Column(SmallInteger, nullable=False, default=0, comment="0=待完成,1=已完成")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    completed_by_user_id = Column(Integer, nullable=True, comment="完成操作人方舟用户ID")
    completed_by_wx_id = Column(String(100), nullable=True, comment="完成操作人微信原始ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("order_product_id", "step_order", name="uk_progress_order_product_step"),
        Index("idx_progress_order_product_id", "order_product_id"),
        Index("idx_progress_process_id", "process_id"),
        Index("idx_progress_status", "status"),
        Index("idx_progress_order_status", "order_product_id", "status"),
        {"comment": "订单产品工序进度表"},
    )


class UserProcessBinding(Base):
    """用户工序绑定表"""

    __tablename__ = "user_process_binding"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer, nullable=False, comment="方舟用户ID")
    process_id = Column(Integer, ForeignKey("process.id", ondelete="CASCADE"), nullable=False, comment="工序ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("user_id", "process_id", name="uk_user_process"),
        Index("idx_upb_user_id", "user_id"),
        Index("idx_upb_process_id", "process_id"),
        {"comment": "用户工序绑定表"},
    )
