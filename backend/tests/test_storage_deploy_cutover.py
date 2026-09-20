import importlib.util
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy'))
from storage_cutover_host import FrozenTransferSession, DOMAINS, validate_coverage, update_env
from app.core.storage.cutover import register_ready
from app.core.storage.models import StorageTransfer
from app.core.storage.cos import StorageError
from sqlalchemy import event


def test_frozen_backfill_uses_one_lookup_and_preserves_transaction_and_tombstones(db):
    selects = []
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'storage_transfers' in statement:
            selects.append(statement)
    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', count)
    try:
        rows = [dict(relative_path=f'{n}.jpg', size=3, sha256='a'*64) for n in range(100)]
        frozen = FrozenTransferSession(db)
        register_ready(frozen, 'asset', rows, 'office')
        register_ready(frozen, 'asset', rows, 'office')
        assert len(selects) == 1
        db.rollback()
        assert db.query(StorageTransfer).count() == 0
        register_ready(FrozenTransferSession(db), 'asset', rows, 'office')
        db.commit()
        record = db.query(StorageTransfer).first()
        record.status = 'deleted'
        db.commit()
        with pytest.raises(StorageError, match='conflicts'):
            register_ready(FrozenTransferSession(db), 'asset', rows, 'office')
        db.rollback()
        assert db.get(StorageTransfer, record.id).status == 'deleted'
    finally:
        event.remove(engine, 'before_cursor_execute', count)


def test_matrix_rejects_missing_source_even_when_all_domains_present():
    required = {domain: ['office','beijing'] for domain in DOMAINS}
    data = [{'manifest':dict(domain=d,source_instance=s)} for d,ss in required.items() for s in ss]
    validate_coverage(data, required)
    with pytest.raises(RuntimeError): validate_coverage(data[:-1], required)
    with pytest.raises(RuntimeError): validate_coverage(data, {d:['office'] for d in DOMAINS})
    with pytest.raises(ValueError): validate_coverage(data, {**required,'asset':[]})


def test_env_update_preserves_hardlink_and_removes_duplicate_settings(tmp_path):
    import os
    original = tmp_path/'env';linked = tmp_path/'linked'
    original.write_text('KEEP=original\nexport COS_WORKER_ENABLED=false\nCOS_WORKER_ENABLED=false\n')
    os.link(original, linked)
    update_env(original, {'COS_WORKER_ENABLED':True, 'COS_ENABLED_DOMAINS':['asset','pm']})
    assert linked.read_text() == original.read_text()
    assert original.read_text().count('COS_WORKER_ENABLED=') == 1
    from dotenv import dotenv_values
    values = dotenv_values(original)
    assert values['KEEP'] == 'original'
    assert values['COS_WORKER_ENABLED'] == 'true'
    assert values['COS_ENABLED_DOMAINS'] == '["asset","pm"]'

@pytest.mark.parametrize('field,value', [('COS_BUCKET','wrong'),('COS_REGION','wrong'),('COS_WORKER_ENABLED',False),('COS_INSTANCE_ID','other'),('COS_SECRET_KEY','wrong')])
def test_start_validation_rejects_runtime_drift(field,value):
    from types import SimpleNamespace
    from storage_cutover_host import expected_config, validate_runtime
    secrets=SimpleNamespace(COS_BUCKET='bucket',COS_REGION='region',COS_KEY_PREFIX='prefix',COS_SECRET_ID='id',COS_SECRET_KEY='secret',COS_SECURITY_TOKEN='')
    expected=expected_config(Path('/live'),True,secrets)
    runtime=SimpleNamespace(**expected)
    validate_runtime(runtime,expected)
    setattr(runtime,field,value)
    with pytest.raises(RuntimeError): validate_runtime(runtime,expected)
