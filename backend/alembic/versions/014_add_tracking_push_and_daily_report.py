"""add tracking push fields and daily report table

Revision ID: 014_add_tracking_push_and_daily_report
Revises: 013_add_ark_short_links
Create Date: 2026-05-12

"""
from alembic import op
import sqlalchemy as sa


revision = '014_tracking_push'
down_revision = '013_add_ark_short_links'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. shipment_tracking 新增 unified_status 和 last_pushed_status
    op.add_column(
        'shipment_tracking',
        sa.Column('unified_status', sa.String(length=30), nullable=True, comment='统一状态码'),
    )
    op.add_column(
        'shipment_tracking',
        sa.Column('last_pushed_status', sa.String(length=30), nullable=True, comment='上次推送时的状态，防重复推送'),
    )
    op.create_index('idx_tracking_unified_status', 'shipment_tracking', ['unified_status'])

    # 2. 新建物流日报表
    op.create_table(
        'ark_shipping_daily_reports',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='所属用户ID'),
        sa.Column('report_date', sa.Date(), nullable=False, comment='日报日期'),
        sa.Column('html_content', sa.Text(), nullable=False, comment='日报HTML内容'),
        sa.Column('short_url', sa.String(length=100), nullable=True, comment='日报短链'),
        sa.Column('is_pushed', sa.Boolean(), nullable=False, server_default='0', comment='是否已推送'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('user_id', 'report_date', name='uk_user_date'),
        comment='物流日报',
    )


def downgrade() -> None:
    op.drop_table('ark_shipping_daily_reports')
    op.drop_index('idx_tracking_unified_status', table_name='shipment_tracking')
    op.drop_column('shipment_tracking', 'last_pushed_status')
    op.drop_column('shipment_tracking', 'unified_status')
