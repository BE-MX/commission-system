"""Bind local aftersales to shipped lines and immutable execution evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "233_local_aftersales"
down_revision = "232_partial_receipt_reversal"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ark_aftersales_cases", "product_name_snapshot", existing_type=sa.String(256),
                    type_=sa.String(512), existing_nullable=False)
    op.add_column("ark_aftersales_cases", sa.Column("local_invoice_item_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_aftersales_local_line", "ark_aftersales_cases", "ark_invoice_items", ["local_invoice_item_id"], ["id"])
    op.create_index("ix_ark_aftersales_cases_local_invoice_item_id", "ark_aftersales_cases", ["local_invoice_item_id"])
    op.create_table("ark_aftersales_executions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", mysql.BIGINT(unsigned=True), sa.ForeignKey("ark_aftersales_cases.id"), nullable=False),
        sa.Column("related_invoice_id", sa.BigInteger(), sa.ForeignKey("ark_invoices.id"), nullable=True, unique=True,
                  comment="补发或重做订单，金额为零且沿用正常检验出库"),
        sa.Column("settlement_item_id", sa.BigInteger(), sa.ForeignKey("ark_shipment_settlement_items.id"), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("quantity", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("stock_document_id", sa.BigInteger(), sa.ForeignKey("ark_stock_documents.id"), nullable=True, unique=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ark_aftersales_executions_case_id", "ark_aftersales_executions", ["case_id"])
    op.create_index("ix_ark_aftersales_executions_settlement_item_id", "ark_aftersales_executions", ["settlement_item_id"])


def downgrade():
    raise RuntimeError("Aftersales execution facts require a reviewed forward migration")
