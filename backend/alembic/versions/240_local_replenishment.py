"""Scope replenishment thresholds by native SKU without reusing external IDs."""
from alembic import op
import sqlalchemy as sa

revision = "240_local_replenishment"
down_revision = "239_local_accessory_price"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ark_safety_stock", "product_id", existing_type=sa.BigInteger(), nullable=True,
                    comment="历史OKKI产品ID；本地配置使用local_sku_id")
    op.add_column("ark_safety_stock", sa.Column("local_sku_id", sa.BigInteger(), nullable=True, comment="本地安全库存SKU ID"))
    op.add_column("ark_safety_stock", sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="安全库存配置并发版本"))
    op.create_foreign_key("fk_safety_local_sku", "ark_safety_stock", "ark_catalog_skus", ["local_sku_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_safety_local_sku", "ark_safety_stock", ["local_sku_id"])
    op.alter_column("ark_production_cart", "product_id", existing_type=sa.BigInteger(), nullable=True,
                    comment="历史外部产品ID，本地使用local_sku_id")
    op.add_column("ark_production_cart", sa.Column("local_sku_id", sa.BigInteger(), nullable=True, comment="本地备货SKU ID"))
    op.create_foreign_key("fk_cart_local_sku", "ark_production_cart", "ark_catalog_skus", ["local_sku_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_cart_user_local_sku", "ark_production_cart", ["user_id", "local_sku_id"])
    op.alter_column("ark_production_cart", "product_name", existing_type=sa.String(255), type_=sa.String(512), existing_nullable=False)
    op.alter_column("ark_production_cart", "model", existing_type=sa.String(100), type_=sa.String(200), existing_nullable=True)


def downgrade():
    raise RuntimeError("Restore a verified backup; native replenishment policies must not be discarded")
