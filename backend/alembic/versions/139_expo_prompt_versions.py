"""Make expo image prompts editable and snapshot every new generation.

Revision ID: 139_expo_prompt_versions
Revises: 138_public_pool_rules
"""

import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.core.time import beijing_now

revision = "139_expo_prompt_versions"
down_revision = "138_public_pool_rules"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_expo_prompt_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="提示词版本ID"),
        sa.Column("name", sa.String(80), nullable=False, comment="版本名称，显示于试戴选择器"),
        sa.Column("hint", sa.String(160), nullable=False, comment="客户可见的版本说明"),
        sa.Column("config_json", sa.JSON(), nullable=False, comment="完整合成提示词配置"),
        sa.Column("revision", sa.Integer(), nullable=False, comment="保存时递增的修订号"),
        sa.Column("is_active", sa.Boolean(), nullable=False, comment="是否允许新生成选择"),
        sa.Column("default_slot", sa.Integer(), nullable=True, comment="默认版本为1，其余为NULL"),
        sa.Column("updated_by", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                  sa.ForeignKey("ark_users.id"), nullable=True, comment="最后修改用户ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="修改北京时间"),
        sa.UniqueConstraint("name", name="uq_expo_prompt_version_name"),
        sa.UniqueConstraint("default_slot", name="uq_expo_prompt_default"),
        sa.CheckConstraint("default_slot IS NULL OR (default_slot = 1 AND is_active = 1)",
                           name="ck_expo_prompt_default_active"),
        comment="展会AI试戴-可配置生图提示词版本",
    )
    with op.batch_alter_table("ark_expo_results") as batch:
        batch.add_column(sa.Column("prompt_version_id", sa.BigInteger(), nullable=True,
                                   comment="本次选择的提示词版本；历史记录为空"))
        batch.add_column(sa.Column("prompt_snapshot", sa.JSON(), nullable=True,
                                   comment="生成请求时的最终提示词、版本和输入快照；历史为空"))
        batch.create_foreign_key("fk_expo_result_prompt_version", "ark_expo_prompt_versions",
                                 ["prompt_version_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("idx_expo_result_prompt_version", ["prompt_version_id"])

    # A migration-owned, frozen copy of the rolled-back production prompts.
    # Runtime never reads this file or overwrites operator edits with these values.
    records = json.loads((Path(__file__).parents[1] / "data/139_expo_prompt_versions.json").read_text(encoding="utf-8"))
    now = beijing_now()
    table = sa.table(
        "ark_expo_prompt_versions", sa.column("id", sa.BigInteger()),
        sa.column("name", sa.String()), sa.column("hint", sa.String()),
        sa.column("config_json", sa.JSON()), sa.column("revision", sa.Integer()),
        sa.column("is_active", sa.Boolean()), sa.column("default_slot", sa.Integer()),
        sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()),
    )
    op.bulk_insert(table, [{**row, "created_at": now, "updated_at": now} for row in records])


def downgrade():
    with op.batch_alter_table("ark_expo_results") as batch:
        batch.drop_constraint("fk_expo_result_prompt_version", type_="foreignkey")
        batch.drop_index("idx_expo_result_prompt_version")
        batch.drop_column("prompt_snapshot")
        batch.drop_column("prompt_version_id")
    op.drop_table("ark_expo_prompt_versions")
