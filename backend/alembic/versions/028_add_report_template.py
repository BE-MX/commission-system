"""add report template table

Revision ID: 028_add_report_template
Revises: 027_add_process_reporting
Create Date: 2026-06-03 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "028_add_report_template"
down_revision: Union[str, None] = "027_add_process_reporting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ark_report_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_code", sa.String(64), nullable=False, comment="报表编码，如 production_order_print"),
        sa.Column("name", sa.String(200), nullable=False, comment="显示名称"),
        sa.Column("description", sa.String(500), nullable=True, comment="报表描述"),
        sa.Column(
            "template_content",
            mysql.LONGTEXT,
            nullable=False,
            comment=".mrt 模板 JSON 内容",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="模板版本号"),
        sa.Column(
            "status",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
            comment="0=禁用,1=启用",
        ),
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
        sa.UniqueConstraint("report_code", name="uk_report_code"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        comment="报表模板表",
    )
    op.create_index("idx_report_templates_status", "ark_report_templates", ["status"])


def downgrade() -> None:
    op.drop_index("idx_report_templates_status", table_name="ark_report_templates")
    op.drop_table("ark_report_templates")
