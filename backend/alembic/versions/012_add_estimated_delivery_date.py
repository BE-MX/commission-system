"""add estimated_delivery_date to tracking tables

Revision ID: 012_add_estimated_delivery_date
Revises: 011_add_waybill_upload
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012_add_estimated_delivery_date'
down_revision = '011_add_waybill_upload'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ark_waybills
    op.add_column(
        'ark_waybills',
        sa.Column('estimated_delivery_date', sa.DateTime(), nullable=True, comment='预计送达时间，来自承运商API，每次轮询覆盖更新'),
    )

    # shipment_tracking
    op.add_column(
        'shipment_tracking',
        sa.Column('estimated_delivery_date', sa.DateTime(), nullable=True, comment='预计送达时间，来自承运商API，每次轮询覆盖更新'),
    )

    # tracking_events
    op.add_column(
        'tracking_events',
        sa.Column('estimated_delivery_date', sa.DateTime(), nullable=True, comment='该次查询时承运商返回的预计送达时间'),
    )


def downgrade() -> None:
    op.drop_column('tracking_events', 'estimated_delivery_date')
    op.drop_column('shipment_tracking', 'estimated_delivery_date')
    op.drop_column('ark_waybills', 'estimated_delivery_date')
