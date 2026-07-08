"""备货管理 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)

from app.core.database import Base


class SafetyStock(Base):
    """安全库存配置表,每个产品一条"""

    __tablename__ = "ark_safety_stock"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    product_id = Column(BigInteger, nullable=False, comment="产品ID,对应 lsordertest.okki_products.product_id")
    safety_stock = Column(Integer, nullable=False, default=0, comment="安全库存阈值(件)")
    lead_time_days = Column(SmallInteger, nullable=False, default=30, comment="备货周期(天)")
    safety_factor = Column(Numeric(4, 2), nullable=False, default=1.50, comment="安全系数")
    source = Column(SmallInteger, nullable=False, default=0, comment="0=手动,1=公式估算,2=TFT模型")
    updated_by = Column(Integer, nullable=False, comment="最后修改人 user_id")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("product_id", name="uk_product_id"),
        Index("idx_safety_stock_updated_at", "updated_at"),
        {"comment": "安全库存配置表,每个产品一条"},
    )


class StockDailyReport(Base):
    """安全库存日报存储表,每天一条"""

    __tablename__ = "ark_stock_daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    report_date = Column(Date, nullable=False, comment="日报日期")
    shortage_count = Column(SmallInteger, nullable=False, default=0, comment="紧缺SKU数量")
    warning_count = Column(SmallInteger, nullable=False, default=0, comment="预警SKU数量")
    sufficient_count = Column(SmallInteger, nullable=False, default=0, comment="充足SKU数量")
    shortage_skus = Column(JSON, nullable=False, default=list, comment="紧缺SKU详情")
    warning_skus = Column(JSON, nullable=False, default=list, comment="预警SKU详情JSON数组")
    dingtalk_sent = Column(SmallInteger, nullable=False, default=0, comment="钉钉推送是否已发:0否1是")
    sent_at = Column(DateTime, nullable=True, comment="推送时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("report_date", name="uk_report_date"),
        Index("idx_stock_daily_created_at", "created_at"),
        {"comment": "安全库存日报存储表,每天一条"},
    )


class ProductionOrder(Base):
    """生产订单主表"""

    __tablename__ = "ark_production_orders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_no = Column(String(32), nullable=False, comment="生产单号")
    batch_no = Column(String(64), nullable=False, comment="生产批次号")
    remark = Column(String(500), nullable=True, comment="生产单备注")
    status = Column(SmallInteger, nullable=False, default=0, comment="0=已提交,1=已终止,2=已完成")
    created_by = Column(Integer, nullable=False, comment="创建人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")
    deleted_flag = Column(SmallInteger, nullable=False, default=0, comment="0=正常,1=已删除(软删)")

    __table_args__ = (
        UniqueConstraint("order_no", name="uk_order_no"),
        UniqueConstraint("batch_no", name="uk_batch_no"),
        Index("idx_production_orders_status", "status"),
        Index("idx_production_orders_created_by", "created_by"),
        {"comment": "生产订单主表"},
    )


class ProductionOrderItem(Base):
    """生产订单明细表"""

    __tablename__ = "ark_production_order_items"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(Integer, ForeignKey("ark_production_orders.id", ondelete="CASCADE"), nullable=False, comment="关联生产订单ID")
    product_id = Column(BigInteger, nullable=False, comment="产品ID")
    product_name = Column(String(255), nullable=False, comment="产品名称")
    model = Column(String(100), nullable=True, comment="型号")
    spec_info = Column(String(255), nullable=True, comment="规格属性")
    order_qty = Column(Integer, nullable=False, comment="生产下单数量")
    received_qty = Column(Integer, nullable=False, default=0, comment="已入库数量")
    status = Column(SmallInteger, nullable=False, default=0, comment="0=已提交,1=已终止,2=已完成")
    is_urgent = Column(SmallInteger, nullable=False, default=0, comment="0=正常,1=加急")
    expected_delivery_date = Column(Date, nullable=True, comment="预计交期")
    remark = Column(String(500), nullable=True, comment="明细备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = (
        Index("idx_production_items_order_id", "order_id"),
        Index("idx_production_items_product_id", "product_id"),
        Index("idx_production_items_status", "status"),
        {"comment": "生产订单产品明细表"},
    )


class ProductionCart(Base):
    """生产单购物车,按用户隔离"""

    __tablename__ = "ark_production_cart"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    user_id = Column(Integer, nullable=False, comment="用户ID")
    product_id = Column(BigInteger, nullable=False, comment="产品ID")
    product_name = Column(String(255), nullable=False, comment="产品名称")
    model = Column(String(100), nullable=True, comment="型号")
    spec_info = Column(String(255), nullable=True, comment="规格属性")
    order_qty = Column(Integer, nullable=False, comment="生产下单数量")
    remark = Column(String(500), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uk_cart_user_product"),
        Index("idx_production_cart_user_id", "user_id"),
        {"comment": "生产单购物车,按用户隔离"},
    )


class ProductionAuditLog(Base):
    """生产订单审计日志"""

    __tablename__ = "ark_production_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(Integer, nullable=False, comment="关联生产订单ID")
    item_id = Column(Integer, nullable=True, comment="关联明细ID,可为空")
    operator_id = Column(Integer, nullable=False, comment="操作人 user_id")
    operator_name = Column(String(64), nullable=False, comment="操作人姓名")
    action = Column(String(32), nullable=False, comment="操作动作")
    from_status = Column(SmallInteger, nullable=True, comment="原状态")
    to_status = Column(SmallInteger, nullable=True, comment="目标状态")
    comment = Column(String(500), nullable=True, comment="操作备注")
    snapshot = Column(JSON, nullable=True, comment="变更快照JSON")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="操作时间")

    __table_args__ = (
        Index("idx_production_audit_order_id", "order_id"),
        Index("idx_production_audit_created_at", "created_at"),
        {"comment": "生产订单审计日志"},
    )


class ProductionPrintLog(Base):
    """生产订单打印日志"""

    __tablename__ = "ark_production_print_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(Integer, nullable=False, comment="关联生产订单ID")
    order_no = Column(String(64), nullable=False, comment="生产单号(冗余)")
    scope = Column(String(20), nullable=False, default="category", comment="打印范围: order/category")
    category_index = Column(SmallInteger, nullable=True, comment="分类编号(scope=category时)")
    category_label = Column(String(255), nullable=True, comment="分类名称快照")
    item_ids_json = Column(JSON, nullable=True, comment="打印的明细ID列表")
    printed_by = Column(Integer, nullable=False, comment="操作人 user_id")
    printed_by_name = Column(String(64), nullable=False, default="", comment="操作人姓名快照")
    printed_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="打印时间")

    __table_args__ = (
        Index("idx_print_log_order", "order_id", "scope", "category_index", "printed_at"),
        Index("idx_print_log_order_no", "order_no"),
        {"comment": "生产订单打印日志"},
    )
