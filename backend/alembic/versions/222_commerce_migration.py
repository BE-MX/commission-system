"""Keep reviewed source imports distinct from new economic commands."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '222_commerce_migration'
down_revision = '221_local_replenishment'
branch_labels = None
depends_on = None


def upgrade():
    # Source identifiers are opaque, case-sensitive identities. Narrowing the
    # equality relation preserves existing rows and all stable local SKU IDs.
    for name, length, comment in (
        ('source', 32, '外部来源系统'), ('tenant', 64, '外部租户标识'),
        ('external_product_id', 64, '外部产品ID'),
        ('external_sku_id', 64, '外部SKU ID，无SKU时为空串')):
        op.alter_column('ark_catalog_external_identities', name,
            existing_type=sa.String(length), type_=mysql.VARCHAR(length, collation='utf8mb4_bin'),
            existing_nullable=False, existing_comment=comment)

    op.create_table('ark_commerce_migration_batches',
        sa.Column('batch_key', mysql.VARCHAR(64, collation='utf8mb4_bin'), primary_key=True, comment='导入请求稳定身份'),
        sa.Column('source', mysql.VARCHAR(32, collation='utf8mb4_bin'), nullable=False, comment='来源系统'),
        sa.Column('tenant', mysql.VARCHAR(64, collation='utf8mb4_bin'), nullable=False, comment='来源租户'),
        sa.Column('manifest_hash', sa.String(64), nullable=False, comment='规范化清单SHA256，不包含凭据'),
        sa.Column('evidence_sha256', sa.String(64), nullable=False, comment='人工核验源文件SHA256'),
        sa.Column('review_reference', sa.String(500), nullable=False, comment='核验依据说明，非批准模拟'),
        sa.Column('cutover_date', sa.Date(), nullable=False, comment='清单期初基准业务日'),
        sa.Column('result', sa.JSON(), nullable=False, comment='原导入结果及内部稳定映射'),
        sa.Column('created_by', mysql.INTEGER(unsigned=True), sa.ForeignKey('ark_users.id', ondelete='RESTRICT'), nullable=False, comment='实际导入人'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='导入完成北京时间'))
    op.create_table('ark_commerce_migration_records',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True, comment='核验来源记录ID'),
        sa.Column('batch_key', mysql.VARCHAR(64, collation='utf8mb4_bin'), sa.ForeignKey('ark_commerce_migration_batches.batch_key', ondelete='RESTRICT'), nullable=False, comment='首次导入批次'),
        sa.Column('source', mysql.VARCHAR(32, collation='utf8mb4_bin'), nullable=False, comment='来源系统'),
        sa.Column('tenant', mysql.VARCHAR(64, collation='utf8mb4_bin'), nullable=False, comment='来源租户'),
        sa.Column('object_type', mysql.VARCHAR(32, collation='utf8mb4_bin'), nullable=False, comment='SKU或历史单据类型，不代表新经济动作'),
        sa.Column('external_id', mysql.VARCHAR(128, collation='utf8mb4_bin'), nullable=False, comment='来源对象稳定ID或规范化组合ID'),
        sa.Column('role', sa.String(16), nullable=False, comment='catalog/只读archive/期初opening'),
        sa.Column('content_hash', sa.String(64), nullable=False, comment='不可变已核验原始事实摘要'),
        sa.Column('snapshot', sa.JSON(), nullable=False, comment='核验事实原始快照，历史事实不更新'),
        sa.Column('local_sku_id', sa.BigInteger(), sa.ForeignKey('ark_catalog_skus.id', ondelete='RESTRICT'), nullable=True, comment='目录对象本地SKU ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='记录导入北京时间'),
        sa.UniqueConstraint('source', 'tenant', 'object_type', 'external_id', name='uq_commerce_migration_source'))
    op.create_index('ix_ark_commerce_migration_records_batch_key', 'ark_commerce_migration_records', ['batch_key'])


def downgrade():
    raise RuntimeError('Do not discard verified migration identities; use forward recovery')
