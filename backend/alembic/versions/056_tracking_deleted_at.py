"""add deleted_at soft-delete column to shipment_tracking

删除运单端点此前复用 is_active（轮询开关）当软删标志：is_active 的真实语义是
「是否继续轮询（签收/超期后置0）」，且列表查询从不排除该值，导致点删除提示成功
但运单仍在列表中。新增独立 deleted_at 列，把「用户删除」与「停止轮询」语义分离。

Revision ID: 056_tracking_deleted_at
Revises: 055_enrich_comments
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa


revision = "056_tracking_deleted_at"
down_revision = "055_enrich_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shipment_tracking",
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            nullable=True,
            comment="软删除时间（用户删除；与 is_active 轮询开关语义分离）",
        ),
    )


def downgrade() -> None:
    op.drop_column("shipment_tracking", "deleted_at")
