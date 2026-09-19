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
