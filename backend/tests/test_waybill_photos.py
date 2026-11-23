from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.shipping_inspection import waybill_photo_service as service
from app.shipping_inspection.waybill_photo_models import ShippingWaybillPhoto


def photo(db, **changes):
    values = dict(id=1, inspection_id=10, token='secret', created_by=7, updated_by=7,
                  rectified_path='aa/a.jpg', original_path='bb/b.jpg', created_at=datetime(2026, 11, 23, 0, 0))
    values.update(changes)
    row = ShippingWaybillPhoto(**values)
    db.add(row)
    db.commit()
    return row


def test_token_owner_inspection_expiry_and_atomic_binding(db, monkeypatch):
    monkeypatch.setattr(service, 'beijing_now', lambda: datetime(2026, 11, 23, 12))
    row = photo(db)
    for inspection_id, user_id in ((11, 7), (10, 8)):
        with pytest.raises(HTTPException):
            service.validate_photo(db, inspection_id, user_id, 'secret')
    service.consume_photo(db, SimpleNamespace(id=10), 55, 7, 'secret', 'barcode', 'not_found')
    db.rollback()
    assert db.get(ShippingWaybillPhoto, row.id).shipment_tracking_id is None
    service.consume_photo(db, SimpleNamespace(id=10), 55, 7, 'secret', 'barcode', 'not_found')
    db.commit()
    assert service.consume_photo(db, SimpleNamespace(id=10), 55, 7, 'secret', 'barcode', 'not_found').id == row.id
    with pytest.raises(HTTPException):
        service.consume_photo(db, SimpleNamespace(id=10), 56, 7, 'secret', 'barcode', 'found')


def test_expiry_exact_beijing_midnight_and_replaced_history(db, monkeypatch):
    monkeypatch.setattr(service, 'beijing_now', lambda: datetime(2026, 11, 24))
    row = photo(db)
    with pytest.raises(HTTPException, match='已过期'):
        service.validate_photo(db, 10, 7, row.token)
    row.created_at += timedelta(seconds=1)
    assert service.validate_photo(db, 10, 7, row.token) is row
    row.shipment_tracking_id = 55
    service.mark_replaced(db, 10, 9)
    assert row.replaced_at == datetime(2026, 11, 24)
    assert row.replaced_by == 9
    with pytest.raises(HTTPException):
        service.consume_photo(db, SimpleNamespace(id=10), 55, 7, row.token, 'manual', 'skipped')


def test_cleanup_only_expired_unbound_with_both_tombstones(db, monkeypatch):
    monkeypatch.setattr(service, 'beijing_now', lambda: datetime(2026, 11, 24))
    photo(db)
    photo(db, id=2, token='bound', shipment_tracking_id=55)
    photo(db, id=3, token='fresh', created_at=datetime(2026, 11, 23, 1))
    tombstone, remove = Mock(), Mock()
    monkeypatch.setattr(service.transfers, 'tombstone', tombstone)
    monkeypatch.setattr(service.file_service, 'remove_file', remove)
    assert service.cleanup_expired(db) == 1
    assert tombstone.call_count == remove.call_count == 2
    assert db.query(ShippingWaybillPhoto).count() == 2


def upload():
    output = BytesIO()
    Image.new('RGB', (4, 4)).save(output, format='PNG')
    return UploadFile(BytesIO(output.getvalue()), filename='test.png', headers=Headers({'content-type': 'image/png'}))


@pytest.mark.asyncio
async def test_capture_ocr_failure_keeps_saved_token_and_barcode(db, monkeypatch, tmp_path):
    from app.tracking import upload_service
    monkeypatch.setattr(service.file_service, 'storage_root', lambda: tmp_path)
    monkeypatch.setattr(service.transfers, 'register', lambda *args: None)
    async def failed(*args):
        raise TimeoutError()
    monkeypatch.setattr(upload_service, 'run_ocr', failed)
    result = await service.capture(db, 10, 7, upload(), upload(), '1234567890')
    assert result['photo_token'] and result['recognition_error']
    assert result['number_source'] == 'barcode' and result['waybill_no'] == '1234567890'
    row = db.query(ShippingWaybillPhoto).one()
    assert service.file_service.resolve_path(row.rectified_path).is_file()
    assert service.file_service.resolve_path(row.original_path).is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize('barcode,expected', [
    ('001234567890', '001234567890'), ('SF1234567890123', 'SF1234567890123'),
    ('1z1234567890123456', '1Z1234567890123456'),
    ('JD123456789012', '1234567890'), ('2L123456789012', '1234567890'),
])
async def test_barcode_precedes_disagreeing_ocr(db, monkeypatch, tmp_path, barcode, expected):
    from unittest.mock import AsyncMock
    from app.tracking import upload_service
    monkeypatch.setattr(service.file_service, 'storage_root', lambda: tmp_path)
    monkeypatch.setattr(service.transfers, 'register', lambda *args: None)
    monkeypatch.setattr(upload_service, 'run_ocr', AsyncMock(return_value={'waybill_no': '1234567890'}))
    result = await service.capture(db, 10, 7, upload(), upload(), barcode)
    assert result['waybill_no'] == expected
    assert result['number_source'] == ('ocr' if expected == '1234567890' else 'barcode')
    assert result['barcode_conflict'] == (None if expected == '1234567890' else '1234567890')


@pytest.mark.asyncio
async def test_invalid_original_does_not_store_rectified(db, monkeypatch):
    store = Mock()
    monkeypatch.setattr(service.file_service, 'store_bytes', store)
    bad = UploadFile(BytesIO(b'bad'), filename='test.png', headers=Headers({'content-type': 'image/png'}))
    with pytest.raises(service.file_service.FileValidationError):
        await service.capture(db, 10, 7, upload(), bad)
    store.assert_not_called()


@pytest.mark.asyncio
async def test_ocr_country_and_contact_are_durable_source_facts(db, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from app.tracking import upload_service
    monkeypatch.setattr(service.file_service, 'storage_root', lambda: tmp_path)
    monkeypatch.setattr(service.transfers, 'register', lambda *args: None)
    monkeypatch.setattr(upload_service, 'run_ocr', AsyncMock(return_value={
        'waybill_no': '1111111111', 'recipient_country': 'Germany', 'recipient_name': 'Source Recipient'}))
    result = await service.capture(db, 10, 7, upload(), upload(), '1234567890')
    row = db.query(ShippingWaybillPhoto).filter_by(token=result['photo_token']).one()
    assert row.ocr_recipient_country == 'Germany' and row.ocr_recipient_name == 'Source Recipient'
    assert 'ocr_recipient_country' not in service.photo_dict(db, row)


def test_reader_cannot_bypass_inspection_scope(db, monkeypatch):
    from app.shipping_inspection import router as existing
    from app.shipping_inspection.waybill_photo_router import read_photo
    def denied(*args):
        raise HTTPException(404, '验货单不存在')
    monkeypatch.setattr(existing, '_require_inspection_scope', denied)
    response = Mock()
    monkeypatch.setattr(service.transfers, 'response', response)
    with pytest.raises(HTTPException) as exc:
        read_photo(10, 1, 'original', db, {'sub': '8'})
    assert exc.value.status_code == 404
    response.assert_not_called()


def test_two_variants_use_private_transfer_read_and_no_path_exposure(db, monkeypatch):
    from app.shipping_inspection import router as existing
    from app.shipping_inspection.waybill_photo_router import read_photo
    row = photo(db, shipment_tracking_id=55)
    monkeypatch.setattr(existing, '_require_inspection_scope', lambda *args: SimpleNamespace(id=10))
    snapshot, response = Mock(return_value={'status': 'ready'}), Mock(return_value='bytes')
    monkeypatch.setattr(service.transfers, 'snapshot', snapshot)
    monkeypatch.setattr(service.transfers, 'response', response)
    for variant, key in [('rectified', row.rectified_path), ('original', row.original_path)]:
        assert read_photo(10, 1, variant, db, {'sub': '7'}) == 'bytes'
        response.assert_called_with('shipping-inspection', key, {'status': 'ready'})
    result = service.photo_dict(db, row)
    assert 'token' not in result and 'rectified_path' not in result
    assert result['original_url'].endswith('?variant=original')


def test_cos_cutover_requires_both_photo_references(db):
    from app.core.storage.cutover import check_reference_coverage
    from app.core.storage.cos import StorageError
    row = photo(db)
    with pytest.raises(StorageError):
        check_reference_coverage(db, 'shipping-inspection', [{'relative_path': row.rectified_path}])
    assert check_reference_coverage(db, 'shipping-inspection', [
        {'relative_path': row.rectified_path}, {'relative_path': row.original_path}]) == 2


def test_beijing_time_independent_of_server_timezone(db, monkeypatch):
    from datetime import timezone
    import app.core.time as clock
    class ForeignServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 11, 23, 16, 0, tzinfo=timezone.utc)
            return instant.astimezone(tz or timezone(timedelta(hours=-5)))
    monkeypatch.setattr(clock, 'datetime', ForeignServerClock)
    assert service.beijing_now() == datetime(2026, 11, 24)
    row = photo(db)
    with pytest.raises(HTTPException):
        service.validate_photo(db, 10, 7, row.token)


@pytest.mark.asyncio
async def test_total_upload_limit_before_writing_files(db, monkeypatch):
    async def large(upload):
        return b'x' * (11 * 1024 * 1024)
    monkeypatch.setattr(service, '_image', large)
    store = Mock()
    monkeypatch.setattr(service.file_service, 'store_bytes', store)
    with pytest.raises(service.file_service.FileValidationError, match='20MB'):
        await service.capture(db, 10, 7, upload(), upload())
    store.assert_not_called()


def test_migration_sqlite_upgrade_and_mysql_ddl(monkeypatch):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from io import StringIO
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    spec = spec_from_file_location('waybill_migration', Path(__file__).parents[1] / 'alembic/versions/279_shipping_waybill_photos.py')
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ark_shipping_inspections (id BIGINT PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE shipment_tracking (id BIGINT PRIMARY KEY)')
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        inspector = inspect(connection)
        columns = {c['name']: c for c in inspector.get_columns('ark_shipping_waybill_photos')}
        assert str(columns['inspection_id']['type']) == str(columns['shipment_tracking_id']['type']) == 'INTEGER'  # suite SQLite BigInteger compiler
        assert len(inspector.get_foreign_keys('ark_shipping_waybill_photos')) == 2
        assert {i['name'] for i in inspector.get_indexes('ark_shipping_waybill_photos')} == {'idx_waybill_photo_inspection', 'idx_waybill_photo_shipment'}
        assert inspector.get_unique_constraints('ark_shipping_waybill_photos')[0]['column_names'] == ['token']
        migration.downgrade()
        assert not inspect(connection).has_table('ark_shipping_waybill_photos')
    output = StringIO()
    context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql': True, 'output_buffer': output})
    monkeypatch.setattr(migration, 'op', Operations(context))
    migration.upgrade()
    sql = output.getvalue()
    assert 'inspection_id BIGINT NOT NULL' in sql
    assert 'shipment_tracking_id BIGINT' in sql
    assert 'UNSIGNED' not in sql
    assert sql.count('ON DELETE RESTRICT') == 2
    assert 'CREATE INDEX idx_waybill_photo_inspection' in sql
    assert 'CREATE INDEX idx_waybill_photo_shipment' in sql
