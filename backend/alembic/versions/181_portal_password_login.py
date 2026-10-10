"""Add managed customer passwords without activating historical accounts.

Revision ID: 181_portal_password_login
Revises: 180_settlement_funding_amendment
"""
from alembic import op
import sqlalchemy as sa

revision = '181_portal_password_login'
down_revision = '180_settlement_funding_amendment'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ark_order_portal_accounts', sa.Column('password_hash', sa.String(255), nullable=True,
        comment='员工设置的采购账号密码哈希；历史无密码账号不可登录'))


def downgrade():
    raise RuntimeError('Customer credential rollback requires reviewed data preservation; do not drop password hashes')
