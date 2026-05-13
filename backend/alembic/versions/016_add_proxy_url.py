"""add proxy_url to ark_insight_sources

Revision ID: 016_add_proxy_url
Revises: 015_add_exclude_keywords
Create Date: 2026-05-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '016_add_proxy_url'
down_revision = '015_add_exclude_keywords'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {col['name'] for col in inspector.get_columns('ark_insight_sources')}

    if 'proxy_url' not in existing_cols:
        op.add_column(
            'ark_insight_sources',
            sa.Column('proxy_url', sa.String(255), nullable=True, comment='HTTP 代理地址（如 http://127.0.0.1:1080），NULL 或不填则直连'),
        )


def downgrade() -> None:
    op.drop_column('ark_insight_sources', 'proxy_url')
