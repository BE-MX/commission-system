"""业务库只读映射（跨库查询，不建表）"""

from sqlalchemy import Column, String, Date, DECIMAL, Text
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()
BUSINESS_SCHEMA = settings.BUSINESS_DB_NAME


class BusinessBase(DeclarativeBase):
    """业务库模型的独立 Base，不参与 Alembic 迁移"""
    pass


class UserBasic(BusinessBase):
    """业务库员工表（只读）"""
    __tablename__ = "user_basic"
    __table_args__ = {"schema": BUSINESS_SCHEMA}

    user_id = Column(String(64), primary_key=True)
    full_name = Column(String(128))
    nickname = Column(String(128))
    user_mobile = Column(String(32))


class CustomerInfo(BusinessBase):
    """业务库客户表（只读）"""
    __tablename__ = "customer_info"
    __table_args__ = {"schema": BUSINESS_SCHEMA}

    company_id = Column(String(64), primary_key=True)
    company_name = Column(String(256))
    country_name = Column(String(128))
    origin_name = Column(String(128))
    archive_type = Column(String(64))
    trail_status_name = Column(String(64))


class OkkiOrder(BusinessBase):
    """业务库订单表（只读）"""
    __tablename__ = "okki_orders"
    __table_args__ = {"schema": BUSINESS_SCHEMA}

    order_id = Column(String(64), primary_key=True)
    order_no = Column(String(64))
    company_id = Column(String(64), comment="客户ID")
    amount_usd = Column(DECIMAL(12, 2))
    user_id = Column(String(64))
    custom_fields = Column(Text)
    account_date = Column(Date)
    trail = Column(String(256))
    status = Column(String(64))
    status_name = Column(String(64))
    departments = Column(Text)


class OkkiReceipt(BusinessBase):
    """业务库回款表（只读）"""
    __tablename__ = "okki_receipts"
    __table_args__ = {"schema": BUSINESS_SCHEMA}

    cash_collection_id = Column(String(64), primary_key=True)
    cash_collection_no = Column(String(64))
    collection_date = Column(Date)
    type = Column(String(64))
    amount_usd = Column(DECIMAL(12, 2))
    order_id = Column(String(64))
    company_id = Column(String(64))
    order_no = Column(String(64))
    company_name = Column(String(256))
