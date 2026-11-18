"""产品风向标持久化模型。

订单事实只读来自 lsordertest；本域只保存「旧产品库时期品名 → 型号 + 默认克重」映射。
需求见 docs/requirements/2026-11-18-product-sales-radar/README.md。
"""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.auth import models as _auth_models  # noqa: F401 - register ark_users for FK resolution
from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

MAPPING_SUGGESTED = "suggested"
MAPPING_CONFIRMED = "confirmed"
MAPPING_IGNORED = "ignored"
MAPPING_STATUSES = (MAPPING_SUGGESTED, MAPPING_CONFIRMED, MAPPING_IGNORED)


class ProductSalesNameMapping(Base):
    __tablename__ = "ark_product_sales_name_mappings"

    id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
        comment="主键",
    )
    name_hash = Column(String(64), nullable=False, comment="规范化品名的 SHA-256")
    product_name = Column(String(512), nullable=False, comment="首次出现的订单品名原值")
    model = Column(String(200), nullable=True, comment="对应的标准型号")
    unit_grams = Column(Numeric(10, 3), nullable=True, comment="每件默认克重（假设值，不是确切值）")
    status = Column(
        String(16), nullable=False, default=MAPPING_SUGGESTED, server_default=MAPPING_SUGGESTED,
        comment="suggested 规则预填 / confirmed 人工采纳 / ignored 非发制品不计重量",
    )
    suggestion_source = Column(String(32), nullable=True, comment="预填来源：okki_model / name_grams")
    rule_version = Column(String(16), nullable=False, comment="生成预填的规则版本")
    line_count = Column(Integer, nullable=False, default=0, server_default="0", comment="涉及有效订单明细行数（统计快照）")
    quantity_total = Column(Numeric(15, 2), nullable=False, default=0, server_default="0", comment="涉及件数合计（统计快照）")
    last_seen_date = Column(Date, nullable=True, comment="最近一次出现的订单入账日期")
    catalog_sku_id = Column(BigInteger, nullable=True, comment="预留：产品主档 SKU 关联，主档有数据后挂钩")
    confirmed_by_user_id = Column(
        USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL", name="fk_ps_mapping_confirmed_by"), nullable=True, comment="确认人",
    )
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("name_hash", name="uq_ps_mapping_name_hash"),
        Index("idx_ps_mapping_status_qty", "status", "quantity_total"),
        {"comment": "产品销量：旧产品库时期品名到型号与默认克重的映射"},
    )
