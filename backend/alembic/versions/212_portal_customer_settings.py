"""Shared customer delivery and customer-specific authorized SKU pricing."""
from alembic import op
import sqlalchemy as sa

revision = "212_portal_customer_settings"
down_revision = "211_color_measure_record_type"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoice_customer_profiles", sa.Column("delivery_json", sa.JSON(), nullable=True, comment="客户共享收货地址；订单保持独立快照"))
    op.add_column("ark_invoice_customer_profiles", sa.Column("delivery_version", sa.Integer(), nullable=False, server_default="1", comment="客户地址并发版本"))
    op.add_column("ark_order_portal_catalog_grants", sa.Column("unit_price", sa.Numeric(12, 4), nullable=True, comment="USD客户专属商品单价；空值沿用定价规则"))
    op.add_column("ark_shipping_inspections", sa.Column("shipment_version", sa.Integer(), nullable=False, server_default="0", comment="物流关联并发版本；不影响验货版本"))
    op.add_column("ark_shipping_inspections", sa.Column("shipment_tracking_id", sa.BigInteger(), nullable=True, comment="验货单关联的已上传物流单"))
    op.create_foreign_key("fk_inspection_shipment_tracking", "ark_shipping_inspections", "shipment_tracking", ["shipment_tracking_id"], ["id"], ondelete="RESTRICT")


    # Apply this release's requested defaults to existing families and inherited items.
    # A family buffer historically stores its display threshold in inventory units.
    families = sa.table("ark_order_portal_product_families", sa.column("id"), sa.column("code"),
        sa.column("out_of_stock_below"), sa.column("row_version"))
    items = sa.table("ark_order_portal_catalog_items", sa.column("family_id"),
        sa.column("conversion_factor"), sa.column("safety_buffer"), sa.column("row_version"))
    bind = op.get_bind()
    for family_id, code in bind.execute(sa.select(families.c.id, families.c.code)):
        key = str(code).lower().replace("-", "_")
        threshold = 5 if "butterfly" in key else 200 if any(name in key for name in
            ("tape_hair", "k_tape", "nano_tape", "i_tape")) else 30
        bind.execute(families.update().where(families.c.id == family_id).values(
            out_of_stock_below=threshold, row_version=families.c.row_version + 1))
        bind.execute(items.update().where(items.c.family_id == family_id).values(
            safety_buffer=threshold * items.c.conversion_factor, row_version=items.c.row_version + 1))


def downgrade():
    raise RuntimeError("Preserve customer addresses and contract prices when rolling back application code")
