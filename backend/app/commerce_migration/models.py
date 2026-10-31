"""Import identities and source evidence; never a second sales ledger."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from app.core.database import Base
from app.core.time import beijing_now


class MigrationBatch(Base):
    __tablename__ = 'ark_commerce_migration_batches'
    batch_key = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), primary_key=True, comment='导入请求稳定身份')
    source = Column(String(32).with_variant(mysql.VARCHAR(32, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='来源系统')
    tenant = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='来源租户')
    manifest_hash = Column(String(64), nullable=False, comment='规范化清单SHA256，不包含凭据')
    evidence_sha256 = Column(String(64), nullable=False, comment='人工核验源文件SHA256')
    review_reference = Column(String(500), nullable=False, comment='核验依据说明，非批准模拟')
    cutover_date = Column(Date, nullable=False, comment='清单期初基准业务日')
    result = Column(JSON, nullable=False, comment='原导入结果及内部稳定映射')
    created_by = Column(Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql'), ForeignKey('ark_users.id', ondelete='RESTRICT'), nullable=False, comment='实际导入人')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='导入完成北京时间')


class MigrationRecord(Base):
    __tablename__ = 'ark_commerce_migration_records'
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='核验来源记录ID')
    batch_key = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), ForeignKey('ark_commerce_migration_batches.batch_key', ondelete='RESTRICT'), nullable=False, index=True, comment='首次导入批次')
    source = Column(String(32).with_variant(mysql.VARCHAR(32, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='来源系统')
    tenant = Column(String(64).with_variant(mysql.VARCHAR(64, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='来源租户')
    object_type = Column(String(32).with_variant(mysql.VARCHAR(32, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='SKU或历史单据类型，不代表新经济动作')
    external_id = Column(String(128).with_variant(mysql.VARCHAR(128, collation='utf8mb4_bin'), 'mysql'), nullable=False, comment='来源对象稳定ID或规范化组合ID')
    role = Column(String(16), nullable=False, comment='catalog/只读archive/期初opening')
    content_hash = Column(String(64), nullable=False, comment='不可变已核验原始事实摘要')
    snapshot = Column(JSON, nullable=False, comment='核验事实原始快照，历史事实不更新')
    local_sku_id = Column(BigInteger, ForeignKey('ark_catalog_skus.id', ondelete='RESTRICT'), nullable=True, comment='目录对象本地SKU ID')
    local_invoice_id = Column(BigInteger, ForeignKey('ark_invoices.id', ondelete='RESTRICT'), nullable=True,
        unique=True, comment='已核验整单承接的现有发票主账')
    local_customer_order_id = Column(BigInteger, ForeignKey('ark_customer_orders.id', ondelete='RESTRICT'), nullable=True,
        unique=True, comment='已核验整单承接的原客户经营投影身份')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='记录导入北京时间')
    __table_args__ = (UniqueConstraint('source', 'tenant', 'object_type', 'external_id', name='uq_commerce_migration_source'),)
