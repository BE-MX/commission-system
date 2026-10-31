"""Independent adversarial checks for original cash and report boundaries."""
from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select

from app.commerce_transition import service as gates
from app.commerce_transition.models import BankAccountDomain, TransferPreparation, ResourceScope, SendingClaim
from app.commerce_migration import settlement_service
from app.commerce_migration.settlement_schemas import SettlementManifest
from app.core.time import beijing_today
from app.finance.transition_identity import reconcile_legacy_identity
from app.invoice.models import Invoice
from app.receipt.models import Receipt
from app.trade.refresh_service import projection_status
from tests.test_commerce_transition_consumers import mixed, cursor
from tests.test_finance_local import finance
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def test_reversed_standalone_original_cash_without_refund_evidence_cannot_retire(db, stock, finance):
    customer, user, account = finance
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    invoice = Invoice(invoice_no='REVIEW-REVERSED-LEGACY', customer_id='old', customer_name='Original',
        invoice_date=date(2026, 10, 3), transaction_mode='legacy', commerce_status='cancelled',
        status='cancelled', internal_balance=0, created_by=int(user['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'original_invoice': invoice.id})
    receipt = Receipt(receipt_no='review-standalone-cash', invoice_id=invoice.id, customer_id='old', source='manual',
        purpose='ordinary', amount=100, reversed_amount=40, bank_charge=0, currency='USD', collection_date=date(2026, 10, 3),
        payment_type='bank_transfer', collect_status=1, sync_status='synced', status='active',
        xiaoman_receipt_id='review-original-receipt', request_key='review-old-cash', request_hash='a'*64,
        created_by=int(user['sub']))
    db.add(receipt); db.flush()
    domain = db.scalar(select(BankAccountDomain)); domain.exclusive_route = None; db.flush()
    identity = reconcile_legacy_identity(db, domain_id=domain.id, transaction_id='review-original-bank',
        receipt_id=receipt.id, statement_reference='Original bank principal is 100, allocation reversed 40', actor_id=int(user['sub']))
    body = SettlementManifest(request_key='review-cash-close', evidence_sha256='e'*64,
        review_reference='No actual refund evidence exists', invoices=[dict(invoice_id=invoice.id, expected_authority_epoch=1)],
        bank_identity_ids=[identity.id])
    assert not settlement_service.preview(db, body)['can_apply']
    with pytest.raises(ValueError):
        settlement_service.apply(db, body, user)
    assert identity.settled_evidence is None


def test_handover_invalidates_previous_customer_order_owner_and_account_date(db, mixed):
    user, _, create = mixed
    order = create('review-old-report-contribution', amount=100)
    old_day = beijing_today() - timedelta(days=10)
    order.account_date = old_day
    invoice = Invoice(invoice_no='REVIEW-FROZEN', customer_id='old', customer_name='Original', invoice_date=beijing_today(),
        transaction_mode='legacy', commerce_status='opening', sales_user_id=None, created_by=user.id)
    db.add(invoice); db.flush()
    order.local_invoice_id = invoice.id
    manifest = {'invoice_ids': [invoice.id], 'epochs': {str(invoice.id): 1}, 'group_ids': [],
                'checkpoint': 'review', 'evidence': {'review': True}}
    db.add(TransferPreparation(request_key='review-report-transfer', source_route='legacy', target_route='local', state='ready',
        manifest=manifest, manifest_hash=gates.digest(manifest)))
    cursor(db); db.flush()
    status = projection_status(db, owner_ids=[user.id], date_from=old_day, date_to=old_day)
    assert status['handover_pending_count'] == 1
    assert not status['data_complete']


@pytest.mark.parametrize('operation', ['outbound_create', 'outbound_update', 'shipment_outbound_create'])
def test_legacy_outbound_cannot_consume_mapped_native_exclusive_sku(db, stock, buyer, monkeypatch, operation):
    from app.catalog.models import CatalogExternalIdentity
    from app.invoice import legacy_sending
    monkeypatch.setattr('app.inventory.legacy_scope.get_settings',
        lambda: SimpleNamespace(PORTAL_OKKI_NAMESPACE='original-tenant'))
    sku, warehouses = stock
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    db.add(CatalogExternalIdentity(source='okki', tenant='original-tenant', external_product_id='22',
        external_sku_id='220', sku_id=sku.id))
    db.add(ResourceScope(resource_kind='sku', resource_key=str(sku.id), warehouse_key=str(warehouses[0].id),
        route='local', state='active', evidence={'physical_count': True, 'old_writers_excluded': True}))
    invoice = Invoice(invoice_no='REVIEW-LEGACY-STOCK', customer_id='old', customer_name='Original',
        invoice_date=date(2026, 10, 3), transaction_mode='legacy', status='synced', created_by=int(buyer[1]['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'source_invoice': invoice.id})
    payload = {'invoice_warehouse_id': '8193514242746', 'record_list': [
        {'product_id': 22, 'sku_id': 220, 'outbound_count': 1, 'order_id': 123, 'order_record_id': 100}]}
    with pytest.raises(ValueError, match='本地或冻结'):
        legacy_sending.start(db, invoice, 'review-old-exclusive-stock', operation, payload,
            {'actor_id': int(buyer[1]['sub']), 'original_stock': True}, 1)
    assert db.scalar(select(SendingClaim.id)) is None


@pytest.mark.parametrize('identity', ['missing', 'other-tenant', 'ambiguous'])
def test_unknown_legacy_physical_identity_cannot_skip_active_native_pilot(db, stock, buyer, monkeypatch, identity):
    from app.catalog.models import CatalogExternalIdentity, CatalogSku
    from app.inventory.legacy_scope import require_legacy_outbound_scope
    sku, warehouses = stock
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    monkeypatch.setattr('app.inventory.legacy_scope.get_settings',
        lambda: SimpleNamespace(PORTAL_OKKI_NAMESPACE='original-tenant'))
    db.add(ResourceScope(resource_kind='sku', resource_key=str(sku.id), warehouse_key=str(warehouses[0].id),
        route='local', state='active', evidence={'reviewed': True}))
    if identity == 'other-tenant':
        db.add(CatalogExternalIdentity(source='okki', tenant='unrelated', external_product_id='22', external_sku_id='220', sku_id=sku.id))
    elif identity == 'ambiguous':
        other = CatalogSku(product_id=sku.product_id, code='REVIEW-OTHER', color='brown', size='20', unit='piece')
        db.add(other); db.flush()
        db.add_all([CatalogExternalIdentity(source='okki', tenant='original-tenant', external_product_id='22', external_sku_id='220', sku_id=sku.id),
            CatalogExternalIdentity(source='okki', tenant='original-tenant', external_product_id='22', external_sku_id='', sku_id=other.id)])
    db.flush()
    with pytest.raises(ValueError, match='SKU' if identity == 'ambiguous' else '唯一实物映射'):
        require_legacy_outbound_scope(db,'outbound_create',{'record_list':[{'product_id':22,'sku_id':220,'outbound_count':1}]})


def test_known_legacy_sku_outside_native_pilot_remains_operable(db, stock, buyer, monkeypatch):
    from app.catalog.models import CatalogExternalIdentity, CatalogSku
    from app.inventory.legacy_scope import require_legacy_outbound_scope
    sku, warehouses = stock
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    monkeypatch.setattr('app.inventory.legacy_scope.get_settings',
        lambda: SimpleNamespace(PORTAL_OKKI_NAMESPACE='original-tenant'))
    other = CatalogSku(product_id=sku.product_id, code='REVIEW-LEGACY', color='brown', size='20', unit='piece')
    db.add(other); db.flush()
    db.add(CatalogExternalIdentity(source='okki', tenant='original-tenant', external_product_id='22', external_sku_id='220', sku_id=other.id))
    db.add(ResourceScope(resource_kind='sku', resource_key=str(sku.id), warehouse_key=str(warehouses[0].id),
        route='local', state='active', evidence={'reviewed': True}))
    db.flush()
    require_legacy_outbound_scope(db,'outbound_create',{'record_list':[{'product_id':22,'sku_id':220,'outbound_count':1}]})


def test_original_only_inventory_keeps_existing_unmapped_outbound_flow(db):
    from app.inventory.legacy_scope import require_legacy_outbound_scope
    require_legacy_outbound_scope(db,'outbound_create',{'record_list':[{'product_id':22,'sku_id':220,'outbound_count':1}]})


def test_product_only_alias_cannot_prove_an_unknown_sku_outside_native_pilot(db, stock, monkeypatch):
    from app.catalog.models import CatalogSku, CatalogExternalIdentity
    from app.inventory.legacy_scope import require_legacy_outbound_scope
    from app.core.config import get_settings
    sku, warehouses = stock
    monkeypatch.setattr(get_settings(), 'PORTAL_OKKI_NAMESPACE', 'original-tenant')
    other = CatalogSku(product_id=sku.product_id, code='PRODUCT-LEVEL-ONLY', size='20', color='Other', unit='piece')
    db.add(other); db.flush()
    db.add(CatalogExternalIdentity(source='okki', tenant='original-tenant', external_product_id='22', external_sku_id='', sku_id=other.id))
    db.add(ResourceScope(resource_kind='sku', resource_key=str(sku.id), warehouse_key=str(warehouses[0].id),
        route='local', state='active', evidence={'reviewed': True}))
    db.flush()
    with pytest.raises(ValueError, match='SKU'):
        require_legacy_outbound_scope(db, 'outbound_create',
            {'record_list': [{'product_id': 22, 'sku_id': 220, 'outbound_count': 1}]})


@pytest.mark.parametrize('state', ['sending', 'unknown'])
def test_original_outbound_inflight_cannot_be_overridden_by_new_pilot_attestation(db, stock, buyer, state):
    sku, warehouses = stock
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    invoice = Invoice(invoice_no='REVIEW-INFLIGHT', customer_id='old', customer_name='Original', invoice_date=date(2026, 10, 3),
        transaction_mode='legacy', status='synced', created_by=int(buyer[1]['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'source_invoice': invoice.id})
    db.add(SendingClaim(invoice_id=invoice.id, route='legacy', epoch=1, request_key='review-original-outbound',
        operation='outbound_create', state=state, active_invoice_key=invoice.id, payload_hash='a'*64,
        responsibilities={'original_payload': 'held before local physical pilot'}))
    db.flush()
    with pytest.raises(ValueError):
        gates.register_resource_scope(db, route='local', resource_kind='sku', resource_key=str(sku.id),
            warehouse_key=str(warehouses[0].id), evidence={'checkpoint':'reviewed-count',
                'old_responsibilities_cleared':{'review_reference':'Operator checkbox cannot close original unknown'},
                'writers_enforced':{'protocol':1}})
    assert db.scalar(select(ResourceScope.id)) is None


@pytest.mark.parametrize('pending_field', ['status', 'delta', 'operation', 'time'])
@pytest.mark.parametrize('key_kind', ['canonical', 'unmapped'])
def test_material_pending_source_cannot_be_reclassified_by_pilot_review(db, stock, buyer, pending_field, key_kind):
    from decimal import Decimal
    from app.core.time import beijing_now
    from app.semifinished.models import InvoiceAllocation, SemifinishedMaterial
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    invoice=Invoice(invoice_no='REVIEW-MATERIAL-PENDING', customer_id='old', customer_name='Original',
        invoice_date=date(2026,10,3),transaction_mode='legacy',status='synced',created_by=int(buyer[1]['sub']))
    material=SemifinishedMaterial(material_code='REVIEW-PENDING',size='18',color_code='Black',color_key='black')
    db.add_all([invoice,material]);db.flush()
    row=InvoiceAllocation(invoice_id=invoice.id,material_id=material.id,status='allocated',allocated_qty_grams=200,
        pending_delta_grams=0,operation_key=None,pending_at=None)
    if pending_field=='status':row.status='pending'
    if pending_field=='delta':row.pending_delta_grams=Decimal('100.125')
    if pending_field=='operation':row.operation_key='original-material-send'
    if pending_field=='time':row.pending_at=beijing_now()
    db.add(row);db.flush()
    with pytest.raises(ValueError,match='物料'):
        gates.register_resource_scope(db,route='local',resource_kind='material',
            resource_key=str(material.id) if key_kind=='canonical' else 'unknown-material',warehouse_key='*',
            evidence={'checkpoint':'review-count','old_responsibilities_cleared':{'manual_review':True},'writers_enforced':{'protocol':1}})
    assert db.scalar(select(ResourceScope.id)) is None
    assert row.status==('pending' if pending_field=='status' else 'allocated')


def test_resolved_original_material_can_enter_native_pilot_without_reapplying_its_movement(db, stock, buyer):
    from app.semifinished.models import InvoiceAllocation, SemifinishedMaterial
    gates.set_policy(db,phase='transition',expected_version=gates.policy(db).version)
    invoice=Invoice(invoice_no='REVIEW-RESOLVED-MATERIAL',customer_id='old',customer_name='Original',
        invoice_date=date(2026,10,3),transaction_mode='legacy',status='synced',created_by=int(buyer[1]['sub']))
    material=SemifinishedMaterial(material_code='REVIEW-RESOLVED',size='18',color_code='Black',color_key='black')
    db.add_all([invoice,material]);db.flush()
    allocation=InvoiceAllocation(invoice_id=invoice.id,material_id=material.id,status='allocated',allocated_qty_grams=200,
        pending_delta_grams=0,operation_key=None,pending_at=None)
    db.add(allocation);db.flush()
    row=gates.register_resource_scope(db,route='local',resource_kind='material',resource_key=str(material.id),warehouse_key='*',
        evidence={'checkpoint':'review-count','old_responsibilities_cleared':{'source_resolved':True},'writers_enforced':{'protocol':1}})
    assert row.route=='local' and allocation.allocated_qty_grams==200


def test_identical_existing_resource_replay_remains_readable_during_unrelated_unknown(db, stock, buyer):
    sku, warehouses=stock
    gates.set_policy(db,phase='transition',expected_version=gates.policy(db).version)
    evidence={'checkpoint':'same-count','old_responsibilities_cleared':{'reviewed':True},'writers_enforced':{'protocol':1}}
    original=gates.register_resource_scope(db,route='local',resource_kind='sku',resource_key=str(sku.id),
        warehouse_key=str(warehouses[0].id),evidence=evidence)
    invoice=Invoice(invoice_no='REVIEW-UNRELATED-LATE',customer_id='old',customer_name='Original',invoice_date=date(2026,10,3),
        transaction_mode='legacy',status='synced',created_by=int(buyer[1]['sub']))
    db.add(invoice);db.flush()
    gates.ensure_authority(db,invoice,route='legacy',confirmed=True,source_evidence={'source_invoice':invoice.id})
    db.add(SendingClaim(invoice_id=invoice.id,route='legacy',epoch=1,request_key='review-unrelated-late',operation='outbound_create',
        state='unknown',active_invoice_key=invoice.id,payload_hash='a'*64,responsibilities={'original':True}))
    db.flush()
    repeated=gates.register_resource_scope(db,route='local',resource_kind='sku',resource_key=str(sku.id),
        warehouse_key=str(warehouses[0].id),evidence=evidence)
    assert repeated.id==original.id
    with pytest.raises(ValueError):
        gates.register_resource_scope(db,route='local',resource_kind='sku',resource_key=str(sku.id),
            warehouse_key=str(warehouses[1].id),evidence=evidence)
