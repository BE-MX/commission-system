"""验货单详情接口契约：每张照片要带上上传人与上传时间，前端照片墙按张展示。"""
from app.shipping_inspection import service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from tests.test_shipping_inspection import _user


def test_record_detail_photos_carry_uploader_name_and_time(db):
    inspector = _user(db)
    inspection = ShippingInspection(outbound_record_id='OB001', outbound_no='T-1', status='submitted',
                                    photo_count=1, created_by=inspector.id)
    db.add(inspection)
    db.flush()
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, file_path='shipping-inspection/a.jpg',
                                   created_by=inspector.id))
    db.commit()

    photo = service.get_record_detail(db, inspection.id)['photos'][0]

    assert photo['created_by_name'] == inspector.real_name
    assert photo['created_at'] is not None


def test_legacy_photo_without_uploader_keeps_time_and_null_name(db):
    inspection = ShippingInspection(outbound_record_id='OB002', outbound_no='T-2', status='submitted', photo_count=1)
    db.add(inspection)
    db.flush()
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, file_path='shipping-inspection/legacy.jpg',
                                   created_by=None))
    db.commit()

    photo = service.get_record_detail(db, inspection.id)['photos'][0]

    assert photo['created_by_name'] is None
    assert photo['created_at'] is not None
