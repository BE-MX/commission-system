"""expo try-on: dedicated hair color library (swatch image + description)

Revision ID: 048_expo_hair_colors
Revises: 047_expo_color_scene
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "048_expo_hair_colors"
down_revision = "047_expo_color_scene"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 展会试戴发色库：参照发型库独立维护，色板图 + 颜色描述直接喂给合成管线
    op.create_table(
        "ark_expo_hair_colors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False, comment="色号，如 1B / 613"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="如 自然黑"),
        sa.Column("hex_code", sa.String(length=16), nullable=True, comment="UI 色块展示，可由色板图自动提取"),
        sa.Column("swatch_path", sa.String(length=512), nullable=True, comment="色板图相对路径，随合成请求送入模型"),
        sa.Column("color_description", sa.Text(), nullable=True, comment="喂给合成 prompt 的颜色描述"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_ark_expo_hair_colors_code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_expo_hair_colors_active", "ark_expo_hair_colors", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_ark_expo_hair_colors_active", table_name="ark_expo_hair_colors")
    op.drop_table("ark_expo_hair_colors")
