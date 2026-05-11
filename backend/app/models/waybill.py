"""运单录入模型"""

from sqlalchemy import Column, Integer, String, Date, DateTime, func

from app.core.database import Base


class Waybill(Base):
    __tablename__ = "ark_waybills"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    waybill_no = Column(String(50), nullable=False, unique=True, comment="运单号")
    carrier = Column(String(50), nullable=False, default="未知", comment="物流商")
    recipient_name = Column(String(100), nullable=False, comment="收件人姓名")
    recipient_country = Column(String(100), nullable=False, comment="收件国家")
    ship_date = Column(Date, nullable=False, comment="发件日期")
    status = Column(String(20), nullable=False, default="待跟踪", comment="状态")
    entry_source = Column(String(20), nullable=False, default="manual", comment="录入来源")
    created_by = Column(String(50), nullable=False, comment="录入人")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
