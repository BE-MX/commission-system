"""Stable local identities; external identifiers are scoped aliases only."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now


class CatalogProduct(Base):
    __tablename__ = "ark_catalog_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    code = Column(String(64), nullable=False, unique=True, comment='唯一业务编码')
    name = Column(String(512), nullable=False, comment='名称')
    display_name = Column(String(256), nullable=False, comment='单据展示名称')
    kind = Column(String(16), nullable=False, default="hair", comment='业务类别')
    model = Column(String(200), nullable=True, comment='产品型号')
    active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时间）')


class CatalogSku(Base):
    __tablename__ = "ark_catalog_skus"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    product_id = Column(BigInteger, ForeignKey("ark_catalog_products.id", ondelete="RESTRICT"), nullable=False, index=True, comment='本地产品ID')
    code = Column(String(64), nullable=False, unique=True, comment='唯一业务编码')
    color = Column(String(128), nullable=False, default="", comment='颜色或色号')
    size = Column(String(128), nullable=False, default="", comment='长度或尺寸')
    curl = Column(String(64), nullable=True, comment='卷度')
    unit = Column(String(16), nullable=False, default="piece", comment='计量单位 piece=件')
    weight_grams = Column(Numeric(14, 3), nullable=True, comment='每件克重')
    attributes = Column(JSON, nullable=True, comment='产品属性快照')
    active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时间）')


class CatalogExternalIdentity(Base):
    __tablename__ = "ark_catalog_external_identities"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    source = Column(String(32).with_variant(mysql.VARCHAR(32, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='外部来源系统')
    tenant = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='外部租户标识')
    external_product_id = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='外部产品ID')
    external_sku_id = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), nullable=False, default="", comment='外部SKU ID，无SKU时为空串')
    sku_id = Column(BigInteger, ForeignKey("ark_catalog_skus.id", ondelete="RESTRICT"), nullable=False, comment='本地SKU ID')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')

    __table_args__ = (UniqueConstraint("source", "tenant", "external_product_id", "external_sku_id", name="uq_catalog_external_identity"),)
