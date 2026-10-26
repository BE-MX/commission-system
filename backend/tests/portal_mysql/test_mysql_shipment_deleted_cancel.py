"""Current JWT, InnoDB authorization and shared executor fence on owned MySQL."""
from sqlalchemy import Column, MetaData, Table, inspect, select, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
import pytest

from app.invoice import shipment_deleted_cancellation as cancels
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication
from app.invoice.outbound_mode import executor_fence, LOCK_NAME
from test_mysql_shipment_failed_cancel import prepare
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import (shipment_app, snapshot, login, change_user, authorize,
    body_for, created, path)  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


@pytest.fixture(scope='session')
def service_schema(service_schema):
    # The shared historical fixture stops before the catalog-family addition.
    # Supply current upstream ORM columns on this owned database only, exactly
    # like its existing synthetic invoice/customer column adapters.
    from app.portal import models
    from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection
    with service_schema.engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        operations = Operations(MigrationContext.configure(connection))
        for model in vars(models).values():
            table = getattr(model, '__table__', None)
            if table is None or table.name not in tables:
                continue
            existing = {col['name'] for col in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    operations.add_column(table.name, Column(col.name, col.type, nullable=True))
        metadata = MetaData()
        for model in (ShippingOperationEvent, ShippingInspection):
            Table(model.__tablename__, metadata, *(Column(col.name, col.type,
                primary_key=col.primary_key, nullable=not col.primary_key) for col in model.__table__.columns))
        metadata.create_all(connection)
    return service_schema


def generated(c, client, monkeypatch):
    root, owner, body = prepare(c, client)
    with Session(c.ctx.engine) as db:
        row = db.get(ShipmentSettlement, c.settlement_id)
        target = db.get(ShipmentOutbound, c.target_id)
        row.state = 'outbound_uncertain'; target.status = 'uncertain'; target.remote_id = '401'
        body['version'] = row.version
        db.commit()
    monkeypatch.setattr(cancels, '_inspection', lambda *_args, **_kw: ('mirror-401', 'original-inspection'))
    c.io.clear()
    return root, owner, body


def address(c):
    return f'/api/shipments/{c.settlement_id}/cancel-deleted-outbound'


def proof():
    return {'remote_id': '401', 'serial_id': 'TEST-02', 'result': 'verified_deleted',
        'observed_at': '2026-10-26T11:00:00', 'goods': None, 'freight': None}


def test_real_authority_unlocked_get_and_fence_held_through_commit(state_app, monkeypatch):
    c = state_app
    with c.app.client() as client:
        _, owner, body = generated(c, client, monkeypatch)
        seen = []
        def observe(db, original):
            with Session(c.ctx.engine) as other:
                other.scalar(select(Invoice).where(Invoice.id == c.invoice_id).with_for_update(nowait=True))
            with Session(c.ctx.engine) as other:
                with executor_fence(other) as acquired:
                    assert acquired is False
            seen.append(original.remote_id)
            return proof()
        monkeypatch.setattr(cancels, '_observe', observe)
        response = client.post(address(c), headers=owner, json=body)
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.json()['data']['state'] == 'cancelled'
        with Session(c.ctx.engine) as db:
            assert db.get(ShipmentOutbound, c.target_id).status == 'cancelled'
            assert {app.status for app in db.query(SettlementApplication).filter_by(
                settlement_id=c.settlement_id)} == {'released'}
            assert db.scalar(text('SELECT IS_USED_LOCK(:name)'), {'name': LOCK_NAME}) is None
        assert seen == ['401'] and c.calls == []
        assert client.post(address(c), headers=owner, json=body).status_code == 409


@pytest.mark.parametrize('change', ['before_disabled', 'during_disabled', 'during_receipt', 'during_task'])
def test_real_current_revocation_and_unlocked_graph_changes_preserve_batch(state_app, monkeypatch, change):
    c = state_app
    with c.app.client() as client:
        root, owner, body = generated(c, client, monkeypatch)
        if change == 'before_disabled':
            change_user(client, c, root, {'is_active': False})
            monkeypatch.setattr(cancels, '_observe', lambda *_: pytest.fail('Denied before GET'))
        else:
            def observe(db, original):
                if change == 'during_disabled':
                    change_user(client, c, root, {'is_active': False})
                else:
                    from app.receipt.models import Receipt
                    with Session(c.ctx.engine) as other:
                        if change == 'during_receipt':
                            other.get(Receipt, c.receipts['victim']).remark = 'Concurrent receipt change'
                        else:
                            other.get(ShipmentOutbound, c.target_id).version += 1
                        other.commit()
                return proof()
            monkeypatch.setattr(cancels, '_observe', observe)
        response = client.post(address(c), headers=owner, json=body)
        assert response.status_code == (403 if 'disabled' in change else 409), response.text
        with Session(c.ctx.engine) as db:
            assert db.get(ShipmentSettlement, c.settlement_id).state == 'outbound_uncertain'
            assert {app.status for app in db.query(SettlementApplication).filter_by(
                settlement_id=c.settlement_id)} == {'reserved'}
        assert c.calls == []
