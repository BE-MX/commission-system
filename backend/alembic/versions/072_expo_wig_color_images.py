"""expo try-on: per-(wig, hair color) 3-angle reference image sets

Revision ID: 072_expo_wig_color_images
Revises: 071_invoice_packaging_qty
Create Date: 2026-07-15

发型×发色关联：每个组合备三角度实拍参考图，合成时按选择匹配唯一颜色的图组
（参考图本身即目标色，取代文字/色板图上色）。稀疏存储，只存备了图的组合。
"""

from alembic import op
import sqlalchemy as sa


revision = "072_expo_wig_color_images"
down_revision = "071_invoice_packaging_qty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FK 用 BigInteger 与目标 PK（ark_expo_wigs.id / ark_expo_hair_colors.id，均 signed BIGINT）
    # 完全一致——ExpoResult.wig_id 同款 FK 已在 045 验证可用
    op.create_table(
        "ark_expo_wig_colors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("wig_id", sa.BigInteger(), nullable=False, comment="发型 ark_expo_wigs.id"),
        sa.Column("hair_color_id", sa.BigInteger(), nullable=False, comment="发色 ark_expo_hair_colors.id"),
        sa.Column("angle_photos", sa.JSON(), nullable=True, comment="该发型该发色的三角度参考图路径列表"),
        sa.Column("cover_path", sa.String(length=512), nullable=True, comment="缩略图相对路径，默认取首张"),
        sa.Column("is_active", sa.SmallInteger(), nullable=False, server_default="1", comment="1=启用,0=停用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["wig_id"], ["ark_expo_wigs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hair_color_id"], ["ark_expo_hair_colors.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("wig_id", "hair_color_id", name="uq_ark_expo_wig_colors_pair"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="展会AI试戴-发型×发色组合三角度参考图（合成按选择匹配唯一颜色图组）",
    )
    op.create_index("idx_ark_expo_wig_colors_wig", "ark_expo_wig_colors", ["wig_id"])


def downgrade() -> None:
    op.drop_index("idx_ark_expo_wig_colors_wig", table_name="ark_expo_wig_colors")
    op.drop_table("ark_expo_wig_colors")
