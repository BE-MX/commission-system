"""Audit of explicit customer-owner repairs to the OKKI mirror."""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String

from app.core.database import Base
from app.core.time import beijing_now


class CustomerSyncLog(Base):
    __tablename__ = "ark_invoice_customer_sync_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    company_id = Column(String(64), nullable=False, comment="OKKI 客户 ID")
    created_by = Column(Integer, nullable=True, comment="操作人方舟用户 ID")
    source_update_time = Column(String(32), nullable=True, comment="OKKI 资料版本时间")
    before_data = Column(JSON, nullable=True, comment="镜像写入前快照；新客户为 null")
    after_data = Column(JSON, nullable=False, comment="镜像写入后快照")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="审计创建北京时间")

    __table_args__ = (
        Index("ix_invoice_customer_sync_company_time", "company_id", "created_at"),
        {"comment": "发票客户手动同步镜像审计"},
    )
