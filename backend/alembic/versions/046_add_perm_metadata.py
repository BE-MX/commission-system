"""permission metadata + audit table (权限重设计方案)

Revision ID: 046_perm_metadata
Revises: 045_expo_tryon
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "046_perm_metadata"
down_revision = "045_expo_tryon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ark_permissions", sa.Column(
        "kind", sa.String(length=16), nullable=False, server_default="action",
        comment="page=页面可见/action=操作/data=数据范围"))
    op.add_column("ark_permissions", sa.Column(
        "is_legacy", sa.Integer(), nullable=False, server_default="0",
        comment="1=已下架，UI 不展示，端点暂保留兼容"))
    op.add_column("ark_permissions", sa.Column(
        "sort", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "ark_permission_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("role_name", sa.String(length=50), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(length=64), nullable=True),
        sa.Column("added_codes", sa.JSON(), nullable=True),
        sa.Column("removed_codes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_ark_perm_audit_role", "ark_permission_audit", ["role_id"])


def downgrade() -> None:
    op.drop_index("idx_ark_perm_audit_role", table_name="ark_permission_audit")
    op.drop_table("ark_permission_audit")
    op.drop_column("ark_permissions", "sort")
    op.drop_column("ark_permissions", "is_legacy")
    op.drop_column("ark_permissions", "kind")
