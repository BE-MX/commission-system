"""Preserve cancelled delivery history while releasing unit reservations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '206_domestic_shipment_cancel'
down_revision = '205_domestic_item_termination'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ark_domestic_shipments') as batch:
        batch.add_column(sa.Column('cancelled_at', sa.DateTime(), nullable=True, comment='批次取消时间，北京时间'))
        batch.add_column(sa.Column('cancelled_by', mysql.INTEGER(unsigned=True).with_variant(sa.Integer(), 'sqlite'), nullable=True, comment='批次取消人ID'))
        batch.add_column(sa.Column('cancelled_units', sa.JSON(), nullable=True, comment='取消时各批次明细的件ID和件号快照'))
        batch.create_foreign_key('fk_dom_shipment_cancelled_by', 'ark_users', ['cancelled_by'], ['id'])


def downgrade():
    raise RuntimeError('Cancellation audit evidence must not be dropped automatically')
