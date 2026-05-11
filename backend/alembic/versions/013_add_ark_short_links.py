"""add ark_short_links table

Revision ID: 013_add_ark_short_links
Revises: 012_add_estimated_delivery_date
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa


revision = '013_add_ark_short_links'
down_revision = '012_add_estimated_delivery_date'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ark_short_links',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('short_code', sa.String(length=8), nullable=False, comment='短码（6位 MD5 前缀，预留 2 位扩展）'),
        sa.Column('original_url', sa.Text(), nullable=False, comment='原始 URL'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False, comment='生成时间'),
        sa.Column('click_count', sa.Integer(), nullable=False, server_default='0', comment='点击次数'),
        sa.UniqueConstraint('short_code', name='uq_ark_short_links_code'),
        comment='短链接记录表',
    )
    op.create_index('idx_short_code', 'ark_short_links', ['short_code'])


def downgrade() -> None:
    op.drop_index('idx_short_code', table_name='ark_short_links')
    op.drop_table('ark_short_links')
