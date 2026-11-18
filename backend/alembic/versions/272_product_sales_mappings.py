"""Create the historical product-name mapping table for the product sales radar."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "272_product_sales_mappings"
down_revision = "271_dom_fu_lost_record"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade():
    op.create_table(
        "ark_product_sales_name_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("name_hash", sa.String(64), nullable=False, comment="规范化品名的 SHA-256"),
        sa.Column("product_name", sa.String(512), nullable=False, comment="首次出现的订单品名原值"),
        sa.Column("model", sa.String(200), nullable=True, comment="对应的标准型号"),
        sa.Column("unit_grams", sa.Numeric(10, 3), nullable=True, comment="每件默认克重（假设值，不是确切值）"),
        sa.Column("status", sa.String(16), nullable=False, server_default="suggested",
                  comment="suggested 规则预填 / confirmed 人工采纳 / ignored 非发制品不计重量"),
        sa.Column("suggestion_source", sa.String(32), nullable=True, comment="预填来源：okki_model / name_grams"),
        sa.Column("rule_version", sa.String(16), nullable=False, comment="生成预填的规则版本"),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0", comment="涉及有效订单明细行数（统计快照）"),
        sa.Column("quantity_total", sa.Numeric(15, 2), nullable=False, server_default="0", comment="涉及件数合计（统计快照）"),
        sa.Column("last_seen_date", sa.Date(), nullable=True, comment="最近一次出现的订单入账日期"),
        sa.Column("catalog_sku_id", sa.BigInteger(), nullable=True, comment="预留：产品主档 SKU 关联，主档有数据后挂钩"),
        sa.Column("confirmed_by_user_id", USER_ID, nullable=True, comment="确认人"),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True, comment="确认时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["ark_users.id"], ondelete="SET NULL",
                                name="fk_ps_mapping_confirmed_by"),
        sa.UniqueConstraint("name_hash", name="uq_ps_mapping_name_hash"),
        comment="产品销量：旧产品库时期品名到型号与默认克重的映射",
    )
    op.create_index("idx_ps_mapping_status_qty", "ark_product_sales_name_mappings", ["status", "quantity_total"])


def downgrade():
    op.drop_index("idx_ps_mapping_status_qty", table_name="ark_product_sales_name_mappings")
    op.drop_table("ark_product_sales_name_mappings")
