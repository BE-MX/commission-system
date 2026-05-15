"""备货管理 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)

from app.core.database import Base


class SafetyStock(Base):
    """安全库存配置表,每个产品一条"""

    __tablename__ = "ark_safety_stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(BigInteger, nullable=False, comment="产品ID,对应 lsordertest.okki_products.product_id")
    safety_stock = Column(Integer, nullable=False, default=0, comment="安全库存阈值(件)")
    lead_time_days = Column(SmallInteger, nullable=False, default=30, comment="备货周期(天)")
    safety_factor = Column(Numeric(4, 2), nullable=False, default=1.50, comment="安全系数")
    source = Column(SmallInteger, nullable=False, default=0, comment="0=手动,1=公式估算,2=TFT模型")
    updated_by = Column(Integer, nullable=False, comment="最后修改人 user_id")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", name="uk_product_id"),
        Index("idx_safety_stock_updated_at", "updated_at"),
    )


class StockDailyReport(Base):
    """安全库存日报存储表,每天一条"""

    __tablename__ = "ark_stock_daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(Date, nullable=False, comment="日报日期")
    shortage_count = Column(SmallInteger, nullable=False, default=0)
    warning_count = Column(SmallInteger, nullable=False, default=0)
    sufficient_count = Column(SmallInteger, nullable=False, default=0)
    shortage_skus = Column(JSON, nullable=False, default=list, comment="紧缺SKU详情")
    warning_skus = Column(JSON, nullable=False, default=list, comment="预警SKU详情")
    dingtalk_sent = Column(SmallInteger, nullable=False, default=0, comment="钉钉推送是否已发:0否1是")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("report_date", name="uk_report_date"),
        Index("idx_stock_daily_created_at", "created_at"),
    )
