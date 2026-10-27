"""Private inspection previews stay small without changing original evidence."""
from contextlib import contextmanager
from io import BytesIO

import pytest
from PIL import Image

from app.shipping_inspection import file_service, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto
from tests.test_shipping_inspection import (
    _bind_okki, _pc_client, _user, outbound_scope_seed, product_display_source, storage,
)

READ = 'shipping_inspection:read'
ALL = 'shipping_inspection:inspection_read_all'


@pytest.fixture
def picture(db, storage, outbound_scope_seed):
    user = _user(db, 'preview-sales')
    _bind_okki(db, user)
    buffer = BytesIO()
    Image.effect_noise((2400, 1600), 90).convert('RGB').save(buffer, 'JPEG', quality=95)
    original = buffer.getvalue()
    key = file_service.store_bytes('evidence.jpg', original)
    inspection = ShippingInspection(outbound_record_id='OB001', status='submitted', created_by=user.id)
    db.add(inspection)
    db.flush()
    photo = ShippingInspectionPhoto(inspection_id=inspection.id, file_path=key, created_by=user.id)
    db.add(photo)
    db.commit()
    return user, photo, original


def test_preview_is_bounded_and_original_stays_byte_identical(db, picture):
    user, photo, original = picture
    url = f'/api/shipping-inspection/images/{photo.file_path}'
    with _pc_client(db, user, [READ]) as client:
        preview = client.get(url, params={'preview': True})
        assert preview.status_code == 200
        assert preview.headers['content-type'] == 'image/jpeg'
        assert preview.headers['cache-control'] == 'private, no-store'
        with Image.open(BytesIO(preview.content)) as image:
            assert max(image.size) <= 640
            assert image.width > image.height
        assert len(preview.content) < 150_000
        assert client.get(url).content == original
    assert file_service.resolve_path(photo.file_path).read_bytes() == original


def test_oversized_png_fails_preview_without_changing_original_access(db, picture):
    user, photo, _ = picture
    buffer = BytesIO()
    Image.new('L', (6000, 5000)).save(buffer, 'PNG')
    original = buffer.getvalue()
    file_service.resolve_path(photo.file_path).write_bytes(original)
    url = f'/api/shipping-inspection/images/{photo.file_path}'
    with _pc_client(db, user, [READ]) as client:
        assert client.get(url, params={'preview': True}).status_code == 503
        assert client.get(url).content == original


def test_preview_checks_scope_and_permission_before_reading_bytes(db, picture, monkeypatch):
    user, photo, _ = picture
    stranger = _user(db, 'preview-stranger')
    _bind_okki(db, stranger, '9002')
    def unexpected(*args, **kwargs):
        pytest.fail('Unauthorized preview read original evidence')
    monkeypatch.setattr(service.transfers, 'materialize', unexpected)
    url = f'/api/shipping-inspection/images/{photo.file_path}?preview=true'
    with _pc_client(db, stranger, [READ]) as client:
        assert client.get(url).status_code == 404
    with _pc_client(db, user, []) as client:
        assert client.get(url).status_code == 403


def test_preview_rejects_video_and_corrupt_image_without_raw_fallback(db, picture):
    user, photo, _ = picture
    url = f'/api/shipping-inspection/images/{photo.file_path}?preview=true'
    with _pc_client(db, user, [READ]) as client:
        photo.media_type = 'video'
        db.commit()
        assert client.get(url).status_code == 400
        photo.media_type = 'image'
        db.commit()
        file_service.resolve_path(photo.file_path).write_bytes(b'corrupt')
        response = client.get(url)
        assert response.status_code == 503
        assert 'corrupt' not in response.text


def test_preview_uses_verified_materialization_after_releasing_db(db, picture, monkeypatch):
    user, photo, _ = picture
    calls = []
    @contextmanager
    def materialize(domain, key, record):
        assert not db.in_transaction()
        calls.append((domain, key))
        yield file_service.resolve_path(key)
    monkeypatch.setattr(service.transfers, 'materialize', materialize)
    with _pc_client(db, user, [READ, ALL]) as client:
        assert client.get(f'/api/shipping-inspection/images/{photo.file_path}?preview=true').status_code == 200
    assert calls == [('shipping-inspection', photo.file_path)]


@pytest.mark.parametrize('mode', ['RGBA', 'CMYK'])
def test_preview_converts_other_image_modes_and_phone_orientation(db, picture, mode):
    user, photo, _ = picture
    buffer = BytesIO()
    image = Image.new(mode, (1200, 800))
    if mode == 'RGBA':
        image.save(buffer, 'PNG')
    else:
        exif = Image.Exif()
        exif[274] = 6  # Phone portrait orientation: rotate pixels before stripping EXIF.
        image.save(buffer, 'JPEG', exif=exif)
    original = buffer.getvalue()
    file_service.resolve_path(photo.file_path).write_bytes(original)
    with _pc_client(db, user, [READ]) as client:
        response = client.get(f'/api/shipping-inspection/images/{photo.file_path}?preview=true')
        assert response.status_code == 200
        with Image.open(BytesIO(response.content)) as preview:
            assert preview.mode == 'RGB'
            assert max(preview.size) == 640
            if mode == 'CMYK':
                assert preview.height > preview.width
            assert not preview.getexif()
    assert file_service.resolve_path(photo.file_path).read_bytes() == original
