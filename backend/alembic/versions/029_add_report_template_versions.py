"""add report template version history

Revision ID: 029_add_report_template_versions
Revises: 028_add_report_template
Create Date: 2026-06-03 01:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "029_add_report_template_versions"
down_revision: Union[str, None] = "028_add_report_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ark_report_template_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False, comment="关联 ark_report_templates.id"),
        sa.Column("version", sa.Integer(), nullable=False, comment="版本号"),
        sa.Column(
            "template_content",
            mysql.LONGTEXT,
            nullable=False,
            comment=".mrt 模板快照",
        ),
        sa.Column("change_summary", sa.String(500), nullable=True, comment="变更说明"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="操作人 user_id"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="报表模板版本历史",
    )
    op.create_index("idx_template_versions_template_id", "ark_report_template_versions", ["template_id"])
    op.create_index(
        "idx_template_versions_template_version",
        "ark_report_template_versions",
        ["template_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_template_versions_template_version", table_name="ark_report_template_versions")
    op.drop_index("idx_template_versions_template_id", table_name="ark_report_template_versions")
    op.drop_table("ark_report_template_versions")
