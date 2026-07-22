"""asset: tag taxonomy v2 支撑列

标签体系重构（docs/requirements/2026-07-22-asset-tag-taxonomy.md）：
- ark_tag_dimensions.is_visible  维度可见开关——新旧体系并存/退役的执行机制
- ark_tag_dimensions.is_managed  系统托管维度（如色系，由推导脚本独占写入，禁人工编辑值）
- ark_tag_values.name_en/aliases 英文名与别名，外部 agent 检索匹配用
- ark_tag_values.parent_value_id 内容子类挂靠内容大类（自引用，unsigned 与 id 完全一致）
- ark_assets.orientation         画幅 landscape/portrait/square，自动计算不进人工标签

全部列 nullable 或带默认值，老代码 + 新 schema 过渡期兼容。

Revision ID: 078_tag_taxonomy_v2
Revises: 077_training_file_meta
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "078_tag_taxonomy_v2"
down_revision = "077_training_file_meta"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    # MySQL DDL 自动提交不可回滚，逐列幂等检查防半执行状态
    dim_cols = _existing_columns("ark_tag_dimensions")
    if "is_visible" not in dim_cols:
        op.add_column(
            "ark_tag_dimensions",
            sa.Column("is_visible", sa.SmallInteger, nullable=False, server_default="1",
                      comment="0=隐藏(前端筛选/上传/folder_upload匹配均不参与),1=可见"),
        )
    if "is_managed" not in dim_cols:
        op.add_column(
            "ark_tag_dimensions",
            sa.Column("is_managed", sa.SmallInteger, nullable=False, server_default="0",
                      comment="1=系统托管维度,值由派生脚本写入,禁人工增删改"),
        )

    val_cols = _existing_columns("ark_tag_values")
    if "name_en" not in val_cols:
        op.add_column(
            "ark_tag_values",
            sa.Column("name_en", sa.String(128), nullable=True, comment="英文名(agent 检索用)"),
        )
    if "aliases" not in val_cols:
        op.add_column(
            "ark_tag_values",
            sa.Column("aliases", sa.JSON, nullable=True, comment="别名数组(中英混合,agent 模糊匹配用)"),
        )
    if "parent_value_id" not in val_cols:
        # ark_tag_values.id 是 INT UNSIGNED，FK 列类型必须完全一致（含 unsigned）
        op.add_column(
            "ark_tag_values",
            sa.Column("parent_value_id", mysql.INTEGER(unsigned=True), nullable=True,
                      comment="父级标签值ID(内容子类→内容大类挂靠,仅该组维度使用)"),
        )
        op.create_foreign_key(
            "fk_tag_val_parent", "ark_tag_values", "ark_tag_values",
            ["parent_value_id"], ["id"],
        )

    asset_cols = _existing_columns("ark_assets")
    if "orientation" not in asset_cols:
        op.add_column(
            "ark_assets",
            sa.Column("orientation", sa.String(16), nullable=True,
                      comment="画幅 landscape/portrait/square,上传时自动计算,存量由回填脚本写入"),
        )


def downgrade():
    if "orientation" in _existing_columns("ark_assets"):
        op.drop_column("ark_assets", "orientation")

    val_cols = _existing_columns("ark_tag_values")
    if "parent_value_id" in val_cols:
        op.drop_constraint("fk_tag_val_parent", "ark_tag_values", type_="foreignkey")
        op.drop_column("ark_tag_values", "parent_value_id")
    if "aliases" in val_cols:
        op.drop_column("ark_tag_values", "aliases")
    if "name_en" in val_cols:
        op.drop_column("ark_tag_values", "name_en")

    dim_cols = _existing_columns("ark_tag_dimensions")
    if "is_managed" in dim_cols:
        op.drop_column("ark_tag_dimensions", "is_managed")
    if "is_visible" in dim_cols:
        op.drop_column("ark_tag_dimensions", "is_visible")
