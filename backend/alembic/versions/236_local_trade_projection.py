"""Native invoice facts share customer projections without replaying history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "236_local_trade_projection"
down_revision = "235_local_commission"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column("local_rate_to_usd", sa.Numeric(18, 8), nullable=True, comment="确认时冻结订单原币至USD汇率"))
    op.add_column("ark_invoices", sa.Column("local_commercial", sa.JSON(), nullable=True, comment="本地商业来源及客户地域快照"))
    op.add_column("ark_invoice_items", sa.Column("commercial_kind", sa.String(16), nullable=True, comment="本地商业明细 sample/bulk，旧单不猜测"))
    op.add_column("ark_customer_orders", sa.Column("local_invoice_id", sa.BigInteger(), nullable=True, comment="本地订单唯一关联，历史承接复用投影"))
    op.create_foreign_key("fk_customer_order_local_invoice", "ark_customer_orders", "ark_invoices", ["local_invoice_id"], ["id"])
    op.create_unique_constraint("uq_customer_order_local_invoice", "ark_customer_orders", ["local_invoice_id"])
    for column, old_size, size in (("product_name", 255, 512), ("model", 128, 200), ("length", 64, 128)):
        op.alter_column("ark_customer_order_items", column, type_=sa.String(size), existing_type=sa.String(old_size), existing_nullable=True,
            comment={"product_name": "订单产品名称原值", "model": "产品型号原值或标准化值", "length": "产品长度及原单位文本"}[column])
    op.create_table("ark_trade_projections",
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("ark_invoices.id"), primary_key=True, comment="唯一订单主账 ID"),
        sa.Column("customer_order_id", sa.BigInteger(), sa.ForeignKey("ark_customer_orders.id"), nullable=False, unique=True, comment="唯一客户订单事实投影"),
        sa.Column("invoice_version", sa.Integer(), nullable=False, comment="已处理订单版本"),
        sa.Column("finance_event_id", sa.BigInteger(), nullable=False, comment="订单资金事件水位"),
        sa.Column("aftersales_execution_id", sa.BigInteger(), nullable=False, comment="售后执行水位"),
        sa.Column("content_hash", sa.String(64), nullable=False, comment="业务内容摘要"),
        sa.Column("projected_at", sa.DateTime(), nullable=False, comment="投影完成北京时间"))
    op.create_table("ark_sales_roster",
        sa.Column("ark_user_id", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), primary_key=True, comment="本地业务员 ID"),
        sa.Column("legacy_user_id", sa.String(64), nullable=True, unique=True, comment="核验的历史业务员 ID"),
        sa.Column("english_name", sa.String(128), nullable=True, comment="英文名"),
        sa.Column("team", sa.String(100), nullable=False, comment="统计分队"),
        sa.Column("camp", sa.String(100), nullable=False, comment="活动阵营"),
        sa.Column("new_customer_target", sa.Integer(), nullable=False, comment="新签目标"),
        sa.Column("amount_target", sa.Numeric(16, 2), nullable=False, comment="USD目标"),
        sa.Column("active", sa.Boolean(), nullable=False, comment="是否统计"),
        sa.Column("version", sa.Integer(), nullable=False, comment="并发版本"),
        sa.Column("updated_by", sa.Integer(), nullable=False, comment="维护人"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="维护北京时间"))


def downgrade():
    raise RuntimeError("Trade provenance cannot be discarded; use a corrective migration")
