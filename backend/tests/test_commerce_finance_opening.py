"""Historical cash is not fresh revenue and may not be imported twice."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import func, select
from app.commerce_migration import finance_service as service
from app.commerce_migration.finance_schemas import FinanceOpeningManifest
from app.commerce_migration.models import MigrationBatch, MigrationRecord
from app.commission.models import CommissionBasis, CommissionEventProjection
from app.customer.models import CustomerExternalIdentity
from app.core.time import beijing_now
from app.finance import service as finance_service
from app.finance.models import FinanceEvent
from app.finance.query_service import reconcile
from app.invoice.settlement_models import ReceiptBatch
from app.models.commission import CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus
from app.receipt.models import Receipt
from tests.test_finance_local import finance, stock, buyer, order, cmd
from tests.test_commission_local import batch
from app.services.commission_calculator import calculate_commission

DAY = date(2026, 10, 3)



def account_domain(db, account):
    from app.commerce_transition import service as gates
    from app.core.config import get_settings
    settings = get_settings()
    return gates.register_bank_domain(db, subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY,
        account_key=account.code, channel=settings.COMMERCE_BANK_CHANNEL, bank_account_ids=[account.id],
        legacy_identity_complete=True, enforced=True, exclusive_route=None,
        evidence={'review_reference': 'Isolated original bank account and complete source-cash fixture'})


def reconcile_original_cash(db, finance, cash, raw):
    from app.commerce_transition import service as gates
    from app.finance.transition_identity import reconcile_legacy_identity
    gates.set_policy(db, phase='transition', expected_version=gates.policy(db).version)
    domain = account_domain(db, finance[2])
    return reconcile_legacy_identity(db, domain_id=domain.id, transaction_id=raw['payments'][0]['bank_reference'],
        batch_id=cash.id, statement_reference='Original whole cash statement, source fixture', actor_id=int(finance[1]['sub']))

def counts(db):
    return [db.scalar(select(func.count()).select_from(model)) for model in
        (MigrationBatch, MigrationRecord, ReceiptBatch, Receipt, FinanceEvent, CommissionBasis, SyncedPayment, CommissionEventProjection)]


def inputs(db, finance, stock, buyer, *, invoice_target=None):
    customer, user, bank = finance
    invoice, target = invoice_target or order(db, stock, buyer)
    invoice.xiaoman_order_id = 'OLD-ORDER'
    customer_identity = CustomerExternalIdentity(customer_id=customer.id, source_system='okki', source_account_key='tenant-A',
        identifier_type='company_id', raw_value='OLD-CUSTOMER', normalized_value='OLD-CUSTOMER',
        identity_strength='strong', cardinality='one_to_one', auto_match_ceiling='verified', verification_status='verified',
        confidence=1, confidence_method_version='confidence_v1', confidence_components_json={}, is_primary=True,
        first_seen_at=beijing_now(), last_seen_at=beijing_now(), status='active', identity_fingerprint='f'*64)
    db.add(customer_identity); db.flush()
    proof_batch = MigrationBatch(batch_key='order-proof', source='okki', tenant='tenant-A', manifest_hash='a'*64,
        evidence_sha256='b'*64, review_reference='Synthetic order responsibility proof', cutover_date=DAY,
        result={}, created_by=int(user['sub']))
    db.add(proof_batch); db.flush()
    proof = MigrationRecord(batch_key=proof_batch.batch_key, source='okki', tenant='tenant-A', object_type='order_binding',
        external_id='OLD-ORDER', role='opening', content_hash='c'*64, local_invoice_id=invoice.id,
        snapshot=dict(invoice_id=invoice.id, local_customer_id=customer.id, source_order_id='OLD-ORDER', source_customer_id='OLD-CUSTOMER'))
    db.add(proof)
    old_batch = CommissionBatch(batch_name='Paid historical', period_start=DAY, period_end=DAY, status='confirmed')
    db.add(old_batch); db.flush()
    for identity, gross, fee, commission in [('OLD-PAYMENT', 600, 0, '7.01'), ('OLD-REFUND', -200, 0, '-2.34')]:
        db.add_all([SyncedPayment(payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
            payment_date=DAY, payment_amount=gross, service_fee=fee, exchange_rate=650, real_amount_rmb=Decimal(gross)*Decimal('6.5')),
            CommissionDetail(batch_id=old_batch.id, payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
                payment_amount=gross, salesperson_id='old-salesperson', salesperson_rate=Decimal('.02'),
                salesperson_commission=Decimal(commission), status='paid'),
            PaymentCommissionStatus(payment_id=identity, batch_id=old_batch.id)])
    db.flush()
    raw = dict(batch_key='financial-opening', source='okki', tenant='tenant-A', cutover_date='2026-10-03',
        evidence_sha256='d'*64, review_reference='Synthetic full historical cash reconciliation', payments=[dict(
            external_id='OLD-CASH', batch_no='HIST-CASH', local_customer_id=customer.id, source_customer_id='OLD-CUSTOMER',
            customer_external_identity_id=customer_identity.id, bank_account_id=bank.id,
            bank_reference='HIST-BANK', currency='USD', gross_amount='600', actual_bank_fee='0', rate_to_cny='6.5', rate_to_usd='1',
            allocated_amount='400', refunded_amount='200', bank_charge_total='0', available_amount='0',
            collection_date='2026-10-03', confirmed_date='2026-10-03', confirmed_by=int(user['sub']),
            confirmed_at='2026-10-03T09:00:00', payment_type='bank_transfer', refunds=[dict(
                external_id='OLD-REFUND', amount='200', bank_reference='HIST-REFUND', business_date='2026-10-03')],
            allocations=[dict(external_id='OLD-ALLOC', invoice_id=invoice.id, receivable_id=target.id,
                order_binding_record_id=proof.id, original_receipt_id='OLD-PAYMENT', source_customer_id='OLD-CUSTOMER',
                purpose='ordinary', collection_date='2026-10-03', amount='600', reversed_amount='200',
                remaining_commission_usd='400', prior_reversals=[dict(payment_id='OLD-REFUND', amount='200', bank_charge='0', rate_to_usd='1', rate_to_cny='6.5', business_date='2026-10-03')])])])
    return raw, invoice, target


def test_cash_opening_preview_replays_after_new_reversal_and_refund_without_reset(db, finance, stock, buyer):
    raw, invoice, target = inputs(db, finance, stock, buyer)
    body = FinanceOpeningManifest.model_validate(raw)
    before = counts(db)
    assert service.preview(db, body)['can_apply'] and counts(db) == before
    result = service.apply_manifest(db, body, finance[1]); db.commit()
    assert counts(db) == [2, 2, 1, 1, 3, 1, 2, 0]
    cash = db.get(ReceiptBatch, result['payments'][0]['batch_id'])
    receipt = db.get(Receipt, result['payments'][0]['allocations'][0]['receipt_id'])
    assert cash.allocated_amount == target.paid_amount == invoice.internal_received == 400
    assert cash.refunded_amount == 200 and finance_service.available(cash) == 0
    assert invoice.total_amount == 1000 and invoice.internal_balance == 600
    assert reconcile(db, finance[1])['differences'] == []
    assert calculate_commission(db, batch(db, 'No new historical income').id).total_payments == 0
    finance_service.reverse_allocation(db, receipt.id, cmd('new-return', receipt.version, amount=100), finance[1])
    finance_service.refund(db, cash.id, cmd('new-refund', cash.version, amount=100, bank_reference='NEW-REFUND'), finance[1])
    db.commit()
    later = counts(db)
    assert service.apply_manifest(db, body, finance[1]) == result
    different_batch = body.model_copy(update={'batch_key': 'financial-repeat'})
    assert service.apply_manifest(db, different_batch, finance[1])['payments'] == result['payments']
    db.commit()
    assert cash.allocated_amount == target.paid_amount == invoice.internal_received == 300
    assert cash.refunded_amount == 300 and finance_service.available(cash) == 0
    assert counts(db)[2:] == later[2:] and reconcile(db, finance[1])['differences'] == []
    assert calculate_commission(db, batch(db, 'Only new negative').id).total_salesperson_commission == Decimal('-1.17')


def test_existing_legacy_cash_and_receipt_keep_ids_original_faces_and_private_proof(db, finance, stock, buyer):
    raw, invoice, target = inputs(db, finance, stock, buyer)
    customer, user, _ = finance
    cash = ReceiptBatch(batch_no='HIST-CASH', customer_id='OLD-CUSTOMER', currency='USD', gross_amount=600,
        collection_date=DAY, payment_type='bank_transfer', request_key='legacy-cash-key', request_hash='a'*64,
        created_by=int(user['sub']))
    db.add(cash); db.flush()
    receipt = Receipt(receipt_no='LEGACY-NO', invoice_id=invoice.id, batch_id=cash.id, source='manual', purpose='ordinary',
        request_key='legacy-receipt-key', request_hash='b'*64, amount=600, bank_charge=0, currency='USD', collection_date=DAY,
        payment_type='bank_transfer', customer_id='OLD-CUSTOMER', xiaoman_order_id='OLD-ORDER', xiaoman_receipt_id='OLD-PAYMENT',
        collect_status=1, sync_status='synced', attachment_ids=['existing-private-proof'], created_by=int(user['sub']))
    db.add(receipt); db.flush()
    reconcile_original_cash(db, finance, cash, raw)
    raw['payments'][0]['existing_batch_id'] = cash.id
    raw['payments'][0]['allocations'][0]['existing_receipt_id'] = receipt.id
    body = FinanceOpeningManifest.model_validate(raw)
    result = service.apply_manifest(db, body, user); db.commit()
    assert result['payments'][0]['batch_id'] == cash.id
    assert result['payments'][0]['allocations'][0]['receipt_id'] == receipt.id
    assert receipt.amount == 600 and receipt.reversed_amount == 200 and receipt.receipt_no == 'LEGACY-NO'
    assert receipt.attachment_ids == ['existing-private-proof'] and receipt.request_key == 'legacy-receipt-key'
    assert cash.request_key == 'legacy-cash-key' and receipt.source == 'local'
    assert cash.version == receipt.version == 2
    assert reconcile(db, user)['differences'] == []


@pytest.mark.parametrize('purpose', ['ordinary', 'presale_deposit', 'presale_balance'])
def test_multiple_payments_obey_full_order_and_presale_component_caps(db, finance, stock, buyer, purpose):
    from copy import deepcopy
    raw, invoice, target = inputs(db, finance, stock, buyer)
    second = deepcopy(raw['payments'][0])
    second.update(external_id='SECOND-CASH', batch_no='SECOND-CASH', bank_reference='SECOND-BANK')
    second['refunds'][0].update(external_id='SECOND-REFUND', bank_reference='SECOND-REFUND-BANK')
    second['allocations'][0].update(external_id='SECOND-ALLOC', original_receipt_id='SECOND-PAYMENT')
    second['allocations'][0]['prior_reversals'][0]['payment_id'] = 'SECOND-REFUND'
    raw['payments'].append(second)
    old_batch_id = db.scalar(select(CommissionBatch.id))
    for identity, gross, commission in [('SECOND-PAYMENT', 600, '7.01'), ('SECOND-REFUND', -200, '-2.34')]:
        db.add_all([SyncedPayment(payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
            payment_date=DAY, payment_amount=gross, service_fee=0, exchange_rate=650, real_amount_rmb=Decimal(gross)*Decimal('6.5')),
            CommissionDetail(batch_id=old_batch_id, payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
                payment_amount=gross, salesperson_id='old-salesperson', salesperson_rate=Decimal('.02'),
                salesperson_commission=Decimal(commission), status='paid'),
            PaymentCommissionStatus(payment_id=identity, batch_id=old_batch_id)])
    if purpose != 'ordinary':
        invoice.order_type = 'presale'
        invoice.local_deposit_amount = Decimal('600')
        for payment in raw['payments']:
            payment['allocations'][0]['purpose'] = purpose
    db.flush()
    body = FinanceOpeningManifest.model_validate(raw)
    before = counts(db)
    report = service.preview(db, body)
    if purpose == 'ordinary':
        assert report['can_apply']
        service.apply_manifest(db, body, finance[1]); db.commit()
        assert target.paid_amount == invoice.internal_received == 800 and invoice.internal_balance == 200
        assert reconcile(db, finance[1])['differences'] == []
    else:
        assert not report['can_apply'] and any(c['code'] == 'presale_opening_excess' for c in report['conflicts'])
        with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
        db.commit()
        assert counts(db) == before and target.paid_amount == invoice.internal_received == 0


@pytest.mark.parametrize('field,value', [('bank_reference', 'DIFFERENT-BANK'), ('rate_to_cny', Decimal('7')),
    ('actual_bank_fee', Decimal('10')), ('net_amount', Decimal('590'))])
def test_existing_bank_evidence_cannot_be_overwritten(db, finance, stock, buyer, field, value):
    raw, _, _ = inputs(db, finance, stock, buyer)
    raw['payments'][0].update(allocations=[], allocated_amount='0', bank_charge_total='0', available_amount='400')
    cash = ReceiptBatch(batch_no='HIST-CASH', customer_id='OLD-CUSTOMER', currency='USD', gross_amount=600,
        collection_date=DAY, payment_type='bank_transfer', request_key='known-legacy-cash', request_hash='a'*64,
        created_by=int(finance[1]['sub']))
    setattr(cash, field, value)
    db.add(cash); db.flush()
    reconcile_original_cash(db, finance, cash, raw)
    raw['payments'][0]['existing_batch_id'] = cash.id
    body = FinanceOpeningManifest.model_validate(raw)
    before = counts(db)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
    db.commit()
    assert counts(db) == before and getattr(cash, field) == value and cash.transaction_mode == 'legacy'


def test_apply_rechecks_current_proof_even_when_preview_is_stale(db, finance, stock, buyer, monkeypatch):
    raw, _, _ = inputs(db, finance, stock, buyer)
    body = FinanceOpeningManifest.model_validate(raw)
    report = service.preview(db, body)
    assert report['can_apply']
    db.delete(db.get(CustomerExternalIdentity, raw['payments'][0]['customer_external_identity_id'])); db.commit()
    before = counts(db)
    monkeypatch.setattr(service, 'preview', lambda *args, **kwargs: report)
    with pytest.raises(ValueError, match='客户身份'): service.apply_manifest(db, body, finance[1])
    db.commit()
    assert counts(db) == before


def test_nonzero_legacy_invoice_summary_requires_an_explicit_baseline(db, finance, stock, buyer):
    raw, invoice, _ = inputs(db, finance, stock, buyer)
    invoice.internal_received, invoice.internal_balance = Decimal('400'), Decimal('600')
    db.flush()
    before = counts(db)
    assert not service.preview(db, FinanceOpeningManifest.model_validate(raw))['can_apply']
    assert counts(db) == before and invoice.internal_received == 400


def test_ordinary_principal_cannot_consume_unpaid_handling_responsibility(db, finance, stock, buyer):
    raw, invoice, target = inputs(db, finance, stock, buyer)
    target.handling_amount = Decimal('700')  # Principal is 300 of the full 1000 AR.
    db.flush()
    body = FinanceOpeningManifest.model_validate(raw)
    before = counts(db)
    report = service.preview(db, body)
    assert not report['can_apply'] and any(c['code'] == 'ar_opening_excess' for c in report['conflicts'])
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
    db.commit()
    assert counts(db) == before and target.paid_amount == invoice.internal_received == 0


def test_existing_deposit_cannot_be_reclassified_as_balance(db, finance, stock, buyer):
    raw, invoice, target = inputs(db, finance, stock, buyer)
    invoice.order_type, invoice.local_deposit_amount = 'presale', Decimal('600')
    cash = ReceiptBatch(batch_no='HIST-CASH', customer_id='OLD-CUSTOMER', currency='USD', gross_amount=600,
        collection_date=DAY, payment_type='bank_transfer', request_key='legacy-deposit-cash', request_hash='a'*64,
        created_by=int(finance[1]['sub']))
    db.add(cash); db.flush()
    receipt = Receipt(receipt_no='LEGACY-DEPOSIT', invoice_id=invoice.id, batch_id=cash.id, source='auto', purpose='presale_deposit',
        receivable_id=target.id, request_key='legacy-deposit', request_hash='b'*64, amount=600, bank_charge=0,
        currency='USD', collection_date=DAY, payment_type='bank_transfer', customer_id='OLD-CUSTOMER',
        xiaoman_order_id='OLD-ORDER', xiaoman_receipt_id='OLD-PAYMENT', collect_status=1, sync_status='synced',
        created_by=int(finance[1]['sub']))
    db.add(receipt); db.flush()
    reconcile_original_cash(db, finance, cash, raw)
    raw['payments'][0]['existing_batch_id'] = cash.id
    raw['payments'][0]['allocations'][0].update(existing_receipt_id=receipt.id, purpose='presale_balance')
    before = counts(db)
    body = FinanceOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
    db.commit()
    assert counts(db) == before and receipt.purpose == 'presale_deposit'
    raw['payments'][0]['allocations'][0]['purpose'] = 'presale_deposit'
    body = FinanceOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    service.apply_manifest(db, body, finance[1]); db.commit()
    assert receipt.id == raw['payments'][0]['allocations'][0]['existing_receipt_id']
    assert receipt.purpose == 'presale_deposit' and target.paid_amount == 400


@pytest.mark.parametrize('mutation', ['unknown_order_proof', 'wrong_customer', 'fx_changed', 'missing_old_commission', 'wrong_original_face', 'same_net_different_faces', 'invented_fee'])
def test_differences_are_previewed_without_financial_effects(db, finance, stock, buyer, mutation):
    raw, _, _ = inputs(db, finance, stock, buyer)
    if mutation == 'unknown_order_proof': raw['payments'][0]['allocations'][0]['order_binding_record_id'] = 999
    elif mutation == 'wrong_customer': raw['payments'][0]['customer_external_identity_id'] = 999
    elif mutation == 'fx_changed': raw['payments'][0]['rate_to_cny'] = '7'
    elif mutation == 'missing_old_commission': db.delete(db.scalar(select(PaymentCommissionStatus).where(PaymentCommissionStatus.payment_id == 'OLD-PAYMENT'))); db.flush()
    elif mutation == 'wrong_original_face':
        raw['payments'][0]['allocations'][0]['amount'] = '500'
        raw['payments'][0].update(allocated_amount='300', available_amount='100')
    elif mutation == 'same_net_different_faces':
        raw['payments'][0]['allocations'][0].update(amount='500', reversed_amount='100')
        raw['payments'][0]['allocations'][0]['prior_reversals'][0]['amount'] = '100'
    elif mutation == 'invented_fee':
        raw['payments'][0]['allocations'][0]['bank_charge'] = '100'
        raw['payments'][0]['bank_charge_total'] = '100'
    body = FinanceOpeningManifest.model_validate(raw)
    before = counts(db)
    report = service.preview(db, body)
    assert not report['can_apply'] and report['conflicts'][0]['section'] == 'payments'
    assert counts(db) == before
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
    db.commit()
    assert counts(db) == before


def test_late_failure_removes_all_financial_effects_even_if_caller_commits(db, finance, stock, buyer, monkeypatch):
    raw, invoice, target = inputs(db, finance, stock, buyer)
    body = FinanceOpeningManifest.model_validate(raw)
    db.commit()
    before = counts(db)
    real_post = service._post_payment
    def fail_after_real_money(*args):
        real_post(*args)
        raise ValueError('Synthetic interruption after all baseline postings')
    monkeypatch.setattr(service, '_post_payment', fail_after_real_money)
    with pytest.raises(ValueError, match='interruption'): service.apply_manifest(db, body, finance[1])
    db.commit(); db.expire_all()
    assert counts(db) == before and target.paid_amount == invoice.internal_received == 0
    assert invoice.internal_balance == 1000


def test_new_source_cannot_reimport_same_cash_or_rewrite_original_content(db, finance, stock, buyer):
    raw, _, _ = inputs(db, finance, stock, buyer)
    body = FinanceOpeningManifest.model_validate(raw)
    service.apply_manifest(db, body, finance[1]); db.commit()
    raw.update(batch_key='other-source', source='other-export')
    alternative = FinanceOpeningManifest.model_validate(raw)
    assert not service.preview(db, alternative)['can_apply']
    raw.update(batch_key='changed-body', source='okki')
    raw['payments'][0]['remark'] = 'Changed original fact'
    assert not service.preview(db, FinanceOpeningManifest.model_validate(raw))['can_apply']


def test_rounded_cross_currency_rate_uses_verified_original_fx(db, finance, stock, buyer):
    from app.finance.models import Currency, BankAccount
    from app.api.commission import _detail_schema_from_row
    from app.commission.query_service import detail_rows
    raw, invoice, target = inputs(db, finance, stock, buyer)
    db.add(Currency(code='EUR', name='EUR', rate_to_cny=Decimal('8.1')))
    account = BankAccount(code='HIST-EUR', name='Historical EUR', currency='EUR')
    db.add(account); db.flush()
    account_domain(db, account)
    invoice.currency = target.currency = 'EUR'
    payment_input = raw['payments'][0]
    payment_input.update(currency='EUR', bank_account_id=account.id, rate_to_cny='8.1', rate_to_usd='1.15714286')
    payment_input['allocations'][0]['remaining_commission_usd'] = '462.86'
    payment_input['allocations'][0]['prior_reversals'][0].update(rate_to_cny='8.1', rate_to_usd='1.15714286')
    for identity, amount, rmb in [('OLD-PAYMENT', Decimal('694.29'), 4860), ('OLD-REFUND', Decimal('-231.43'), -1620)]:
        payment_row = db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == identity))
        payment_row.payment_amount, payment_row.exchange_rate, payment_row.real_amount_rmb = amount, Decimal('700'), Decimal(rmb)
        db.scalar(select(CommissionDetail).where(CommissionDetail.payment_id == identity)).payment_amount = amount
    db.flush()
    body = FinanceOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    result = service.apply_manifest(db, body, finance[1])
    receipt = db.get(Receipt, result['payments'][0]['allocations'][0]['receipt_id'])
    finance_service.reverse_allocation(db, receipt.id, cmd('full-eur-reversal', receipt.version, amount=400), finance[1])
    new_batch = batch(db, 'Rounded original FX')
    assert calculate_commission(db, new_batch.id).total_salesperson_commission == Decimal('-4.67')
    assert _detail_schema_from_row(detail_rows(db, new_batch.id)[0]).salesperson_commission_rmb == -32.69
    assert reconcile(db, finance[1])['differences'] == []


@pytest.mark.parametrize('mixed_fx', [False, True])
def test_each_old_foreign_reversal_keeps_its_usd_rounding_and_paid_rmb(db, finance, stock, buyer, mixed_fx):
    from app.finance.models import Currency, BankAccount
    from app.commission.query_service import detail_rows
    from app.api.commission import _detail_schema_from_row
    raw, invoice, target = inputs(db, finance, stock, buyer)
    db.add(Currency(code='EUR', name='EUR', rate_to_cny=Decimal('8.1')))
    account = BankAccount(code='EUR-MULTI', name='EUR multiple historical reversals', currency='EUR')
    db.add(account); db.flush()
    account_domain(db, account)
    invoice.currency = target.currency = 'EUR'
    item = raw['payments'][0]
    item.update(currency='EUR', bank_account_id=account.id, rate_to_cny='8.1', rate_to_usd='1.15714286')
    allocation = item['allocations'][0]
    allocation['remaining_commission_usd'] = '462.87'
    allocation['prior_reversals'] = [dict(payment_id='OLD-REFUND', amount='100', bank_charge='0',
        rate_to_usd='1.15714286', rate_to_cny='8.1', business_date='2026-10-03'),
        dict(payment_id='OLD-REFUND-2', amount='100', bank_charge='0', rate_to_usd='1.15714286',
            rate_to_cny='7.52142859' if mixed_fx else '8.1', business_date='2026-10-03')]
    original = db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == 'OLD-PAYMENT'))
    original.payment_amount, original.exchange_rate, original.real_amount_rmb = Decimal('694.29'), 700, 4860
    db.scalar(select(CommissionDetail).where(CommissionDetail.payment_id == 'OLD-PAYMENT')).payment_amount = Decimal('694.29')
    old_refund = db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == 'OLD-REFUND'))
    old_refund.payment_amount, old_refund.exchange_rate, old_refund.real_amount_rmb = Decimal('-115.71'), 700, -810
    old_detail = db.scalar(select(CommissionDetail).where(CommissionDetail.payment_id == 'OLD-REFUND'))
    old_detail.payment_amount, old_detail.salesperson_commission = Decimal('-115.71'), Decimal('-1.17')
    db.add_all([SyncedPayment(payment_id='OLD-REFUND-2', order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
        payment_date=DAY, payment_amount=Decimal('-115.71'), service_fee=0, exchange_rate=650 if mixed_fx else 700,
        real_amount_rmb=Decimal('-752.14') if mixed_fx else Decimal('-810')),
        CommissionDetail(batch_id=old_detail.batch_id, payment_id='OLD-REFUND-2', order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
            payment_amount=Decimal('-115.71'), salesperson_id='old-salesperson', salesperson_rate=Decimal('.02'),
            salesperson_commission=Decimal('-1.17'), status='paid'),
        PaymentCommissionStatus(payment_id='OLD-REFUND-2', batch_id=old_detail.batch_id)])
    db.flush()
    body = FinanceOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    result = service.apply_manifest(db, body, finance[1])
    receipt = db.get(Receipt, result['payments'][0]['allocations'][0]['receipt_id'])
    for index, amount in enumerate([Decimal('133.33'), Decimal('133.33'), Decimal('133.34')]):
        finance_service.reverse_allocation(db, receipt.id, cmd(f'multi-eur-reversal-{index}', receipt.version, amount=amount), finance[1])
    new_batch = batch(db, 'Historical cross currency residual')
    assert calculate_commission(db, new_batch.id).total_salesperson_commission == Decimal('-4.67')
    rows = detail_rows(db, new_batch.id)
    # Legacy UI rounded -1.17 * 6.5 to -7.60; preserve that paid/displayed cent.
    expected = Decimal('-33.28') if mixed_fx else Decimal('-32.69')
    assert sum(Decimal(str(_detail_schema_from_row(row).salesperson_commission_rmb)) for row in rows) == expected
    assert sum(p.payment_amount - p.service_fee for p in db.scalars(select(SyncedPayment).where(SyncedPayment.payment_id.like('ark-finance:%')))) == Decimal('-462.87')
    assert reconcile(db, finance[1])['differences'] == []


def test_unallocated_legacy_payment_cannot_change_customer_without_verified_identity(db, finance, stock, buyer):
    raw, _, _ = inputs(db, finance, stock, buyer)
    payment_input = raw['payments'][0]
    payment_input.update(allocations=[], refunds=[], allocated_amount='0', refunded_amount='0', available_amount='600')
    cash = ReceiptBatch(batch_no='HIST-CASH', customer_id='OTHER-CUSTOMER', currency='USD', gross_amount=600,
        collection_date=DAY, payment_type='bank_transfer', request_key='legacy-unallocated', request_hash='a'*64,
        created_by=int(finance[1]['sub']))
    db.add(cash); db.flush()
    payment_input['existing_batch_id'] = cash.id
    body = FinanceOpeningManifest.model_validate(raw)
    assert not service.preview(db, body)['can_apply']
    with pytest.raises(ValueError, match='冲突'): service.apply_manifest(db, body, finance[1])
    assert cash.customer_id == 'OTHER-CUSTOMER' and cash.transaction_mode == 'legacy'


def test_customer_split_uses_current_identity_owner_for_unallocated_cash(db, finance, stock, buyer):
    from datetime import timedelta
    from app.customer.models import CustomerChangeProposal, CustomerObjectOwnership
    from tests.test_customer_facts import _customer
    from tests.test_customer_governance_policy import _profile, _digest
    raw, _, _ = inputs(db, finance, stock, buyer)
    storage = finance[0]
    target = _customer(db, 'current-owner-after-split')
    profile = _profile(db, storage)
    proposal = CustomerChangeProposal(customer_id=storage.id, target_customer_id=target.id, action_type='split',
        payload_schema_version='customer_split_v1', payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level='critical', data_classification='restricted_internal', visibility_scope='management',
        action_hash=_digest('financial-opening-split'), status='executed', expires_at=beijing_now()+timedelta(days=1))
    db.add(proposal); db.flush()
    payment_input = raw['payments'][0]
    db.add(CustomerObjectOwnership(object_type='external_identity', object_id=payment_input['customer_external_identity_id'],
        storage_customer_id=storage.id, current_customer_id=target.id, ownership_version=1,
        last_change_proposal_id=proposal.id, last_action_type='split'))
    db.flush()
    payment_input.update(allocations=[], refunds=[], allocated_amount='0', refunded_amount='0', available_amount='600')
    assert not service.preview(db, FinanceOpeningManifest.model_validate(raw))['can_apply']
    payment_input['local_customer_id'] = target.id
    body = FinanceOpeningManifest.model_validate(raw)
    assert service.preview(db, body)['can_apply']
    result = service.apply_manifest(db, body, finance[1]); db.commit()
    assert db.get(ReceiptBatch, result['payments'][0]['batch_id']).local_customer_id == target.id


def test_financial_import_api_requires_migration_admin(db, finance, stock, buyer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.commerce_migration.router import router
    raw, _, _ = inputs(db, finance, stock, buyer)
    user = dict(sub=finance[1]['sub'], roles=[], permissions=['receipt:admin'])
    app = FastAPI(); app.include_router(router, prefix='/api/commerce-migration')
    app.dependency_overrides[get_current_user] = lambda: user
    from tests.authority_helpers import seed_authority
    seed_authority(db, int(user['sub']), *user.get('permissions', []), roles=user.get('roles', []))
    def request_session():
        # TestClient requests own a fresh transaction, like production get_db.
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    app.dependency_overrides[get_db] = request_session
    client = TestClient(app)
    assert client.post('/api/commerce-migration/finance/preview', json=raw).status_code == 403
    assert client.post('/api/commerce-migration/finance/batches', json=raw).status_code == 403
    user['permissions'] = ['commerce_migration:admin']
    seed_authority(db, int(user['sub']), 'commerce_migration:admin')
    preview = client.post('/api/commerce-migration/finance/preview', json=raw)
    assert preview.status_code == 200 and preview.json()['data']['can_apply'], preview.text
    applied = client.post('/api/commerce-migration/finance/batches', json=raw)
    assert applied.status_code == 200, applied.text
    assert client.post('/api/commerce-migration/finance/batches', json=raw).json()['data'] == applied.json()['data']
