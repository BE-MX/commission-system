"""track invoices imported from OKKI screenshots

Revision ID: 119_invoice_screenshot_src
Revises: 117_sales_pool_dedupe
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "119_invoice_screenshot_src"
down_revision = "117_sales_pool_dedupe"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns("ark_invoices")}


def _indexes() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("ark_invoices")}


def upgrade() -> None:
    columns = _columns()
    additions = (
        ("source_type", sa.String(32), False, "manual", "来源：manual/okki_screenshot"),
        ("source_order_id", sa.String(64), True, None, "截图匹配到的既有OKKI订单ID"),
        ("source_order_no", sa.String(64), True, None, "截图匹配到的既有OKKI订单号"),
        ("source_order_name", sa.String(256), True, None, "截图识别的OKKI订单名称"),
        ("source_image_sha256", sa.String(64), True, None, "来源截图SHA-256；不保存原图"),
    )
    for name, column_type, nullable, default, comment in additions:
        if name in columns:
            continue
        op.add_column("ark_invoices", sa.Column(
            name,
            column_type,
            nullable=nullable,
            server_default=default,
            comment=comment,
        ))

    indexes = _indexes()
    if "uq_invoice_source_order" not in indexes:
        op.create_index(
            "uq_invoice_source_order",
            "ark_invoices",
            ["source_type", "source_order_id"],
            unique=True,
        )
    if "uq_invoice_source_image" not in indexes:
        op.create_index(
            "uq_invoice_source_image",
            "ark_invoices",
            ["source_type", "source_image_sha256"],
            unique=True,
        )


def downgrade() -> None:
    indexes = _indexes()
    if "uq_invoice_source_image" in indexes:
        op.drop_index("uq_invoice_source_image", table_name="ark_invoices")
    if "uq_invoice_source_order" in indexes:
        op.drop_index("uq_invoice_source_order", table_name="ark_invoices")
    columns = _columns()
    for name in (
        "source_image_sha256",
        "source_order_name",
        "source_order_no",
        "source_order_id",
        "source_type",
    ):
        if name in columns:
            op.drop_column("ark_invoices", name)
