"""add invoice module

Revision ID: 044_invoice_module
Revises: 043_commission_confirmation
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "044_invoice_module"
down_revision = "043_commission_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_invoices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_no", sa.String(length=64), nullable=False, comment="Invoice number"),
        sa.Column("customer_id", sa.String(length=64), nullable=False, comment="customer_info.company_id"),
        sa.Column("customer_name", sa.String(length=256), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft", comment="draft/ready/synced/sync_failed"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("xiaoman_order_id", sa.String(length=64), nullable=True),
        sa.Column("xiaoman_order_no", sa.String(length=64), nullable=True),
        sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="not_synced"),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_no", name="uq_ark_invoices_invoice_no"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_invoices_customer", "ark_invoices", ["customer_id"])
    op.create_index("idx_ark_invoices_status", "ark_invoices", ["status"])
    op.create_index("idx_ark_invoices_created_at", "ark_invoices", ["created_at"])

    op.create_table(
        "ark_invoice_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="okki_products.product_id"),
        sa.Column("sku_id", sa.BigInteger(), nullable=True, comment="okki_inventory.sku_id"),
        sa.Column("product_name", sa.String(length=512), nullable=False),
        sa.Column("product_display", sa.String(length=256), nullable=False),
        sa.Column("net_weight_grams", sa.String(length=64), nullable=False, comment="Mapped from okki_products.unit"),
        sa.Column("curl", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("color", sa.String(length=128), nullable=False),
        sa.Column("length", sa.String(length=128), nullable=False, comment="Mapped from okki_products.size"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_per_piece", sa.Numeric(12, 4), nullable=True),
        sa.Column("total_price", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("price_source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("xiaoman_unique_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["invoice_id"], ["ark_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_invoice_items_invoice", "ark_invoice_items", ["invoice_id"])
    op.create_index("idx_ark_invoice_items_product", "ark_invoice_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("idx_ark_invoice_items_product", table_name="ark_invoice_items")
    op.drop_index("idx_ark_invoice_items_invoice", table_name="ark_invoice_items")
    op.drop_table("ark_invoice_items")
    op.drop_index("idx_ark_invoices_created_at", table_name="ark_invoices")
    op.drop_index("idx_ark_invoices_status", table_name="ark_invoices")
    op.drop_index("idx_ark_invoices_customer", table_name="ark_invoices")
    op.drop_table("ark_invoices")

