import json

import pytest

from app.core.storage.cutover import verified_rows, register_ready
from app.core.storage.cos import StorageError
from app.core.storage.models import StorageTransfer


def test_staged_or_incomplete_or_wrong_bucket_receipts_cannot_cut_over():
    row = {'relative_path':'a.jpg','size':3,'sha256':'a'*64}
    manifest = {'version':1,'domain':'asset','source_instance':'office','files':[row]}
    receipt = {**row,'domain':'asset','source_instance':'office','target_bucket':'bucket-123',
               'target_key':'ark/production/asset/a.jpg','verified_at':'2026-09-19T08:00:00'}
    kwargs = {'bucket':'bucket-123','prefix':'ark/production'}
    assert verified_rows(manifest,json.dumps(receipt),**kwargs) == [row]
    staged = {k:v for k,v in receipt.items() if k!='verified_at'}
    staged['staged_at']='2026-09-19T08:00:00'
    for invalid in ['', json.dumps(staged), json.dumps({**receipt,'target_bucket':'wrong-123'})]:
        with pytest.raises(StorageError):
            verified_rows(manifest,invalid,**kwargs)


def test_backfill_is_transactional_idempotent_and_cannot_resurrect_tombstone(db):
    rows=[{'relative_path':'a.jpg','size':3,'sha256':'a'*64}]
    register_ready(db,'asset',rows,'office')
    db.rollback()
    assert db.query(StorageTransfer).count()==0
    register_ready(db,'asset',rows,'office')
    db.commit()
    register_ready(db,'asset',rows,'office')
    db.commit()
    assert db.query(StorageTransfer).count()==1
    record=db.query(StorageTransfer).one()
    record.status='deleted'
    db.commit()
    with pytest.raises(StorageError):
        register_ready(db,'asset',rows,'office')
    db.rollback()
    assert db.query(StorageTransfer).one().status=='deleted'


def test_multi_instance_union_deduplicates_and_rejects_conflicting_bytes():
    from app.core.storage.cutover import verified_union
    def entry(source, sha):
        row = {'relative_path':'shared.jpg','size':3,'sha256':sha}
        manifest = {'version':1,'domain':'asset','source_instance':source,'files':[row]}
        receipt = {**row,'domain':'asset','source_instance':source,'target_bucket':'bucket-123',
                   'target_key':'ark/production/asset/shared.jpg','verified_at':'2026-09-19T08:00:00'}
        return manifest, json.dumps(receipt)
    kwargs = {'bucket':'bucket-123','prefix':'ark/production'}
    result = verified_union([entry('office','a'*64),entry('beijing','a'*64)], **kwargs)
    assert len(result['asset']) == 1
    with pytest.raises(StorageError, match='Instances disagree'):
        verified_union([entry('office','a'*64),entry('beijing','b'*64)], **kwargs)


def test_complete_file_copy_cannot_hide_missing_database_originals(db):
    from app.asset.models import Asset, AssetVersion
    from app.core.storage.cutover import check_reference_coverage
    asset = Asset(file_name='current.jpg',file_type='image',file_format='jpg',uploader_id=1,
                  storage_path='current.jpg',thumbnail_path='thumb.jpg',file_size=3)
    db.add(asset)
    db.flush()
    db.add(AssetVersion(asset_id=asset.id,uploader_id=1,storage_path='history.jpg',file_size=4))
    db.commit()
    rows = [{'relative_path':key,'size':size,'sha256':'a'*64} for key,size in [('current.jpg',3),('thumb.jpg',2)]]
    with pytest.raises(StorageError, match='missing=1'):
        register_ready(db,'asset',rows,'office')
    assert db.query(StorageTransfer).count() == 0
    rows.append({'relative_path':'history.jpg','size':4,'sha256':'b'*64})
    assert check_reference_coverage(db,'asset',rows) == 3
    rows[-1]['size'] = 1
    with pytest.raises(StorageError, match='size_mismatch=1'):
        check_reference_coverage(db,'asset',rows)


@pytest.fixture
def asset_reference_rows(db):
    from app.asset.models import Asset, AssetVersion
    asset = Asset(file_name='missing.jpg', file_type='image', file_format='jpg', uploader_id=1,
                  storage_path='missing.jpg', thumbnail_path='thumb.jpg', file_size=3)
    db.add(asset)
    db.flush()
    # One exception covers the exact object even if multiple records reference it.
    db.add(AssetVersion(asset_id=asset.id, uploader_id=1, storage_path='missing.jpg', file_size=3))
    db.commit()
    return [{'relative_path': 'thumb.jpg', 'size': 2, 'sha256': 'a' * 64}]


def test_exact_missing_exception_is_transactional_and_does_not_invent_transfer(db, asset_reference_rows):
    from app.core.storage.cutover import check_reference_coverage
    rows = asset_reference_rows
    with pytest.raises(StorageError, match='missing=2'):
        register_ready(db, 'asset', rows, 'office')
    assert db.query(StorageTransfer).count() == 0
    assert check_reference_coverage(db, 'asset', rows,
                                    missing_reference_exceptions=['missing.jpg']) == 3
    register_ready(db, 'asset', rows, 'office', missing_reference_exceptions=['missing.jpg'])
    assert [row.object_key for row in db.query(StorageTransfer)] == ['thumb.jpg']
    db.rollback()
    assert db.query(StorageTransfer).count() == 0


@pytest.mark.parametrize('exceptions,error', [
    (['missing.jpg', 'missing.jpg'], ValueError),
    (['thumb.jpg'], StorageError),
    (['unreferenced.jpg'], StorageError),
    (['missing.jpg', 'unreferenced.jpg'], StorageError),
    (['*.jpg'], StorageError),
    (['../missing.jpg'], ValueError),
    ('missing.jpg', ValueError),
])
def test_missing_exceptions_cannot_be_stale_broad_or_duplicated(db, asset_reference_rows, exceptions, error):
    with pytest.raises(error):
        register_ready(db, 'asset', asset_reference_rows, 'office', missing_reference_exceptions=exceptions)
    assert db.query(StorageTransfer).count() == 0


def test_missing_exception_cannot_silence_another_missing_reference(db, asset_reference_rows):
    with pytest.raises(StorageError, match='missing=1'):
        register_ready(db, 'asset', [], 'office', missing_reference_exceptions=['missing.jpg'])
    assert db.query(StorageTransfer).count() == 0


def test_exceptions_are_rejected_outside_asset(db):
    from app.core.storage.cutover import check_reference_coverage
    for function in (
        lambda: check_reference_coverage(db, 'shipping-inspection', [], missing_reference_exceptions=['missing.jpg']),
        lambda: register_ready(db, 'shipping-inspection', [], 'office', missing_reference_exceptions=['missing.jpg']),
    ):
        with pytest.raises(ValueError, match='only supported for asset'):
            function()


def test_exception_never_bypasses_size_or_registered_hash_checks(db, asset_reference_rows):
    from app.asset.models import Asset
    asset = db.query(Asset).one()
    asset.storage_path = 'present.jpg'
    db.commit()
    rows = asset_reference_rows + [{'relative_path': 'present.jpg', 'size': 1, 'sha256': 'b' * 64}]
    with pytest.raises(StorageError, match='size_mismatch=1'):
        register_ready(db, 'asset', rows, 'office', missing_reference_exceptions=['missing.jpg'])
    rows[-1]['size'] = 3
    register_ready(db, 'asset', rows, 'office', missing_reference_exceptions=['missing.jpg'])
    db.commit()
    rows[-1]['sha256'] = 'c' * 64
    with pytest.raises(StorageError, match='conflicts'):
        register_ready(db, 'asset', rows, 'office', missing_reference_exceptions=['missing.jpg'])
    db.rollback()
    assert db.query(StorageTransfer).filter_by(object_key='present.jpg').one().sha256 == 'b' * 64
