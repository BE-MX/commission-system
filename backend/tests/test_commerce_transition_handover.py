"""Real reviewed openings activate through the persistent frozen authority."""
from copy import deepcopy
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.commerce_transition import service as gates
from app.commerce_transition.models import InvoiceAuthority, PlatformPolicy, TransferPreparation
from app.commerce_migration import order_service, inventory_service, activation_service
from app.commerce_migration.activation_schemas import ActivationSelection, ActivationManifest
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.inventory.models import StockBalance, StockLedger
from app.invoice.models import Invoice, InvoiceLinkedSync
from tests.test_commerce_order_opening import inputs, seed_original_order, DAY
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock
from tests.test_finance_local import finance


def original(db, buyer, stock, *, tag='OLD'):
    raw = inputs(db, buyer, tag=tag)
    source = raw['orders'][0]
    source.update(source_received_amount='0', source_balance_amount='1000', commerce_status='confirmed', historical_shipment_ids=[])
    source['receivables'][0]['paid_amount'] = '0'
    source['items'][0].update(shipped_quantity=0, reservations=[{'warehouse_id': stock[1][0].id, 'quantity': 10}])
    invoice, _ = seed_original_order(db, raw, buyer[1])
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    return raw, invoice


def counted(db, stock, user, sku_id):
    sku, (warehouse, _) = stock
    manifest = InventoryOpeningManifest(batch_key='reviewed-physical', source='physical-count', tenant='warehouse',
        cutover_date=DAY, evidence_sha256='f'*64, review_reference='Actual isolated closing physical count', materials=[],
        stocks=[dict(external_id='counted-sku', mode='initialize', warehouse_id=warehouse.id,
                     local_sku_id=sku_id, quality='sellable', on_hand=10, reserved=0)])
    return inventory_service.apply_manifest(db, manifest, user)


def test_complete_original_opening_runs_real_transfer_callback_and_preserves_quantities(db, stock, buyer):
    raw, invoice = original(db, buyer, stock)
    before_id = invoice.id
    opening = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])
    preparation = db.get(TransferPreparation, opening['handover_preparation_id'])
    assert preparation.state == 'ready'
    assert invoice.transaction_mode == 'legacy' and invoice.commerce_status == 'opening'
    assert db.get(InvoiceAuthority, invoice.id).state == 'frozen'
    counted(db, stock, buyer[1], raw['orders'][0]['items'][0]['local_sku_id'])
    selected = ActivationSelection(request_key='real-handover', record_ids=[opening['orders'][0]['record_id']])
    review = activation_service.prepare(db, selected)
    assert review['report']['can_activate'], review['report']
    command = ActivationManifest.model_validate(review['command'])
    assert command.handover_preparation_id == preparation.id
    result = activation_service.activate(db, command, buyer[1])
    db.flush()
    assert invoice.id == before_id and invoice.transaction_mode == 'local'
    authority = db.get(InvoiceAuthority, invoice.id)
    assert (authority.route, authority.state, authority.epoch) == ('local', 'active', 2)
    assert preparation.state == 'completed' and preparation.verification['opening_receipt']['invoice_commerce_event_id']
    balance = db.scalar(select(StockBalance))
    assert (balance.on_hand, balance.reserved) == (10, 10)
    assert db.scalar(select(func.count()).select_from(Invoice)) == 1
    assert invoice.total_amount == Decimal('1000') and invoice.internal_received == 0
    assert activation_service.activate(db, command, buyer[1]) == result
    assert (balance.on_hand, balance.reserved) == (10, 10)
    with pytest.raises(ValueError, match='办理权'):
        gates.require_route(db, invoice, 'legacy', 1)


@pytest.mark.parametrize('state', ['running', 'uncertain'])
def test_original_unknown_freezes_without_posting_any_opening(db, stock, buyer, state):
    raw, invoice = original(db, buyer, stock)
    db.add(InvoiceLinkedSync(id='original-linked', invoice_id=invoice.id, request_key='original-linked',
        request_hash='a'*64, status=state, before={}, after={}, steps={}, created_by=int(buyer[1]['sub'])))
    db.flush()
    result = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])
    db.commit()
    assert result['status'] == 'waiting' and not result['orders']
    assert invoice.transaction_mode == 'legacy' and invoice.commerce_status != 'opening'
    assert db.get(InvoiceAuthority, invoice.id).state == 'frozen'
    assert db.get(TransferPreparation, result['handover_preparation_id']).state == 'waiting'
    assert db.scalar(select(func.count()).select_from(StockLedger)) == 0


def test_opening_rejects_shadow_source_and_missing_original_invoice(db, stock, buyer):
    raw = inputs(db, buyer)
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    with pytest.raises(ValueError, match='原发票'):
        order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])
    shadow = deepcopy(raw); shadow['source'] = 'shadow'
    with pytest.raises(ValueError, match='期初'):
        order_service.apply_manifest(db, OrderOpeningManifest.model_validate(shadow), buyer[1])


def test_shared_a600_b400_activates_whole_closure_without_recreating_principal(db, stock, finance):
    from app.commerce_migration import finance_service
    from app.commerce_migration.finance_schemas import FinanceOpeningManifest
    from app.commerce_transition.models import BankAccountDomain, BankIdentity
    from app.finance.transition_identity import reconcile_legacy_identity
    from app.invoice.settlement_models import ReceiptBatch
    from app.receipt.models import Receipt
    from app.models.commission import CommissionBatch, CommissionDetail, PaymentCommissionStatus, SyncedPayment
    customer, user, bank = finance
    raw = inputs(db, (customer, user))
    a = raw['orders'][0]
    a.update(source_received_amount='600', source_balance_amount='400', commerce_status='confirmed', historical_shipment_ids=[])
    a['items'][0].update(shipped_quantity=0, reservations=[])
    b = deepcopy(a)
    b.update(source_order_id='OLD-ORDER-B', invoice_no='OLD-INVOICE-B', source_received_amount='400', source_balance_amount='600')
    b['receivables'][0]['paid_amount'] = '400'
    raw_b = {**deepcopy(raw), 'batch_key': 'second-original', 'orders': [b]}
    invoice_a, _ = seed_original_order(db, raw, user)
    invoice_b, _ = seed_original_order(db, raw_b, user)
    raw['orders'].append(raw_b['orders'][0])
    batch = ReceiptBatch(batch_no='ORIGINAL-P', customer_id=a['source_customer_id'], currency='USD', gross_amount=1000,
        bank_account_id=bank.id, bank_reference='P-BANK', collection_date=DAY, payment_type='bank_transfer',
        transaction_mode='legacy', request_key='original-P', request_hash='a'*64, created_by=int(user['sub']))
    commission = CommissionBatch(batch_name='Original paid commissions', period_start=DAY, period_end=DAY, status='confirmed')
    db.add_all([batch, commission]); db.flush()
    receipts = []
    for invoice, amount, key in [(invoice_a, 600, 'PA'), (invoice_b, 400, 'PB')]:
        receipt = Receipt(receipt_no=key, invoice_id=invoice.id, batch_id=batch.id, source='manual',
            customer_id=a['source_customer_id'], xiaoman_order_id=invoice.xiaoman_order_id, xiaoman_receipt_id=key,
            purpose='ordinary', amount=amount, bank_charge=0, currency='USD', collection_date=DAY, payment_type='bank_transfer',
            collect_status=1, sync_status='synced', request_key=key, request_hash='b'*64, created_by=int(user['sub']))
        db.add_all([receipt, SyncedPayment(payment_id=key, order_id=invoice.xiaoman_order_id, customer_id=a['source_customer_id'],
            payment_date=DAY, payment_amount=amount, service_fee=0, exchange_rate=650, real_amount_rmb=Decimal(amount)*Decimal('6.5')),
            CommissionDetail(batch_id=commission.id, payment_id=key, order_id=invoice.xiaoman_order_id,
                customer_id=a['source_customer_id'], payment_amount=amount, salesperson_id='old-sales', salesperson_rate=Decimal('.02'),
                salesperson_commission=Decimal(amount)*Decimal('.02'), status='paid'),
            PaymentCommissionStatus(payment_id=key, batch_id=commission.id)])
        receipts.append(receipt)
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    domain = db.scalar(select(BankAccountDomain))
    domain.exclusive_route = None; db.flush()
    identity = reconcile_legacy_identity(db, domain_id=domain.id, transaction_id='P-BANK', batch_id=batch.id,
        statement_reference='Original P bank statement', actor_id=int(user['sub']))
    original_identity = identity.id
    with pytest.raises(ValueError, match='闭包'):
        order_service.apply_manifest(db, OrderOpeningManifest.model_validate({**raw, 'orders': raw['orders'][:1]}), user)
    opening = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), user)
    allocations = []
    for mapping, receipt in zip(opening['orders'], receipts, strict=True):
        allocations.append(dict(external_id=f'allocation-{receipt.id}', existing_receipt_id=receipt.id, invoice_id=receipt.invoice_id,
            order_binding_record_id=mapping['record_id'], receivable_id=mapping['receivables'][0]['receivable_id'],
            original_receipt_id=receipt.xiaoman_receipt_id, source_customer_id=a['source_customer_id'], purpose='ordinary',
            collection_date=DAY, amount=receipt.amount, bank_charge=0, remaining_commission_usd=receipt.amount))
    cash = FinanceOpeningManifest.model_validate(dict(batch_key='P-opening', source='okki', tenant=raw['tenant'], cutover_date=DAY,
        evidence_sha256='c'*64, review_reference='Original P full A600/B400 reconciliation', payments=[dict(external_id='P',
            existing_batch_id=batch.id, batch_no=batch.batch_no, local_customer_id=customer.id, source_customer_id=a['source_customer_id'],
            customer_external_identity_id=a['customer_external_identity_id'], bank_account_id=bank.id, bank_reference='P-BANK',
            currency='USD', gross_amount=1000, actual_bank_fee=0, allocated_amount=1000, refunded_amount=0, bank_charge_total=0,
            available_amount=0, rate_to_cny='6.5', rate_to_usd=1, collection_date=DAY, confirmed_date=DAY,
            confirmed_by=int(user['sub']), confirmed_at='2026-10-03T08:00:00', payment_type='bank_transfer', allocations=allocations)]))
    finance_service.apply_manifest(db, cash, user)
    review = activation_service.prepare(db, ActivationSelection(request_key='P-whole-activation',
        record_ids=[m['record_id'] for m in opening['orders']]))
    assert review['report']['can_activate'], review['report']
    activation_service.activate(db, ActivationManifest.model_validate(review['command']), user)
    db.flush()
    assert db.scalar(select(func.count()).select_from(ReceiptBatch)) == 1
    assert db.scalar(select(func.count()).select_from(BankIdentity)) == 1
    assert identity.id == original_identity and identity.route == 'local' and identity.payment_ref == f'local:{batch.id}'
    assert batch.gross_amount == batch.allocated_amount == 1000 and batch.refunded_amount == 0
    assert invoice_a.internal_received + invoice_b.internal_received == 1000
    assert invoice_a.transaction_mode == invoice_b.transaction_mode == 'local'


def test_settlement_reads_actual_zero_closure_and_freezes_old_writes(db, stock, buyer):
    from app.commerce_migration.settlement_schemas import SettlementManifest
    from app.commerce_migration import settlement_service
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    invoice = Invoice(invoice_no='settled-original', customer_id='old-customer', customer_name='Original', invoice_date=DAY,
        transaction_mode='legacy', commerce_status='cancelled', status='cancelled', internal_received=0, internal_balance=1,
        created_by=int(buyer[1]['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'original_cancelled_record': invoice.id})
    body = SettlementManifest(request_key='audited-close', evidence_sha256='e'*64, review_reference='Actual original closing ledger',
        invoices=[{'invoice_id': invoice.id, 'expected_authority_epoch': 1}])
    assert not settlement_service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='余额'):
        settlement_service.apply(db, body, buyer[1])
    invoice.internal_balance = 0; db.flush()
    before = db.get(InvoiceAuthority, invoice.id).lock_version
    assert settlement_service.preview(db, body)['can_apply']
    assert db.get(InvoiceAuthority, invoice.id).lock_version == before
    result = settlement_service.apply(db, body, buyer[1])
    assert result['request_key'] == 'audited-close'
    assert db.get(InvoiceAuthority, invoice.id).settled_evidence['evidence_sha256'] == 'e'*64
    with pytest.raises(ValueError, match='冻结'):
        gates.require_route(db, invoice, 'legacy', 1)
    assert settlement_service.apply(db, body, buyer[1]) == result
    gates.set_policy(db, phase='local_only', expected_version=gates.policy(db).version)


def test_settlement_rejects_unallocated_legacy_principal(db, stock, finance):
    from app.commerce_migration.settlement_schemas import SettlementManifest
    from app.commerce_migration import settlement_service
    from app.commerce_transition.models import BankAccountDomain
    from app.finance.transition_identity import reconcile_legacy_identity
    from app.invoice.settlement_models import ReceiptBatch
    customer, user, bank = finance
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    batch = ReceiptBatch(batch_no='old-unallocated', customer_id='old', currency='USD', gross_amount=1000,
        transaction_mode='legacy', bank_account_id=bank.id, bank_reference='old-unallocated-bank', collection_date=DAY,
        payment_type='bank_transfer', request_key='old-unallocated', request_hash='a'*64, created_by=int(user['sub']))
    db.add(batch); db.flush()
    domain = db.scalar(select(BankAccountDomain)); domain.exclusive_route = None; db.flush()
    identity = reconcile_legacy_identity(db, domain_id=domain.id, transaction_id=batch.bank_reference,
        batch_id=batch.id, statement_reference='Actual unallocated bank statement', actor_id=int(user['sub']))
    body = SettlementManifest(request_key='must-not-close-cash', evidence_sha256='e'*64,
        review_reference='A checkbox cannot consume cash', bank_identity_ids=[identity.id])
    report = settlement_service.preview(db, body)
    assert not report['can_apply']
    with pytest.raises(ValueError, match='未分配'):
        settlement_service.apply(db, body, user)
    assert identity.settled_evidence is None


def staged(db, stock, buyer):
    raw, invoice = original(db, buyer, stock)
    result = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])
    counted(db, stock, buyer[1], raw['orders'][0]['items'][0]['local_sku_id'])
    command = activation_service.prepare(db, ActivationSelection(request_key='guarded-handover',
        record_ids=[result['orders'][0]['record_id']]))['command']
    return invoice, ActivationManifest.model_validate(command)


def test_late_unknown_and_stale_epoch_cannot_complete_staged_handover(db, stock, buyer):
    invoice, body = staged(db, stock, buyer)
    authority = db.get(InvoiceAuthority, invoice.id)
    altered = body.model_copy(update={'expected_authority_epochs': {invoice.id: authority.epoch + 1}})
    with pytest.raises(ValueError, match='epoch'):
        activation_service.activate(db, altered, buyer[1])
    db.add(InvoiceLinkedSync(id='late-unknown', invoice_id=invoice.id, request_key='late-unknown',
        request_hash='a'*64, status='uncertain', before={}, after={}, steps={}, created_by=int(buyer[1]['sub'])))
    db.flush()
    assert not activation_service.preview(db, body)['can_activate']
    with pytest.raises(ValueError, match='unknown'):
        activation_service.activate(db, body, buyer[1])
    db.commit()
    assert (authority.route, authority.state, authority.epoch) == ('legacy', 'frozen', 1)
    assert invoice.transaction_mode == 'legacy' and invoice.commerce_status == 'opening'
    assert db.scalar(select(StockBalance.reserved)) == 0


def test_failed_real_callback_rolls_back_opening_and_keeps_old_authority_frozen(db, stock, buyer, monkeypatch):
    from app.commerce_migration import handover_service
    invoice, body = staged(db, stock, buyer)
    real = handover_service.reserve_opening_line
    def fail_after_real_post(*args):
        real(*args)
        raise ValueError('Callback interrupted after the real stock posting')
    monkeypatch.setattr(handover_service, 'reserve_opening_line', fail_after_real_post)
    before = db.scalar(select(func.count()).select_from(StockLedger))
    with pytest.raises(ValueError, match='Callback interrupted'):
        activation_service.activate(db, body, buyer[1])
    db.commit()
    assert (db.get(InvoiceAuthority, invoice.id).route, db.get(InvoiceAuthority, invoice.id).state) == ('legacy', 'frozen')
    assert invoice.transaction_mode == 'legacy' and invoice.commerce_status == 'opening'
    assert db.get(TransferPreparation, body.handover_preparation_id).state == 'ready'
    assert db.scalar(select(StockBalance.reserved)) == invoice.items[0].stock_reserved_quantity == 0
    assert db.scalar(select(func.count()).select_from(StockLedger)) == before


def test_handover_pending_preserves_legacy_cursor_then_waits_for_real_local_projection(db, stock, buyer):
    from app.customer.models import CustomerSyncCursor
    from app.trade.refresh_service import projection_status
    from app.trade.projection_service import project_invoice
    from app.core.time import beijing_now
    invoice, body = staged(db, stock, buyer)
    stamp = beijing_now()
    cursor = CustomerSyncCursor(source_system='okki', resource_type='orders', scope_key='default',
        sync_status='idle', generation=1, last_success_at=stamp, last_counts_json={})
    db.add(cursor); db.flush()
    state = projection_status(db)
    assert state['status'] == 'pending' and state['handover_pending_count'] == 1 and not state['data_complete']
    activation_service.activate(db, body, buyer[1])
    state = projection_status(db)
    assert state['handover_pending_count'] == 0 and state['pending_count'] == 1 and not state['data_complete']
    project_invoice(db, invoice.id); db.flush()
    assert projection_status(db)['data_complete']
    assert cursor.last_success_at == stamp and cursor.generation == 1


def test_completed_handover_real_old_sync_endpoint_rejects_before_external_post(db, stock, buyer, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.invoice.router import router
    from app.invoice import order_sync_execution
    from tests.authority_helpers import seed_authority
    invoice, body = staged(db, stock, buyer)
    activation_service.activate(db, body, buyer[1])
    identity = invoice.id
    user = {**buyer[1], 'roles': [], 'permissions': ['invoice:sync', 'invoice:read_all']}
    seed_authority(db, int(user['sub']), *user['permissions'])
    app = FastAPI(); app.include_router(router, prefix='/api/invoice')
    def session():
        db.rollback()
        try: yield db
        finally: db.rollback()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(order_sync_execution, 'token', lambda *_args, **_kw: pytest.fail('A migrated order reached the provider credential/send stage'))
    monkeypatch.setattr(order_sync_execution, 'send', lambda *_args, **_kw: pytest.fail('A migrated order reached external POST'))
    with TestClient(app) as client:
        response = client.post(f'/api/invoice/invoices/{identity}/sync')
    assert response.status_code == 409, response.text
    assert db.get(InvoiceAuthority, identity).route == 'local'


def test_standalone_original_production_activates_only_current_reviewed_resource(db, stock, buyer):
    from tests.test_commerce_production_opening import inputs as production_inputs
    from app.commerce_migration import production_service
    from app.commerce_migration.production_schemas import ProductionOpeningManifest
    from app.commerce_transition.models import ResourceScope
    raw, invoice, production, item = production_inputs(db, stock, buyer)
    source = raw['productions'][0]['items'][0]
    source.update(supplies=[], received_quantity=0)
    item.received_qty = 0
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    result = production_service.apply_manifest(db, ProductionOpeningManifest.model_validate(raw), buyer[1])
    review = activation_service.prepare(db, ActivationSelection(request_key='x'*64,
        record_ids=[result['productions'][0]['record_id']]))
    assert review['report']['can_activate'], review['report']
    body = ActivationManifest.model_validate(review['command'])
    scope = db.scalar(select(ResourceScope).where(ResourceScope.resource_kind == 'production',
        ResourceScope.resource_key == str(production.id)))
    scope.state = 'frozen'; db.flush()
    with pytest.raises(ValueError, match='冻结'):
        activation_service.activate(db, body, buyer[1])
    scope.state = 'active'; db.flush()
    stale = body.model_copy(update={'productions': [body.productions[0].model_copy(update={
        'items': [body.productions[0].items[0].model_copy(update={'expected_version': 999})]})]})
    with pytest.raises(ValueError, match='版本'):
        activation_service.activate(db, stale, buyer[1])
    result = activation_service.activate(db, body, buyer[1])
    assert production.transaction_mode == 'local' and body.handover_preparation_id is None
    assert activation_service.activate(db, body, buyer[1]) == result


def test_settlement_matches_unlinked_original_aftersales_by_original_order_identity(db, stock, buyer):
    from app.aftersales.models import AfterSalesCase
    from app.commerce_migration import settlement_service
    from app.commerce_migration.settlement_schemas import SettlementManifest
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    invoice = Invoice(invoice_no='old-aftersales-open', xiaoman_order_id='original-remote-order', customer_id='old',
        customer_name='Original', invoice_date=DAY, transaction_mode='legacy', commerce_status='cancelled',
        status='cancelled', internal_balance=0, created_by=int(buyer[1]['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'original_cancelled_id': invoice.id})
    case = AfterSalesCase(case_no='old-after-sale', creator_user_id=int(buyer[1]['sub']), creator_name_snapshot='Original',
        customer_id='old', customer_name_snapshot='Original', customer_grade='A', order_id=invoice.xiaoman_order_id,
        order_no_snapshot='Original', purchase_date=DAY, feedback_date=DAY, product_name_snapshot='Original goods',
        color_value='Black', length_value='18', weight_value=20, weight_unit='g', quantity=1,
        primary_issue_type='quality', problem_description='Actual pending historical case', occurred_stage='usage',
        affects_end_customer='yes', affected_goods_value=100, current_status='draft')
    db.add(case); db.flush()
    body = SettlementManifest(request_key='not-closed-aftersales', evidence_sha256='a'*64,
        review_reference='Check original source case identity', invoices=[{'invoice_id': invoice.id, 'expected_authority_epoch': 1}])
    assert not settlement_service.preview(db, body)['can_apply']
    with pytest.raises(ValueError): settlement_service.apply(db, body, buyer[1])
    assert db.get(InvoiceAuthority, invoice.id).settled_evidence is None


def test_settlement_api_reads_live_permission_and_rejects_stale_jwt_after_revocation(db, stock, buyer):
    from app.auth.models import ArkRolePermission, ArkUserRole
    from app.commerce_migration.settlement_schemas import SettlementManifest
    from tests.test_commerce_migration_workbench_api import client_for
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    invoice = Invoice(invoice_no='http-close', customer_id='old', customer_name='Original', invoice_date=DAY,
        transaction_mode='legacy', commerce_status='cancelled', status='cancelled', internal_balance=0,
        created_by=int(buyer[1]['sub']))
    db.add(invoice); db.flush()
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True, source_evidence={'original_cancelled_id': invoice.id})
    body = SettlementManifest(request_key='http-closed', evidence_sha256='b'*64, review_reference='Actual original cancelled closure',
        invoices=[{'invoice_id': invoice.id, 'expected_authority_epoch': 1}]).model_dump(mode='json')
    user = {**buyer[1], 'roles': [], 'permissions': ['commerce_migration:admin']}
    with client_for(db, user) as client:
        before = db.get(InvoiceAuthority, invoice.id).lock_version
        response = client.post('/api/commerce-migration/settlement/preview', json=body)
        assert response.status_code == 200 and response.json()['data']['can_apply'], response.text
        assert db.get(InvoiceAuthority, invoice.id).lock_version == before
        response = client.post('/api/commerce-migration/settlement', json=body)
        assert response.status_code == 200 and response.json()['data']['request_key'] == 'http-closed', response.text
        roles = select(ArkUserRole.role_id).where(ArkUserRole.user_id == int(user['sub']))
        db.query(ArkRolePermission).filter(ArkRolePermission.role_id.in_(roles)).delete(synchronize_session=False)
        db.commit()
        for path in ['settlement/preview', 'settlement']:
            assert client.post('/api/commerce-migration/' + path, json=body).status_code == 403


@pytest.mark.parametrize('workflow', ['cancel_pending', 'deleting', 'uncertain', 'cascade_running', 'cascade_uncertain', 'cascade_blocked', 'receipt_delete'])
def test_terminal_remove_claim_does_not_hide_unfinished_local_workflow(db, stock, buyer, workflow):
    from app.commerce_transition.models import SendingClaim
    from app.receipt.models import Receipt, ReceiptLog
    import json
    raw, invoice = original(db, buyer, stock)
    gates.ensure_authority(db, invoice, route='legacy', confirmed=True,
        source_evidence={'original_remove_invoice_id': invoice.id})
    claim = SendingClaim(invoice_id=invoice.id, request_key='already-acknowledged-remove', operation='order_remove',
        route='legacy', epoch=1, state='succeeded', payload_hash='a'*64, active_invoice_key=None, responsibilities={})
    db.add(claim)
    if workflow == 'cancel_pending':
        invoice.status = 'cancel_pending'
    elif workflow == 'receipt_delete':
        receipt = Receipt(receipt_no='delete-not-finalized', invoice_id=invoice.id, customer_id=invoice.customer_id,
            source='manual', purpose='ordinary', amount=10, bank_charge=0, currency='USD', collection_date=DAY,
            payment_type='bank_transfer', collect_status=1, sync_status='synced', status='active',
            xiaoman_receipt_id='old-receipt-delete', request_key='old-delete-receipt', request_hash='a'*64,
            created_by=int(buyer[1]['sub']))
        db.add(receipt); db.flush()
        db.add(ReceiptLog(receipt_id=receipt.id, action='delete_started', message=json.dumps({
            'token': 'old-token', 'target': 'old-receipt-delete', 'reason': 'Actual unfinished old deletion'})))
    else:
        invoice.cancellation = {'status': workflow}
    db.flush()
    result = order_service.apply_manifest(db, OrderOpeningManifest.model_validate(raw), buyer[1])
    db.commit()
    assert result['status'] == 'waiting' and result['orders'] == []
    assert claim.state == 'succeeded' and db.get(InvoiceAuthority, invoice.id).state == 'frozen'
    assert db.get(TransferPreparation, result['handover_preparation_id']).state == 'waiting'
    assert invoice.transaction_mode == 'legacy' and invoice.commerce_status != 'opening'
    assert db.scalar(select(func.count()).select_from(StockLedger)) == 0
