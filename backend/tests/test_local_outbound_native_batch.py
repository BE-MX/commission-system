"""Batch native-outbound detection must agree with the per-identity is_native rule."""
from datetime import date

import pytest

from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement
from app.shipping_inspection import local_outbound_service as local
from tests.test_finance_local import finance  # noqa: F401 - fixture
from tests.test_invoice_commerce import buyer  # noqa: F401 - fixture used by finance
from tests.test_inventory_local import stock  # noqa: F401 - fixture used by buyer


def _outbound(db, user_id, key, payload):
    invoice = Invoice(invoice_no=f'INV-{key}', customer_id='C1', customer_name='C', invoice_date=date(2026, 11, 1),
                      currency='USD', created_by=user_id)
    db.add(invoice); db.flush()
    settlement = ShipmentSettlement(invoice_id=invoice.id, settlement_no=f'S-{key}', sequence=1, state='shipped',
        is_final=0, quote={}, quote_hash='a' * 64, request_key=f'req-{key}', request_hash='a' * 64, created_by=user_id)
    db.add(settlement); db.flush()
    row = ShipmentOutbound(settlement_id=settlement.id, invoice_id=invoice.id, outbound_no=f'O-{key}',
        remote_id=f'remote-{key}', status='local_shipped', payload_hash='a' * 64, payload=payload)
    db.add(row); db.flush()
    return row


def test_native_identities_matches_is_native(db, finance):  # noqa: F811
    user_id = int(finance[1]['sub'])
    adopted = _outbound(db, user_id, 'a', {'transaction_mode': 'local', 'original_outbound_record_id': 'rec-1'})
    _outbound(db, user_id, 'b', {'transaction_mode': 'local', 'original_outbound_invoice_id': 'inv-2'})
    _outbound(db, user_id, 'c', {'transaction_mode': 'legacy', 'original_outbound_record_id': 'rec-3'})
    ids = ['rec-1', 'inv-2', 'rec-3', 'mirror-only', f'local-{adopted.id}']
    batch = local.native_identities(db, ids)
    assert batch == {i for i in ids if local.is_native(db, i)} == {'rec-1', 'inv-2', f'local-{adopted.id}'}
    assert local.native_identities(db, []) == set()


def test_native_identities_rejects_ambiguous_alias_like_get(db, finance):  # noqa: F811
    user_id = int(finance[1]['sub'])
    _outbound(db, user_id, 'x', {'transaction_mode': 'local', 'original_outbound_record_id': 'dup'})
    _outbound(db, user_id, 'y', {'transaction_mode': 'local', 'original_outbound_invoice_id': 'dup'})
    with pytest.raises(ValueError, match='不唯一'):
        local.get(db, 'dup')
    with pytest.raises(ValueError, match='不唯一'):
        local.native_identities(db, ['dup'])
