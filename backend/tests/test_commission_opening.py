"""Historical paid commissions remain consumed; only new reversals project."""
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.commission.models import CommissionBasis, CommissionEventProjection
from app.commission.opening_service import bind_paid_history
from app.commission.projection_service import sync_events
from app.commission.service import resolve
from app.commerce_migration.finance_schemas import HistoricalReversal
from app.finance import service as finance_service
from app.finance.models import FinanceEvent
from app.finance.query_service import reconcile
from app.invoice.settlement_models import ReceiptBatch
from app.models.commission import CommissionBatch, CommissionDetail, PaymentCommissionStatus, SyncedPayment
from app.receipt.models import Receipt
from app.services.commission_calculator import calculate_commission
from tests.test_finance_local import finance, stock, buyer, order, cmd
from tests.test_commission_local import batch

DAY = date(2026, 10, 3)


@pytest.mark.parametrize('prior_amount', [None, Decimal('117')])
def test_preopening_native_null_rmb_metadata_preserves_paid_cents(db, finance, stock, buyer, prior_amount):
    from tests.test_commission_local import snapshot, allocate
    from app.finance.models import Currency
    from app.commission.projection_service import _projected_rmb
    from app.commission.service import ROLES
    db.get(Currency, 'USD').rate_to_cny = Decimal('6.5')
    snapshot(db, finance[0], finance[1])
    receipt, basis = allocate(db, finance, stock, buyer, '350.50')
    sync_events(db, DAY)
    if prior_amount:
        finance_service.reverse_allocation(db, receipt.id, cmd('old-native-reverse', receipt.version, amount=prior_amount), finance[1])
        sync_events(db, DAY)
    old_rows = db.scalars(select(CommissionEventProjection)).all()
    old_ids = {row.event_id for row in old_rows}
    for row in old_rows:
        for role in ROLES:
            setattr(row, f'{role}_commission_rmb', None)
    db.commit()
    old_rmb = sum((_projected_rmb(row, db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == row.payment_id)),
        'salesperson') for row in old_rows), Decimal(0))
    assert old_rmb == (Decimal('30.35') if prior_amount else Decimal('45.56'))
    if prior_amount:
        finance_service.reverse_allocation(db, receipt.id, cmd('tiny-new-native-reverse', receipt.version, amount=Decimal('.01')), finance[1])
        assert sync_events(db, DAY) == 1
        tiny = db.scalar(select(CommissionEventProjection).where(CommissionEventProjection.event_id.not_in(old_ids)))
        assert tiny.salesperson_commission == 0 and tiny.salesperson_commission_rmb == 0
    finance_service.reverse_allocation(db, receipt.id, cmd('new-native-reverse', receipt.version), finance[1])
    assert sync_events(db, DAY) == 1
    db.commit(); db.expire_all()
    new_rows = [row for row in db.scalars(select(CommissionEventProjection)) if row.event_id not in old_ids]
    assert sum((row.salesperson_commission_rmb for row in new_rows), Decimal(0)) == -old_rmb
    assert sum(db.scalars(select(CommissionEventProjection.salesperson_commission))) == 0
    assert all(row.salesperson_commission_rmb is None for row in db.scalars(select(CommissionEventProjection).where(
        CommissionEventProjection.event_id.in_(old_ids))))
    assert basis.snapshot['salesperson_original_commission'] == '7.01'
    assert sync_events(db, DAY) == 0


def historical(db, finance, stock, buyer, *, rate=Decimal('7')):
    customer, user, bank = finance
    invoice, target = order(db, stock, buyer)
    invoice.xiaoman_order_id = 'OLD-ORDER'
    invoice.internal_received, invoice.internal_balance = Decimal('400'), Decimal('600')
    target.paid_amount = Decimal('400')
    cash = ReceiptBatch(batch_no='OLD-CASH', customer_id=f'ark:{customer.id}', local_customer_id=customer.id,
        transaction_mode='local', currency='USD', gross_amount=600, allocated_amount=400, refunded_amount=200,
        actual_bank_fee=0, net_amount=600, bank_charge_total=0, bank_account_id=bank.id, bank_reference='HIST-BANK',
        finance_status='confirmed', rate_to_cny=rate, rate_to_usd=1, collection_date=DAY,
        confirmed_date=DAY, payment_type='bank_transfer', request_key='opening-cash', request_hash='a'*64, created_by=int(user['sub']))
    db.add(cash); db.flush()
    receipt = Receipt(receipt_no='OLD-RECEIPT', invoice_id=invoice.id, batch_id=cash.id, receivable_id=target.id,
        purpose='ordinary', source='local', request_key='opening-receipt', request_hash='b'*64,
        amount=600, bank_charge=0, reversed_amount=200, reversed_bank_charge=0, currency='USD', collection_date=DAY,
        payment_type='bank_transfer', customer_id=f'ark:{customer.id}', xiaoman_receipt_id='OLD-PAYMENT',
        xiaoman_order_id='OLD-ORDER', collect_status=1, sync_status='not_applicable', created_by=int(user['sub']))
    db.add(receipt); db.flush()
    event = FinanceEvent(request_key='opening-event', request_hash='c'*64, action='opening_allocation',
        batch_id=cash.id, receipt_id=receipt.id, receivable_id=target.id, business_date=DAY,
        amount=400, commission_amount_usd=400, created_by=int(user['sub']),
        payload={'opening': {'reversed_amount': '200.00', 'reversed_bank_charge': '0.00'}})
    db.add_all([event, FinanceEvent(request_key='opening-refund', request_hash='d'*64, action='opening_refund',
        batch_id=cash.id, business_date=DAY, amount=-200, created_by=int(user['sub']), payload={})])
    old_batch = CommissionBatch(batch_name='Historical paid', period_start=DAY, period_end=DAY, status='confirmed')
    db.add(old_batch); db.flush()
    for identity, gross, rmb, commission in [('OLD-PAYMENT', 600, finance_service.money(600*rate), '7.01'), ('OLD-REFUND', -200, finance_service.money(-200*rate), '-2.34')]:
        db.add_all([SyncedPayment(payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
            payment_date=DAY, payment_amount=gross, service_fee=0, exchange_rate=rate*100, real_amount_rmb=rmb),
            CommissionDetail(batch_id=old_batch.id, payment_id=identity, order_id='OLD-ORDER', customer_id='OLD-CUSTOMER',
                payment_amount=gross, salesperson_id='old-salesperson', salesperson_rate=Decimal('.02'),
                salesperson_commission=Decimal(commission), status='paid'),
            PaymentCommissionStatus(payment_id=identity, batch_id=old_batch.id)])
    db.flush()
    basis = bind_paid_history(db, event, receipt, source_customer_id='OLD-CUSTOMER', payment_id='OLD-PAYMENT',
        prior_reversals=[HistoricalReversal(payment_id='OLD-REFUND', amount=200, bank_charge=0, rate_to_usd=1, rate_to_cny=rate, business_date=DAY)], actor_id=int(user['sub']))
    return invoice, target, cash, receipt, event, basis, old_batch


@pytest.mark.parametrize('parts', [[400], [Decimal('133.33'), Decimal('133.33'), Decimal('133.34')]])
@pytest.mark.parametrize('rate', [Decimal('6.5'), Decimal('7.12345678')])
def test_historical_rmb_tail_is_preserved_in_personal_summary_and_exports(db, finance, stock, buyer, parts, rate):
    from app.api.commission import _detail_schema_from_row, _build_sales_summary, _build_monthly_summary
    from app.commission.query_service import detail_rows
    _, _, _, receipt, _, basis, _ = historical(db, finance, stock, buyer, rate=rate)
    expected_rmb = -(Decimal(str(round(7.01*float(rate), 2))) + Decimal(str(round(-2.34*float(rate), 2))))
    for index, amount in enumerate(parts):
        finance_service.reverse_allocation(db, receipt.id, cmd(f'rmb-reverse-{index}', receipt.version, amount=amount), finance[1])
    new_batch = batch(db, 'RMB cents')
    calculate_commission(db, new_batch.id)
    db.commit(); db.expire_all()
    rows = detail_rows(db, new_batch.id)
    assert sum(Decimal(str(_detail_schema_from_row(row).salesperson_commission_rmb)) for row in rows) == expected_rmb
    assert Decimal(str(_build_sales_summary(rows, ['old-salesperson']).total_commission_rmb)) == expected_rmb
    assert Decimal(str(_build_monthly_summary(rows, ['old-salesperson'])[0].total_commission_rmb)) == expected_rmb
    assert Decimal(db.scalar(select(CommissionBasis).where(CommissionBasis.id == basis.id)).snapshot['opening_exchange_rate']) == rate
    assert {payment.exchange_rate for payment in db.scalars(select(SyncedPayment).where(SyncedPayment.payment_id.like('ark-finance:%')))} == {rate}


def test_historical_income_never_reprojects_and_future_refunds_use_remaining_cents(db, finance, stock, buyer):
    _, _, cash, receipt, event, basis, _ = historical(db, finance, stock, buyer)
    _, user, _ = finance
    assert sync_events(db, DAY) == 0
    assert not db.scalars(select(CommissionEventProjection)).all()
    assert len(db.scalars(select(SyncedPayment)).all()) == 2
    assert basis.snapshot['salesperson_original_commission'] == '4.67'
    assert reconcile(db, user)['differences'] == []
    finance_service.reverse_allocation(db, receipt.id, cmd('new-reversal-1', receipt.version, amount=200), user)
    first = calculate_commission(db, batch(db, 'New first').id)
    assert first.total_payments == 1 and first.total_salesperson_commission == Decimal('-2.34')
    finance_service.reverse_allocation(db, receipt.id, cmd('new-reversal-2', receipt.version, amount=200), user)
    second = calculate_commission(db, batch(db, 'New second').id)
    assert second.total_payments == 1 and second.total_salesperson_commission == Decimal('-2.33')
    assert calculate_commission(db, batch(db, 'Retry').id).total_payments == 0
    assert receipt.reversed_amount == 600 and cash.allocated_amount == 0
    assert reconcile(db, user)['differences'] == []
    assert db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == f'ark-finance:{event.id}')) is None
    assert db.scalar(select(CommissionDetail.salesperson_commission).where(CommissionDetail.payment_id == 'OLD-PAYMENT')) == Decimal('7.01')


def test_unconfirmed_historical_batch_blocks_new_negative_consumption(db, finance, stock, buyer):
    _, _, _, receipt, _, _, old_batch = historical(db, finance, stock, buyer)
    _, user, _ = finance
    finance_service.reverse_allocation(db, receipt.id, cmd('new-reversal', receipt.version, amount=100), user)
    old_batch.status = 'calculated'
    result = calculate_commission(db, batch(db, 'Waiting').id)
    assert result.total_payments == 0 and result.skipped_dependency == 1


def test_unrelated_pending_basis_does_not_block_opening_and_frozen_opening_cannot_resolve(db, finance, stock, buyer):
    db.add(FinanceEvent(request_key='unrelated', request_hash='e'*64, action='allocate', business_date=DAY,
        created_by=int(finance[1]['sub']), payload={}))
    db.flush()
    other_event = db.scalar(select(FinanceEvent).where(FinanceEvent.request_key == 'unrelated'))
    db.add(CommissionBasis(event_id=other_event.id, customer_id='ark:other', snapshot=None, pending_reason='Missing snapshot'))
    db.flush()
    _, _, _, _, _, basis, _ = historical(db, finance, stock, buyer)
    with pytest.raises(ValueError, match='冻结'):
        resolve(db, basis.id, 999, 'Cannot rewrite history', finance[1])


@pytest.mark.parametrize('mutation', ['missing_status', 'wrong_order', 'positive_adjustment', 'beneficiary_drift', 'duplicate_consumption', 'missing_beneficiary', 'fx_drift'])
def test_historical_binding_rejects_missing_or_inconsistent_proof(db, finance, stock, buyer, mutation):
    _, _, cash, receipt, event, basis, _ = historical(db, finance, stock, buyer)
    if mutation != 'duplicate_consumption':
        db.delete(basis); db.flush()
    if mutation == 'missing_status':
        db.delete(db.scalar(select(PaymentCommissionStatus).where(PaymentCommissionStatus.payment_id == 'OLD-PAYMENT')))
    elif mutation == 'wrong_order':
        db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == 'OLD-PAYMENT')).order_id = 'OTHER'
    elif mutation == 'positive_adjustment':
        db.scalar(select(SyncedPayment).where(SyncedPayment.payment_id == 'OLD-REFUND')).payment_amount = 200
    elif mutation == 'beneficiary_drift':
        db.scalar(select(CommissionDetail).where(CommissionDetail.payment_id == 'OLD-REFUND')).salesperson_id = 'OTHER'
    elif mutation == 'missing_beneficiary':
        db.scalar(select(CommissionDetail).where(CommissionDetail.payment_id == 'OLD-PAYMENT')).supervisor_commission = Decimal('1.00')
    elif mutation == 'fx_drift':
        cash.rate_to_cny = Decimal('8')
    db.flush()
    with pytest.raises(ValueError):
        bind_paid_history(db, event, receipt, source_customer_id='OLD-CUSTOMER', payment_id='OLD-PAYMENT',
            prior_reversals=[HistoricalReversal(payment_id='OLD-REFUND', amount=200, bank_charge=0, rate_to_usd=1, rate_to_cny=7, business_date=DAY)], actor_id=int(finance[1]['sub']))
