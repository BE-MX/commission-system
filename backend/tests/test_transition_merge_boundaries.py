"""Main order grouping and legacy returns remain isolated across formal routes."""
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.commerce_transition import service as gates, transfer_service
from app.commerce_transition.models import InvoiceAuthority, PlatformPolicy
from app.invoice import service, item_group_service
from app.invoice.linked_sync_service import edit_version
from app.invoice.schemas import InvoiceCreate, InvoiceItemGroupsUpdate
from app.sales_return import guards as return_guards, service as returns
from app.sales_return.models import ReturnEffect, ReturnReceipt, SalesReturn
from app.shipping_inspection.print_customer_service import with_customer_order_info
from tests.test_commerce_transition_editor import editor
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock
from tests.test_finance_local import finance
from tests.test_commerce_transition_authority import install, invoice
from tests.test_sales_return_service import env, activate, draft, USER


def test_native_unified_editor_persists_groups_and_inspection_without_mirrors(db, editor):
    values, user = editor
    values = {**values, 'okki_new_deal': 1, 'inspection_requirement': 'detail',
        'item_groups': [{'key': 'first', 'name': 'First lot', 'sort_order': 1}],
        'items': [{**values['items'][0], 'group_key': 'first'}]}
    row = service.create_invoice(db, InvoiceCreate(**values), int(user['sub']))
    identity = row.id
    db.commit()
    row = service.get_invoice(db, identity)
    assert row.inspection_requirement == 'detail'
    assert row.items[0].group.key == 'first'
    printed = with_customer_order_info(db, {'transaction_mode': 'local', 'invoice_id': identity})
    assert printed['inspection_requirement'] == 'detail' and printed['is_new_deal']
    command = InvoiceItemGroupsUpdate(expected_version=edit_version(row),
        expected_groups_version=item_group_service.version(row), expected_authority_epoch=1,
        item_groups=[{'key':'second','name':'Second lot','sort_order':1}],
        items=[{'id':row.items[0].id,'group_key':'second'}])
    amount, version = row.total_amount, row.commerce_version
    db.commit()
    item_group_service.update_local(db, identity, command, user)
    db.commit()
    row = service.get_invoice(db, identity)
    assert row.total_amount == amount and row.commerce_version == version
    assert row.items[0].group.key == 'second'
    db.commit()
    with pytest.raises((ValueError, HTTPException), match='办理权'):
        item_group_service.update_local(db, identity, command.model_copy(update={'expected_authority_epoch': 9}), user)


@pytest.mark.parametrize('route,state', [('local','active'), ('legacy','frozen')])
def test_old_return_cannot_mutate_a_transferred_or_frozen_invoice(db, route, state):
    install(db)
    row = invoice(db, route=route)
    row.xiaoman_order_id = 'legacy-1'
    db.get(InvoiceAuthority, row.id).state = state
    db.flush()
    with pytest.raises(ValueError, match='办理权|冻结|路线'):
        return_guards.require_legacy_order(db, 'legacy-1', row.id)
    assert db.scalar(select(func.count()).select_from(ReturnEffect)) == 0
    assert db.scalar(select(func.count()).select_from(ReturnReceipt)) == 0


def test_legacy_return_refuses_local_only_even_without_invoice(db):
    install(db, 'local_only')
    with pytest.raises(ValueError, match='路线|阶段'):
        return_guards.require_legacy_order(db, 'unbound-old-order')


@pytest.mark.parametrize('status', ['draft','effective'])
def test_handover_refuses_unrepresented_old_return_before_freezing(env, status):
    db, snapshot, _ = env
    install(db)
    original = invoice(db)
    original.xiaoman_order_id = '101'
    snapshot['invoice_id'] = original.id
    row = returns.create(db, draft(), USER)
    row.status = status
    db.flush()
    assert transfer_service._pending_sales_returns(db, [original.id])
    with pytest.raises(ValueError, match='退货'):
        transfer_service.prepare_transfer(db, invoice_ids=[original.id], target_route='local',
            request_key='return-blocked-handover', checkpoint='verified-original', evidence={'review':'reviewed'})
    assert db.get(InvoiceAuthority, original.id).state == 'active'

def test_native_group_edit_rechecks_customer_scope_after_role_revocation(db, editor):
    from app.auth.models import ArkUser, ArkRole, ArkPermission
    values, user = editor
    row = service.create_invoice(db, InvoiceCreate(**values), int(user['sub']))
    identity = row.id
    group = row.item_groups[0]
    command = InvoiceItemGroupsUpdate(expected_version=edit_version(row),
        expected_groups_version=item_group_service.version(row), expected_authority_epoch=1,
        item_groups=[{'key':group.key,'name':'Unauthorized rename','sort_order':1}],
        items=[{'id':row.items[0].id,'group_key':group.key}])
    actor = db.get(ArkUser, int(user['sub']))
    role = ArkRole(name='group-writer',label='Group writer',permissions=[
        ArkPermission(code='invoice:write',module='invoice',action='write',label='Invoice writer')])
    actor.roles = [role]
    db.commit()
    with pytest.raises((ValueError, HTTPException)):
        item_group_service.update_local(db, identity, command, user)
    db.rollback()
    assert service.get_invoice(db, identity).item_groups[0].name != 'Unauthorized rename'


def test_native_and_legacy_refund_commissions_share_batch_without_double_consumption(db, finance, stock, buyer):
    from tests.test_commission_local import snapshot, allocate, batch
    from tests.test_sales_return_commission import original, refund
    from app.models.commission import CommissionDetail, PaymentCommissionStatus
    from app.services.commission_calculator import calculate_commission
    customer, user, _ = finance
    snapshot(db, customer, user)
    allocate(db, finance, stock, buyer, '100')
    original(db)
    refund(db, '200')
    current = batch(db, 'Mixed formal sources')
    result = calculate_commission(db, current.id)
    assert result.total_payments == 2 and result.total_salesperson_commission == Decimal('-2')
    rows = db.scalars(select(CommissionDetail).where(CommissionDetail.batch_id == current.id)).all()
    assert {row.salesperson_id for row in rows} == {f"ark:{user['sub']}", 'old-A'}
    assert {row.payment_id.split(':')[0] for row in rows} == {'ark-finance','ark_return'}
    assert calculate_commission(db, batch(db, 'Mixed retry').id).total_payments == 0
    assert db.scalar(select(func.count()).select_from(PaymentCommissionStatus)) == 3
