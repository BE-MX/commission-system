"""The established invoice editor must dispatch local writes without a mirror."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

from app.auth.models import ArkRole, ArkUser
from app.commerce_transition.models import InvoiceAuthority
from app.invoice import service
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceUpdate
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


@pytest.fixture
def editor(db, buyer, stock):
    customer, user = buyer
    role = ArkRole(name='super_admin', label='Isolated editor administrator', is_system=True)
    db.add(role)
    actor = db.get(ArkUser, int(user['sub']))
    actor.roles.append(role)
    db.flush()
    sku, _ = stock
    values = dict(transaction_route='local', request_key='editor:create',
        local_customer_id=customer.id, customer_id=f'ark:{customer.id}', customer_name='caller label',
        sales_user_id=int(user['sub']), invoice_date=date(2026, 10, 3), currency='USD',
        items=[dict(local_sku_id=sku.id, product_display='caller display', color='Black', quantity=3, price_per_piece=10)])
    def no_mirror(conn, cursor, statement, parameters, context, executemany):
        assert 'lsordertest.' not in statement and '`lsordertest`.' not in statement, 'local editor queried the transaction mirror'
    event.listen(db.get_bind(), 'before_cursor_execute', no_mirror)
    yield values, user
    event.remove(db.get_bind(), 'before_cursor_execute', no_mirror)


def test_unified_create_uses_local_customer_sku_and_single_idempotent_invoice(db, editor):
    values, user = editor
    body = InvoiceCreate(**values)
    first = service.create_invoice(db, body, int(user['sub']))
    second = service.create_invoice(db, body, int(user['sub']))
    assert first.id == second.id
    assert first.transaction_mode == 'local' and first.commerce_status == 'draft'
    assert first.total_amount == Decimal('30') and first.customer_name != 'caller label'
    assert first.items[0].local_sku_id == values['items'][0]['local_sku_id']
    assert db.scalar(select(func.count()).select_from(Invoice)) == 1
    assert db.get(InvoiceAuthority, first.id).route == 'local'


def test_unified_local_update_keeps_line_identity_and_rejects_old_version(db, editor):
    values, user = editor
    first = service.create_invoice(db, InvoiceCreate(**values), int(user['sub']))
    line_id = first.items[0].id
    update = {**values, 'request_key': 'editor:update', 'expected_commerce_version': 1,
        'expected_authority_epoch': 1, 'items': [{**values['items'][0], 'id': line_id, 'quantity': 2}]}
    service.update_invoice(db, first, InvoiceUpdate(**update), int(user['sub']))
    assert first.items[0].id == line_id and first.total_amount == Decimal('20')
    with pytest.raises(ValueError, match='版本|刷新|变化'):
        service.update_invoice(db, first, InvoiceUpdate(**{**update, 'request_key': 'editor:stale'}), int(user['sub']))
    assert first.items[0].quantity == 2


def test_local_editor_cannot_save_remote_receipt_draft_or_unmapped_sku(db, editor):
    values, user = editor
    with pytest.raises(ValueError, match='SKU|本地'):
        service.create_invoice(db, InvoiceCreate(**{**values, 'items': [dict(product_display='Hair', color='Black', quantity=1, price_per_piece=10)]}), int(user['sub']))
    assert db.scalar(select(func.count()).select_from(Invoice)) == 0
