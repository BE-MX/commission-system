"""add stock management module (ark_safety_stock + ark_stock_daily_reports)

Revision ID: 019_add_stock_module
Revises: 018_enhance_case_library
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_add_stock_module"
down_revision: Union[str, None] = "018_enhance_case_library"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 安全库存配置表 ──────────────────────────────────────
    op.create_table(
        "ark_safety_stock",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品ID,对应 lsordertest.okki_products.product_id"),
        sa.Column("safety_stock", sa.Integer(), nullable=False, server_default="0", comment="安全库存阈值(件)"),
        sa.Column("lead_time_days", sa.SmallInteger(), nullable=False, server_default="30", comment="备货周期(天)"),
        sa.Column("safety_factor", sa.Numeric(4, 2), nullable=False, server_default="1.50", comment="安全系数"),
        sa.Column("source", sa.SmallInteger(), nullable=False, server_default="0", comment="0=手动,1=公式估算,2=TFT模型"),
        sa.Column("updated_by", sa.Integer(), nullable=False, comment="最后修改人,对应 ark_users.id"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="最后修改时间",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
        sa.UniqueConstraint("product_id", name="uk_product_id"),
        comment="安全库存配置表,每个产品一条",
    )
    op.create_index("idx_safety_stock_updated_at", "ark_safety_stock", ["updated_at"])

    # ── 库存日报存储表 ──────────────────────────────────────
    op.create_table(
        "ark_stock_daily_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键"),
        sa.Column("report_date", sa.Date(), nullable=False, comment="日报日期"),
        sa.Column("shortage_count", sa.SmallInteger(), nullable=False, server_default="0", comment="紧缺SKU数量"),
        sa.Column("warning_count", sa.SmallInteger(), nullable=False, server_default="0", comment="预警SKU数量"),
        sa.Column("sufficient_count", sa.SmallInteger(), nullable=False, server_default="0", comment="充足SKU数量"),
        sa.Column("shortage_skus", sa.JSON(), nullable=False, comment="紧缺SKU详情JSON数组"),
        sa.Column("warning_skus", sa.JSON(), nullable=False, comment="预警SKU详情JSON数组"),
        sa.Column("dingtalk_sent", sa.SmallInteger(), nullable=False, server_default="0", comment="钉钉推送是否已发:0否1是"),
        sa.Column("sent_at", sa.DateTime(), nullable=True, comment="推送时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
        sa.UniqueConstraint("report_date", name="uk_report_date"),
        comment="安全库存日报存储表,每天一条",
    )
    op.create_index("idx_stock_daily_created_at", "ark_stock_daily_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_stock_daily_created_at", table_name="ark_stock_daily_reports")
    op.drop_table("ark_stock_daily_reports")
    op.drop_index("idx_safety_stock_updated_at", table_name="ark_safety_stock")
    op.drop_table("ark_safety_stock")
