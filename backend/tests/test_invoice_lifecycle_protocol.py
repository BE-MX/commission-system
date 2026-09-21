"""Protocol rejection and isolated additive migration coverage."""
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.invoice import lifecycle_remote, okki_client

@pytest.mark.parametrize('http_status,body,missing', [
    (200, {'code':404,'message':'Not Found Resource'}, True),
    (200, {'code':404,'message':'Not Found Resource.'}, True),
    (404, {'code':404,'message':'Not Found Resource'}, False),
    (200, {'code':403,'message':'Forbidden'}, False),
    (200, {'code':404,'message':'Not Found Resource','data':{'order_id':'123'}}, False),
    (200, {'code':200,'data':{'order_id':'999'}}, False),
])
def test_only_exact_missing_proves_deletion(monkeypatch,http_status,body,missing):
    monkeypatch.setattr(lifecycle_remote.httpx,'request',lambda *a,**kw:SimpleNamespace(status_code=http_status,json=lambda:body))
    if missing:
        assert lifecycle_remote.request('test','order','123') is None
    else:
        with pytest.raises(okki_client.OkkiApiError):
            lifecycle_remote.request('test','order','123')


def test_additive_migration_repeat_preserves_existing_rows():
    spec=importlib.util.spec_from_file_location('lifecycle_migration',Path(__file__).parents[1]/'alembic/versions/161_invoice_lifecycle.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE ark_invoices (id INTEGER PRIMARY KEY, invoice_no TEXT)'))
        connection.execute(sa.text("INSERT INTO ark_invoices VALUES (1, 'existing')"))
        migration.op=Operations(MigrationContext.configure(connection))
        migration.upgrade();migration.upgrade()
        row=connection.execute(sa.text('SELECT invoice_no, sync_attempt, cancellation, outbound_auto_requested FROM ark_invoices')).one()
        assert tuple(row)==('existing',None,None,0)
