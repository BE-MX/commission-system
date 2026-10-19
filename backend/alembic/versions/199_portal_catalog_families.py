"""Add portal product families, color swatches and catalog family/grade links.

Additive only: existing catalog items keep NULL family/grade and stay visible
exactly as before until an administrator assigns them.
"""
from alembic import op
import sqlalchemy as sa

revision = "199_portal_catalog_families"
down_revision = "198_customer_media_playback"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _record_columns():
    return [
        sa.Column("id", ID, autoincrement=True, nullable=False, comment="数据库主键"),
        sa.Column("public_id", sa.String(length=36), nullable=False, comment="对外稳定UUID，不承载授权"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间，北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="最后修改时间，北京时间"),
        sa.Column("row_version", sa.BigInteger(), nullable=False, comment="并发更新版本"),
    ]


def upgrade():
    op.create_table(
        "ark_order_portal_product_families",
        sa.Column("site_id", ID, nullable=False, comment="门户sites关联记录"),
        sa.Column("code", sa.String(length=32), nullable=False, comment="产品族稳定编码"),
        sa.Column("display_name", sa.String(length=128), nullable=False, comment="客户可见产品族名称"),
        sa.Column("sale_unit", sa.String(length=32), nullable=False, comment="销售单位，须与成员商品一致"),
        sa.Column("unit_weight_grams", sa.Numeric(14, 6), nullable=False, comment="每销售单位克重，用于总重与运费"),
        sa.Column("min_qty", sa.BigInteger(), nullable=False, comment="最小购买数量（销售单位）"),
        sa.Column("step_qty", sa.BigInteger(), nullable=False, comment="购买步长（销售单位）"),
        sa.Column("out_of_stock_below", sa.Numeric(14, 6), nullable=False, comment="低于该可用量显示无货（销售单位）"),
        sa.Column("allowed_grades", sa.JSON(), nullable=False, comment="向客户展示的工艺档列表"),
        sa.Column("sort_order", sa.BigInteger(), nullable=False, comment="目录展示顺序"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="受服务层状态机约束的业务状态"),
        *_record_columns(),
        sa.CheckConstraint("status IN ('enabled','disabled')", name="ck_op_family_status"),
        sa.CheckConstraint("unit_weight_grams > 0 AND min_qty > 0 AND step_qty > 0 AND out_of_stock_below >= 0",
                           name="ck_op_family_quantity"),
        sa.ForeignKeyConstraint(["site_id"], ["ark_order_portal_sites.id"], name="fk_op_families_site_id",
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "code", name="uq_op_family_code"),
        sa.UniqueConstraint("public_id", name="uq_op_family_public_id"),
        comment="客户下单门户产品族",
    )
    op.create_table(
        "ark_order_portal_color_swatches",
        sa.Column("site_id", ID, nullable=False, comment="门户sites关联记录"),
        sa.Column("color_key", sa.String(length=64), nullable=False, comment="规范化色号键，与标准SKU颜色匹配"),
        sa.Column("color_code", sa.String(length=64), nullable=False, comment="客户可见标准色号写法"),
        sa.Column("display_name", sa.String(length=128), nullable=True, comment="可选颜色展示名"),
        sa.Column("image_asset_id", sa.String(length=64), nullable=True, comment="受管理图片资产引用"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="受服务层状态机约束的业务状态"),
        *_record_columns(),
        sa.CheckConstraint("status IN ('enabled','disabled')", name="ck_op_swatch_status"),
        sa.ForeignKeyConstraint(["site_id"], ["ark_order_portal_sites.id"], name="fk_op_swatches_site_id",
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "color_key", name="uq_op_swatch_color"),
        sa.UniqueConstraint("public_id", name="uq_op_swatch_public_id"),
        comment="客户下单门户色块图库",
    )
    op.add_column("ark_order_portal_catalog_items",
                  sa.Column("family_id", ID, nullable=True, comment="门户product_families关联记录"))
    op.add_column("ark_order_portal_catalog_items",
                  sa.Column("grade", sa.String(length=16), nullable=True, comment="工艺档 standard/super/ultra"))
    op.create_index("ix_op_catalog_family_grade", "ark_order_portal_catalog_items", ["family_id", "grade"])
    # SQLite (isolated tests) cannot ALTER in constraints; MySQL gets the real FK and check.
    if op.get_context().dialect.name != "sqlite":
        op.create_foreign_key("fk_op_catalog_items_family_id", "ark_order_portal_catalog_items",
                              "ark_order_portal_product_families", ["family_id"], ["id"], ondelete="RESTRICT")
        op.create_check_constraint(
            "ck_op_catalog_family_grade", "ark_order_portal_catalog_items",
            "(family_id IS NULL AND grade IS NULL) OR "
            "(family_id IS NOT NULL AND grade IN ('standard','super','ultra'))")


def downgrade():
    raise RuntimeError("Portal catalog configuration must be preserved; disable families instead of downgrading")
