"""Standard SKU catalog and immutable customer presentation revisions."""

from sqlalchemy import (BigInteger, CheckConstraint, Column, Index, JSON, Numeric,
                        String, UniqueConstraint, DateTime)

from app.core.database import Base
from app.portal.model_base import PREFIX, Record, Versioned, employee, reference


class CatalogItem(Record, Versioned, Base):
    __tablename__ = PREFIX + "catalog_items"
    site_id = reference("sites")
    product_kind = Column(String(16), nullable=False, comment='标准商品类别，发品或配件')
    source_namespace = Column(String(128), nullable=False, comment='标准SKU数据源命名空间')
    product_id = Column(String(64), nullable=False, comment='标准商品ID，按字符串存储')
    sku_id = Column(String(64), nullable=False, comment='标准规格ID，按字符串存储')
    standard_fingerprint = Column(String(64), nullable=False, comment='标准SKU元数据指纹')
    standard_json = Column(JSON, nullable=False, comment='不可被客户别名覆盖的标准属性')
    display_name = Column(String(128), nullable=False, comment='站点默认型号展示名')
    color_name = Column(String(128), nullable=False, comment='站点默认颜色展示名')
    image_asset_id = Column(String(64), comment='受管理图片资产引用')
    status = Column(String(16), nullable=False, default="draft", comment='受服务层状态机约束的业务状态')
    inventory_unit = Column(String(32), nullable=False, comment='库存标准单位')
    sale_unit = Column(String(32), nullable=False, comment='销售标准单位')
    conversion_factor = Column(Numeric(14, 6), nullable=False, comment='每销售单位对应库存单位量')
    min_qty = Column(BigInteger, nullable=False, default=1, comment='最小购买数量')
    step_qty = Column(BigInteger, nullable=False, default=1, comment='购买数量步长')
    safety_buffer = Column(Numeric(14, 6), nullable=False, default=0, comment='库存标准单位下的安全余量')
    __table_args__ = (
        UniqueConstraint("site_id", "source_namespace", "product_id", "sku_id", name="uq_op_catalog_sku"),
        CheckConstraint("product_kind IN ('hair','accessory')", name="ck_op_catalog_kind"),
        CheckConstraint("status IN ('draft','published','disabled')", name="ck_op_catalog_status"),
        CheckConstraint("conversion_factor > 0 AND min_qty > 0 AND step_qty > 0 AND safety_buffer >= 0", name="ck_op_catalog_quantity"),
        Index("ix_op_catalog_site_status", "site_id", "status"),
    )


class CatalogGrant(Record, Base):
    __tablename__ = PREFIX + "catalog_grants"
    access_id = reference("customer_access")
    catalog_item_id = reference("catalog_items")
    status = Column(String(16), nullable=False, default="enabled", comment='受服务层状态机约束的业务状态')
    __table_args__ = (
        UniqueConstraint("access_id", "catalog_item_id", name="uq_op_catalog_grant"),
        CheckConstraint("status IN ('enabled','disabled')", name="ck_op_catalog_grant_status"),
    )


class MappingRevision(Record, Base):
    __tablename__ = PREFIX + "mapping_revisions"
    access_id = reference("customer_access")
    version = Column(BigInteger, nullable=False, comment='授权或配置版本')
    status = Column(String(16), nullable=False, default="draft", comment='受服务层状态机约束的业务状态')
    created_by = employee()
    published_at = Column(DateTime, comment='正式发布的北京时间')
    base_version = Column(BigInteger, nullable=False, comment='编辑开始时的版本')
    snapshot_json = Column(JSON, nullable=False, comment='不可变客户映射快照')
    digest = Column(String(64), nullable=False, comment='映射快照SHA256摘要')
    __table_args__ = (
        UniqueConstraint("access_id", "version", name="uq_op_mapping_revision"),
        CheckConstraint("status IN ('draft','published')", name="ck_op_mapping_status"),
    )
