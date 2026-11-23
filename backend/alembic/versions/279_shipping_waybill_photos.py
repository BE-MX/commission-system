"""Private waybill capture evidence, separate from printable inspection media."""
from alembic import op
import sqlalchemy as sa

revision = '279_shipping_waybill_photos'
down_revision = '278_devlog_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_shipping_waybill_photos',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('inspection_id', sa.BigInteger(), sa.ForeignKey('ark_shipping_inspections.id', ondelete='RESTRICT'), nullable=False, comment='验货单'),
        sa.Column('shipment_tracking_id', sa.BigInteger(), sa.ForeignKey('shipment_tracking.id', ondelete='RESTRICT'), comment='关联物流记录；空为待提交'),
        sa.Column('rectified_path', sa.String(255), nullable=False, comment='增强裁正图相对路径'),
        sa.Column('original_path', sa.String(255), nullable=False, comment='原图相对路径'),
        sa.Column('ocr_recipient_country', sa.String(128), comment='原图识别的收件国家事实；不随用户编辑覆盖'),
        sa.Column('ocr_recipient_name', sa.String(256), comment='原图识别的收件人事实；不随用户编辑覆盖'),
        sa.Column('number_source', sa.String(16), nullable=False, comment='barcode/ocr/manual'),
        sa.Column('sync_result', sa.String(16), nullable=False, comment='found/not_found/failed/unsupported/skipped'),
        sa.Column('token', sa.String(64), nullable=False, unique=True, comment='一次性关联凭证'),
        sa.Column('replaced_at', sa.DateTime(), comment='替换时间'),
        sa.Column('replaced_by', sa.Integer(), comment='替换人'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='拍摄时间（北京时间）'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='拍摄人'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间（北京时间）'),
        sa.Column('updated_by', sa.Integer(), nullable=False, comment='更新人'),
        comment='验货单物流单照片')
    op.create_index('idx_waybill_photo_inspection', 'ark_shipping_waybill_photos', ['inspection_id'])
    op.create_index('idx_waybill_photo_shipment', 'ark_shipping_waybill_photos', ['shipment_tracking_id'])


def downgrade():
    op.drop_table('ark_shipping_waybill_photos')
