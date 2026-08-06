"""design_image_library_prompt

提示词模板表 + 参考图库表（公库全员可见、私库仅创建者）。

Revision ID: 091_design_image_library_prompt
Revises: 090_expo_store_quota
Create Date: 2026-08-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# ark_users.id 在 MySQL 实际为 INT UNSIGNED；FK 列类型必须与目标列完全一致。
_UID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


revision: str = "091_design_image_library_prompt"
down_revision: Union[str, None] = "090_expo_store_quota"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ark_design_image_prompt_templates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, comment="模板分类"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="模板名称"),
        sa.Column("content", sa.Text(), nullable=False, comment="完整提示词模板，{key} 为参数占位"),
        sa.Column("options", sa.JSON(), nullable=True, comment="参数槽定义 [{key, label, choices[]}]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1"), comment="是否启用"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="排序权重，小在前"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_di_prompt_tpl_category", "category", "is_active", "sort"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="AI 生图提示词模板",
    )

    op.create_table(
        "ark_design_image_library_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default=sa.text("'private'"), comment="公库 public / 私库 private"),
        sa.Column("owner_user_id", _UID, nullable=False, comment="创建者（私库仅本人可见可用）"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=sa.text("''"), comment="图片标题"),
        sa.Column("storage_path", sa.String(length=512), nullable=False, comment="私有根目录下相对路径"),
        sa.Column("mime_type", sa.String(length=64), nullable=False, comment="MIME 类型"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, comment="文件字节数"),
        sa.Column("width", sa.Integer(), nullable=False, comment="图片宽度"),
        sa.Column("height", sa.Integer(), nullable=False, comment="图片高度"),
        sa.Column("sha256", sa.String(length=64), nullable=False, comment="文件 SHA-256"),
        sa.Column("created_by", _UID, nullable=False, comment="创建人"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="RESTRICT"),
        sa.Index("idx_di_library_scope_created", "scope", "deleted_at", "created_at"),
        sa.Index("idx_di_library_owner_scope", "owner_user_id", "scope"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="AI 生图参考图库",
    )


def downgrade() -> None:
    op.drop_table("ark_design_image_library_assets")
    op.drop_table("ark_design_image_prompt_templates")
