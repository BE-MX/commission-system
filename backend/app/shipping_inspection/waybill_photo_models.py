"""Private waybill evidence; deliberately separate from printable inspection media."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String
from app.core.database import Base
from app.core.time import beijing_now


class ShippingWaybillPhoto(Base):
    __tablename__ = 'ark_shipping_waybill_photos'
    __table_args__ = (Index('idx_waybill_photo_inspection', 'inspection_id'),
                      Index('idx_waybill_photo_shipment', 'shipment_tracking_id'),
                      {'comment': '验货单物流单照片'})
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    inspection_id = Column(BigInteger, ForeignKey('ark_shipping_inspections.id', ondelete='RESTRICT'), nullable=False, comment='验货单')
    shipment_tracking_id = Column(BigInteger, ForeignKey('shipment_tracking.id', ondelete='RESTRICT'), comment='关联物流记录；空为待提交')
    rectified_path = Column(String(255), nullable=False, comment='增强裁正图相对路径')
    original_path = Column(String(255), nullable=False, comment='原图相对路径')
    ocr_recipient_country = Column(String(128), comment='原图识别的收件国家事实；不随用户编辑覆盖')
    ocr_recipient_name = Column(String(256), comment='原图识别的收件人事实；不随用户编辑覆盖')
    number_source = Column(String(16), nullable=False, default='manual', comment='barcode/ocr/manual')
    sync_result = Column(String(16), nullable=False, default='skipped', comment='found/not_found/failed/unsupported/skipped')
    token = Column(String(64), nullable=False, unique=True, comment='一次性关联凭证')
    replaced_at = Column(DateTime, comment='替换时间')
    replaced_by = Column(Integer, comment='替换人')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='拍摄时间（北京时间）')
    created_by = Column(Integer, nullable=False, comment='拍摄人')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时间）')
    updated_by = Column(Integer, nullable=False, comment='更新人')
