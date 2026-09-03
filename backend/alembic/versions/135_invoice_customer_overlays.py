"""Add invoice customer overlay table (manual OKKI customer sync).

发票录入的客户搜索读 lsordertest.customer_info 只读镜像，OKKI 新客户/负责人
变更存在同步延迟，私海过滤下查不到客户。手动同步（OKKI 客户查重+详情接口）
结果落方舟自有 overlay 表，不碰业务库只读红线；搜索合并两源，镜像追上后
（update_time 新于 overlay 的 source_update_time）自动让位回镜像。

Revision ID: 135_invoice_customer_overlays
Revises: 134_domestic_credit_shipdate
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "135_invoice_customer_overlays"
down_revision = "134_domestic_credit_shipdate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_invoice_customer_overlays",
        sa.Column("company_id", sa.String(64), nullable=False, comment="OKKI company_id"),
        sa.Column("company_name", sa.String(256), nullable=False, comment="公司名称"),
        sa.Column("country_name", sa.String(128), nullable=True, comment="国家/地区"),
        sa.Column("origin_name", sa.String(128), nullable=True, comment="客户来源"),
        sa.Column("archive_type", sa.String(64), nullable=True, comment="建档类型"),
        sa.Column("trail_status_name", sa.String(64), nullable=True, comment="客户阶段名称"),
        sa.Column("owner_user_ids", sa.JSON(), nullable=True, comment="归属 OKKI 用户 ID 数组（空=公海）"),
        sa.Column("source_update_time", sa.String(32), nullable=True, comment="OKKI 侧 update_time（与镜像比新旧用）"),
        sa.Column("synced_by", sa.Integer(), nullable=True, comment="最近一次手动同步操作人 user_id"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="首次同步时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="最近同步时间",
        ),
        sa.PrimaryKeyConstraint("company_id"),
        comment="发票客户手动同步 overlay（补只读镜像延迟，镜像追上后自动让位）",
    )


def downgrade() -> None:
    op.drop_table("ark_invoice_customer_overlays")
