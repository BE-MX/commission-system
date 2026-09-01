"""Add shipping inspection tables (OKKI outbound inspection loop).

Revision ID: 128_shipping_inspection
Revises: 127_domestic_route_rules
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "128_shipping_inspection"
down_revision = "127_domestic_route_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_shipping_inspections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("outbound_record_id", sa.String(64), nullable=False, comment="OKKI 出库单 id"),
        sa.Column("outbound_no", sa.String(64), nullable=True, comment="出库单号（冗余，便于检索与展示）"),
        sa.Column("customer_name", sa.String(256), nullable=True, comment="客户名（冗余，列表展示用）"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", comment="draft=草稿,submitted=已提交"),
        sa.Column("photo_count", sa.Integer(), nullable=False, server_default="0", comment="提交时照片总数（列表页免 join）"),
        sa.Column("remark", sa.String(500), nullable=True, comment="备注"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True, comment="提交时间"),
        sa.Column("submitted_by", sa.BigInteger(), nullable=True, comment="提交人（ark_users.id）"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人"),
        sa.Column("updated_by", sa.Integer(), nullable=True, comment="更新人"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbound_record_id", name="uq_shipping_inspection_outbound"),
        comment="发货检验单",
    )
    op.create_index("idx_shipping_inspection_outbound_no", "ark_shipping_inspections", ["outbound_no"])

    op.create_table(
        "ark_shipping_inspection_photos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("inspection_id", sa.BigInteger(), nullable=False, comment="检验单 id"),
        sa.Column("item_id", sa.String(64), nullable=True, comment="出库明细 id；NULL=整单照片"),
        sa.Column("file_path", sa.String(255), nullable=False, comment="相对路径（file_service 约定）"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0", comment="展示顺序"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="上传人"),
        sa.ForeignKeyConstraint(
            ["inspection_id"],
            ["ark_shipping_inspections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="发货检验照片",
    )
    op.create_index(
        "idx_shipping_inspection_photo_inspection",
        "ark_shipping_inspection_photos",
        ["inspection_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_shipping_inspection_photo_inspection", table_name="ark_shipping_inspection_photos")
    op.drop_table("ark_shipping_inspection_photos")
    op.drop_index("idx_shipping_inspection_outbound_no", table_name="ark_shipping_inspections")
    op.drop_table("ark_shipping_inspections")
