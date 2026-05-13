"""add exclude_keywords to ark_insight_sources

Revision ID: 015_add_exclude_keywords
Revises: 014_add_tracking_push_and_daily_report
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '015_add_exclude_keywords'
down_revision = '014_tracking_push'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {col['name'] for col in inspector.get_columns('ark_insight_sources')}

    if 'exclude_keywords' not in existing_cols:
        op.add_column(
            'ark_insight_sources',
            sa.Column('exclude_keywords', sa.JSON, nullable=True, comment='排除关键词过滤（JSON数组，命中任一丢弃）'),
        )


def downgrade() -> None:
    op.drop_column('ark_insight_sources', 'exclude_keywords')
