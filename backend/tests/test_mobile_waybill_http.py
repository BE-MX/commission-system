"""Exercise the same queue, multipart capture, preview and binding endpoints as the phone."""
from io import BytesIO
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.shipping_inspection import router, waybill_mobile_router, waybill_photo_router, waybill_photo_service
from app.tracking import upload_service
from tests.test_mobile_waybill_binding import PERMS, setup, tracking, outbound_scope_seed


def test_phone_capture_associates_private_photo_and_retries(db, setup, tmp_path, monkeypatch):
    user, inspection, _, _ = setup
    tracking(db)
    db.commit()
    app = FastAPI()
    app.include_router(router.router, prefix='/api/shipping-inspection')
    app.include_router(waybill_photo_router.router, prefix='/api')
    app.dependency_overrides[get_current_user] = lambda: {'sub': str(user.id), 'username': user.username,
                                                         'roles': [], 'permissions': PERMS}
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(waybill_mobile_router, 'get_live_user_authorization', lambda *_: ([], PERMS))
    monkeypatch.setattr(waybill_photo_service.file_service, 'storage_root', lambda: tmp_path)
    monkeypatch.setattr(upload_service, 'run_ocr', AsyncMock(return_value={'waybill_no': '9876543210',
                        'recipient_name': 'Jane', 'recipient_country': '美国', 'carrier': 'DHL'}))
    image = BytesIO()
    Image.new('RGB', (12, 8)).save(image, format='PNG')
    part = ('waybill.png', image.getvalue(), 'image/png')
    path = f'/api/shipping-inspection/records/{inspection.id}'
    queue = '/api/shipping-inspection/mobile/waybill-queue'
    with TestClient(app) as client:
        response = client.get(queue, params={'tab': 'pending'})
        assert response.status_code == 200, response.text
        assert inspection.id in {r['id'] for r in response.json()['data']['items']}
        captured = client.post(path + '/waybill-photo', files={'rectified': part, 'original': part},
                               data={'barcode': '1234567890'})
        assert captured.status_code == 200, captured.text
        saved = captured.json()['data']
        assert saved['number_source'] == 'barcode' and saved['barcode_conflict'] == '9876543210'
        form = dict(waybill_no=saved['waybill_no'], carrier='DHL', edit_version=0, shipment_version=0,
                    recipient_name='Jane', recipient_country='美国', photo_token=saved['photo_token'])
        preview = client.post(path + '/shipment-preview', json=form)
        assert preview.status_code == 200, preview.text
        result = preview.json()['data']
        assert result['can_submit'] and result['existing']['outside_tracking_scope']
        assert 'SECRET RECIPIENT' not in preview.text
        payload = dict(**form, source='mobile', number_source='barcode', preview_token=result['preview_token'],
                       confirmed_warnings=[w['code'] for w in result['warnings'] if w['requires_confirmation']])
        for _ in range(2):
            submitted = client.put(path + '/shipment', json=payload)
            assert submitted.status_code == 200, submitted.text
        photos = client.get(path + '/waybill-photos').json()['data']
        assert [p['id'] for p in photos] == [saved['photo_id']]
        assert 'token' not in photos[0] and photos[0]['inspection_id'] == inspection.id
        assert client.get(photos[0]['original_url']).content == image.getvalue()
        done = client.get(queue, params={'tab': 'done'}).json()['data']['items']
        assert len(done) == 1 and done[0]['photo']['id'] == saved['photo_id']
