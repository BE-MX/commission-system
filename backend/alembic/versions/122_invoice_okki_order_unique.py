"""make invoice OKKI order binding unique

Revision ID: 122_invoice_okki_order_unique
Revises: 121_invoice_inventory_sync_key
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "122_invoice_okki_order_unique"
down_revision = "121_invoice_inventory_sync_key"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_invoice_xiaoman_order_id"


def _indexes() -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("ark_invoices")}


def upgrade() -> None:
    bind = op.get_bind()
    # 空字符串在业务上等于未绑定，先归一为 NULL，保留多条未绑定记录。
    bind.execute(sa.text("""
        UPDATE ark_invoices
        SET xiaoman_order_id = NULL
        WHERE xiaoman_order_id IS NOT NULL
          AND TRIM(xiaoman_order_id) = ''
    """))
    duplicates = bind.execute(sa.text("""
        SELECT xiaoman_order_id, COUNT(*) AS duplicate_count
        FROM ark_invoices
        WHERE xiaoman_order_id IS NOT NULL
        GROUP BY xiaoman_order_id
        HAVING COUNT(*) > 1
        LIMIT 10
    """)).mappings().all()
    if duplicates:
        ids = ", ".join(str(row["xiaoman_order_id"]) for row in duplicates)
        raise RuntimeError(
            f"检测到重复 OKKI 订单绑定（{ids}），请先人工清理后重跑迁移"
        )
    if INDEX_NAME not in _indexes():
        op.create_index(
            INDEX_NAME,
            "ark_invoices",
            ["xiaoman_order_id"],
            unique=True,
        )


def downgrade() -> None:
    if INDEX_NAME in _indexes():
        op.drop_index(INDEX_NAME, table_name="ark_invoices")
