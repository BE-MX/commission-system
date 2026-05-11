"""add ark_waybills table for waybill upload

Revision ID: 011_add_waybill_upload
Revises: 010_add_insight_module
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011_add_waybill_upload'
down_revision = '010_add_insight_module'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ark_waybills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('waybill_no', sa.String(50), nullable=False, comment='运单号（唯一）'),
        sa.Column('carrier', sa.String(50), nullable=False, server_default='未知', comment='物流商：FedEx/DHL/UPS/未知'),
        sa.Column('recipient_name', sa.String(100), nullable=False, comment='收件人姓名'),
        sa.Column('recipient_country', sa.String(100), nullable=False, comment='收件国家'),
        sa.Column('ship_date', sa.Date(), nullable=False, comment='发件日期'),
        sa.Column('status', sa.String(20), nullable=False, server_default='待跟踪', comment='状态：待跟踪/运输中/已签收/异常'),
        sa.Column('entry_source', sa.String(20), nullable=False, server_default='manual', comment='录入来源：ocr/manual'),
        sa.Column('created_by', sa.String(50), nullable=False, comment='录入人（登录用户名）'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('waybill_no', name='uk_waybill_no'),
        sa.Index('idx_waybill_carrier', 'carrier'),
        sa.Index('idx_waybill_ship_date', 'ship_date'),
        sa.Index('idx_waybill_created_by', 'created_by'),
        sa.Index('idx_waybill_status', 'status'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
        comment='运单信息表（图片 OCR / 手动录入）',
    )


def downgrade() -> None:
    op.drop_table('ark_waybills')
