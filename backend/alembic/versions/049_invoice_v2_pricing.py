"""invoice v2: pricing, order types, custom products, sync infra

Revision ID: 049_invoice_v2_pricing
Revises: 048_expo_hair_colors
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "049_invoice_v2_pricing"
down_revision = "048_expo_hair_colors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ark_invoices: order type + header snapshot fields ──
    op.add_column("ark_invoices", sa.Column("order_type", sa.String(16), nullable=False, server_default="stock", comment="stock/production"))
    op.add_column("ark_invoices", sa.Column("contact_name", sa.String(256), nullable=True))
    op.add_column("ark_invoices", sa.Column("contact_phone", sa.String(100), nullable=True))
    op.add_column("ark_invoices", sa.Column("contact_email", sa.String(256), nullable=True))
    op.add_column("ark_invoices", sa.Column("delivery_address", sa.Text(), nullable=True))
    op.add_column("ark_invoices", sa.Column("sales_user_id", sa.Integer(), nullable=True))
    op.add_column("ark_invoices", sa.Column("sales_user_name", sa.String(100), nullable=True))
    op.add_column("ark_invoices", sa.Column("sales_phone", sa.String(100), nullable=True))
    op.add_column("ark_invoices", sa.Column("sales_email", sa.String(256), nullable=True))
    op.add_column("ark_invoices", sa.Column("express_channel", sa.String(64), nullable=True, comment="DHL/FedEx..."))
    op.add_column("ark_invoices", sa.Column("shipping_fee", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("ark_invoices", sa.Column("surcharge_name", sa.String(128), nullable=True, comment="e.g. Paypal Surcharge"))
    op.add_column("ark_invoices", sa.Column("surcharge_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("ark_invoices", sa.Column("payment_term", sa.String(256), nullable=True))
    op.add_column("ark_invoices", sa.Column("product_amount", sa.Numeric(14, 2), nullable=False, server_default="0", comment="sum of item totals, before fees"))
    op.add_column("ark_invoices", sa.Column("internal_payment_method", sa.String(64), nullable=True))
    op.add_column("ark_invoices", sa.Column("internal_discount", sa.Numeric(14, 2), nullable=True))
    op.add_column("ark_invoices", sa.Column("internal_accessory", sa.Numeric(14, 2), nullable=True))
    op.add_column("ark_invoices", sa.Column("internal_received", sa.Numeric(14, 2), nullable=True))
    op.add_column("ark_invoices", sa.Column("internal_balance", sa.Numeric(14, 2), nullable=True))
    op.add_column("ark_invoices", sa.Column("internal_shipping_type", sa.String(64), nullable=True))

    # ── ark_invoice_items: custom lines have no okki product_id ──
    op.alter_column("ark_invoice_items", "product_id", existing_type=sa.BigInteger(), nullable=True, comment="okki_products.product_id; NULL for custom lines")
    op.alter_column("ark_invoice_items", "model", existing_type=sa.String(128), nullable=True, comment="production model; optional for custom lines")
    op.add_column("ark_invoice_items", sa.Column("item_type", sa.String(16), nullable=False, server_default="stock", comment="stock/custom"))
    op.add_column("ark_invoice_items", sa.Column("standard_price", sa.Numeric(12, 4), nullable=True, comment="matrix std price snapshot"))
    op.add_column("ark_invoice_items", sa.Column("customer_price", sa.Numeric(12, 4), nullable=True, comment="rule-adjusted price snapshot"))
    op.add_column("ark_invoice_items", sa.Column("custom_product_id", sa.BigInteger(), nullable=True, comment="ark_custom_products.id, no FK by design"))
    op.create_index("idx_ark_invoice_items_custom", "ark_invoice_items", ["custom_product_id"])

    # ── custom products sunk from production-order entry ──
    op.create_table(
        "ark_custom_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("match_key", sa.String(512), nullable=False, comment="normalize(display|model|color|size|unit)"),
        sa.Column("product_display", sa.String(256), nullable=False, comment="series+grade, invoice Product column"),
        sa.Column("product_name", sa.String(512), nullable=False, comment="display/size/color/unit, mirrors okki naming"),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("color", sa.String(128), nullable=False),
        sa.Column("size", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("okki_product_id", sa.BigInteger(), nullable=True, comment="backfilled when OKKI later creates it"),
        sa.Column("okki_sku_id", sa.BigInteger(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_key", name="uq_ark_custom_products_key"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # ── pricing: color type mapping ──
    op.create_table(
        "ark_price_color_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("color_code", sa.String(64), nullable=False),
        sa.Column("color_type", sa.String(16), nullable=False, comment="solid/piano/ombre/balayage"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("color_code", name="uq_ark_price_color_code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # ── pricing: standard price matrix ──
    op.create_table(
        "ark_std_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("series_grade", sa.String(128), nullable=False, comment="e.g. Super Double Drawn Genius"),
        sa.Column("length", sa.String(32), nullable=False, comment="normalized, inch mark stripped"),
        sa.Column("weight_unit", sa.String(32), nullable=False, comment="e.g. 20g"),
        sa.Column("color_type", sa.String(16), nullable=False),
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_grade", "length", "weight_unit", "color_type", name="uq_ark_std_prices_key"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # ── pricing: per-customer adjustment rule (one of two modes) ──
    op.create_table(
        "ark_customer_price_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False, comment="customer_info.company_id"),
        sa.Column("customer_name", sa.String(256), nullable=True),
        sa.Column("adjust_type", sa.String(16), nullable=False, comment="fixed/percent"),
        sa.Column("adjust_value", sa.Numeric(12, 4), nullable=False, comment="signed: +2 fixed add / -3 percent down"),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("preferred_template", sa.String(8), nullable=True, comment="invoice export template A/B"),
        sa.Column("remark", sa.String(512), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_ark_customer_price_rules"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )

    # ── OKKI sync log (phase 2 uses it; created now so schema is stable) ──
    op.create_table(
        "ark_invoice_sync_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False, comment="create/update/retry"),
        sa.Column("success", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("request_digest", sa.Text(), nullable=True, comment="sanitized request summary"),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["invoice_id"], ["ark_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_invoice_sync_logs_inv", "ark_invoice_sync_logs", ["invoice_id"])

    # ── OKKI push settings (single row, admin managed) ──
    op.create_table(
        "ark_xiaoman_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("generic_product_no", sa.String(64), nullable=True, comment="OKKI product_no of the generic product"),
        sa.Column("generic_product_id", sa.BigInteger(), nullable=True, comment="resolved from okki_products"),
        sa.Column("generic_sku_id", sa.BigInteger(), nullable=True),
        sa.Column("default_order_status", sa.String(64), nullable=True, comment="from orderEnums"),
        sa.Column("default_currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )


def downgrade() -> None:
    op.drop_table("ark_xiaoman_settings")
    op.drop_index("idx_ark_invoice_sync_logs_inv", table_name="ark_invoice_sync_logs")
    op.drop_table("ark_invoice_sync_logs")
    op.drop_table("ark_customer_price_rules")
    op.drop_table("ark_std_prices")
    op.drop_table("ark_price_color_types")
    op.drop_table("ark_custom_products")
    op.drop_index("idx_ark_invoice_items_custom", table_name="ark_invoice_items")
    op.drop_column("ark_invoice_items", "custom_product_id")
    op.drop_column("ark_invoice_items", "customer_price")
    op.drop_column("ark_invoice_items", "standard_price")
    op.drop_column("ark_invoice_items", "item_type")
    op.alter_column("ark_invoice_items", "model", existing_type=sa.String(128), nullable=False)
    op.alter_column("ark_invoice_items", "product_id", existing_type=sa.BigInteger(), nullable=False)
    for col in (
        "internal_shipping_type", "internal_balance", "internal_received", "internal_accessory",
        "internal_discount", "internal_payment_method", "product_amount", "payment_term",
        "surcharge_amount", "surcharge_name", "shipping_fee", "express_channel",
        "sales_email", "sales_phone", "sales_user_name", "sales_user_id",
        "delivery_address", "contact_email", "contact_phone", "contact_name", "order_type",
    ):
        op.drop_column("ark_invoices", col)
