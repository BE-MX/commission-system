"""add data governance module (3 tables)

Revision ID: 030_add_data_governance
Revises: 029_add_report_template_versions
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "030_add_data_governance"
down_revision: Union[str, None] = "029_add_report_template_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. data_concepts ──────────────────────────────────────
    op.create_table(
        "data_concepts",
        sa.Column("id", sa.String(64), nullable=False, comment="概念ID，snake_case，如 sales_revenue"),
        sa.Column("name_zh", sa.String(50), nullable=False, comment="中文名"),
        sa.Column("name_en", sa.String(100), nullable=False, comment="英文名"),
        sa.Column(
            "layer",
            sa.Enum("financial", "customer", "product", "production", "sales_process", "logistics", name="concept_layer"),
            nullable=False,
            comment="所属层级",
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "pending", "in_progress", "review", "active", "deprecated", name="concept_status"),
            nullable=False,
            server_default="draft",
            comment="概念状态",
        ),
        sa.Column(
            "priority",
            sa.Enum("P1", "P2", "P3", name="concept_priority"),
            nullable=True,
            comment="待补充优先级",
        ),
        sa.Column("one_liner", sa.String(60), nullable=True, comment="一句话定义"),
        sa.Column("full_definition", sa.Text(), nullable=True, comment="完整定义（Markdown）"),
        sa.Column("boundary_includes", sa.JSON(), nullable=True, comment="包含范围标签列表"),
        sa.Column("boundary_excludes", sa.JSON(), nullable=True, comment="排除范围标签列表"),
        sa.Column("formula", sa.Text(), nullable=True, comment="计算公式"),
        sa.Column("numerator", sa.String(200), nullable=True, comment="分子"),
        sa.Column("denominator", sa.String(200), nullable=True, comment="分母"),
        sa.Column("unit", sa.String(20), nullable=True, comment="单位"),
        sa.Column("primary_table", sa.String(100), nullable=True, comment="主数据表"),
        sa.Column("primary_field", sa.String(100), nullable=True, comment="主字段"),
        sa.Column("filter_conditions", sa.JSON(), nullable=True, comment="过滤条件列表"),
        sa.Column("related_tables", sa.JSON(), nullable=True, comment="关联表列表"),
        sa.Column("time_granularity", sa.JSON(), nullable=True, comment="时间粒度多选"),
        sa.Column("entity_granularity", sa.String(100), nullable=True, comment="实体粒度"),
        sa.Column("segments", sa.JSON(), nullable=True, comment="可切分维度列表"),
        sa.Column("owner", sa.String(100), nullable=True, comment="负责人/模块"),
        sa.Column("staleness_trigger", sa.Text(), nullable=True, comment="失效触发条件"),
        sa.Column(
            "confidence",
            sa.Enum("high", "medium", "low", name="concept_confidence"),
            nullable=True,
            comment="置信度",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="补充备注"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人 user_id"),
        sa.Column("updated_by", sa.Integer(), nullable=True, comment="最后修改人 user_id"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="数据概念注册表",
    )
    op.create_index("idx_data_concepts_layer", "data_concepts", ["layer"])
    op.create_index("idx_data_concepts_status", "data_concepts", ["status"])

    # ── 2. concept_relationships ──────────────────────────────
    op.create_table(
        "concept_relationships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "source_concept_id", sa.String(64), nullable=False,
            comment="源概念ID FK→data_concepts.id",
        ),
        sa.Column(
            "target_concept_id", sa.String(64), nullable=False,
            comment="目标概念ID FK→data_concepts.id",
        ),
        sa.Column(
            "relation_type",
            sa.Enum(
                "parent_of", "composed_of", "derived_from",
                "influences", "conflicts_with", "requires",
                "leads", "lags",
                name="relation_type",
            ),
            nullable=False,
            comment="关联类型",
        ),
        sa.Column("description", sa.String(200), nullable=True, comment="关联备注说明"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人 user_id"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "is_auto_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否由系统自动生成（如 conflicts_with 反向边）",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["source_concept_id"], ["data_concepts.id"],
            ondelete="CASCADE", name="fk_rel_source_concept",
        ),
        sa.ForeignKeyConstraint(
            ["target_concept_id"], ["data_concepts.id"],
            ondelete="CASCADE", name="fk_rel_target_concept",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="概念关联关系",
    )
    op.create_index(
        "idx_concept_rels_source", "concept_relationships", ["source_concept_id"],
    )
    op.create_index(
        "idx_concept_rels_target", "concept_relationships", ["target_concept_id"],
    )
    op.create_index(
        "uk_concept_rels_pair",
        "concept_relationships",
        ["source_concept_id", "target_concept_id", "relation_type"],
        unique=True,
    )

    # ── 3. concept_change_logs ────────────────────────────────
    op.create_table(
        "concept_change_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "concept_id", sa.String(64), nullable=False,
            comment="概念ID FK→data_concepts.id",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="操作时间",
        ),
        sa.Column("operator", sa.String(64), nullable=True, comment="操作人"),
        sa.Column(
            "action",
            sa.Enum(
                "create", "edit", "submit", "approve", "reject", "deprecate", "rollback",
                name="change_action",
            ),
            nullable=False,
            comment="操作类型",
        ),
        sa.Column("changed_fields", sa.JSON(), nullable=True, comment="变更字段 before/after"),
        sa.Column("comment", sa.String(500), nullable=True, comment="操作备注"),
        sa.Column("snapshot", sa.JSON(), nullable=True, comment="操作时概念完整快照"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["data_concepts.id"],
            ondelete="CASCADE", name="fk_changelog_concept",
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="概念变更记录",
    )
    op.create_index(
        "idx_change_logs_concept", "concept_change_logs", ["concept_id"],
    )
    op.create_index(
        "idx_change_logs_timestamp", "concept_change_logs", ["timestamp"],
    )


def downgrade() -> None:
    op.drop_index("idx_change_logs_timestamp", table_name="concept_change_logs")
    op.drop_index("idx_change_logs_concept", table_name="concept_change_logs")
    op.drop_table("concept_change_logs")

    op.drop_index("uk_concept_rels_pair", table_name="concept_relationships")
    op.drop_index("idx_concept_rels_target", table_name="concept_relationships")
    op.drop_index("idx_concept_rels_source", table_name="concept_relationships")
    op.drop_table("concept_relationships")

    op.drop_index("idx_data_concepts_status", table_name="data_concepts")
    op.drop_index("idx_data_concepts_layer", table_name="data_concepts")
    op.drop_table("data_concepts")
