"""Actual old cash evidence fences both new and already-confirmed native money."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from pydantic import ValidationError
from app.commerce_transition import service as gates
from app.commerce_transition.models import BankAccountDomain, BankIdentity, PlatformPolicy
from app.commerce_transition.schemas import LegacyBankReconciliation
from app.finance import service as finance_service
from app.finance.models import FinanceEvent
from app.finance.transition_identity import reconcile_legacy_identity, unmapped_legacy_money
from app.invoice.settlement_models import ReceiptBatch
from app.sales_return import service, schemas
from app.sales_return.models import ReturnReceipt
from tests.test_finance_local import finance, payment, cmd
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock
from tests.test_sales_return_service import env, activate, USER, count
from tests.test_commerce_transition_http import client_for


@pytest.fixture
def cash_case(db, finance, env):
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    row, _ = activate(db)
    return row, finance


def move(db, row, status):
    return service.cash(db, row.id, schemas.Cash(version=row.version, status=status,
        evidence=f'Actual bank statement evidence for {status}'), USER)


def reconcile(db, row, movement='paid', transaction='OLD-PAID'):
    return reconcile_legacy_identity(db, domain_id=db.scalar(select(BankAccountDomain.id)),
        transaction_id=transaction, sales_return_id=row.id, cash_movement=movement,
        statement_reference='Reviewed original bank statement', actor_id=7)


def test_intended_refund_is_not_actual_cash_and_cannot_be_reconciled(db, cash_case):
    row, (customer, user, bank) = cash_case
    assert count(db, ReturnReceipt) == 1 and unmapped_legacy_money(db) == []
    with pytest.raises(ValueError, match='实际支付'):
        reconcile(db, row)
    finance_service.register(db, payment(customer, bank), user)
    assert count(db, ReceiptBatch) == count(db, BankIdentity) == 1


def test_paid_cash_freezes_existing_local_cash_until_historical_identity_reconciled(db, cash_case):
    row, (customer, user, bank) = cash_case
    local = finance_service.register(db, payment(customer, bank), user)
    finance_service.confirm(db, local.id, cmd('confirm', 1), user)
    move(db, row, 'paid')
    assert unmapped_legacy_money(db) == [f'legacy-return-paid:{row.id}']
    with pytest.raises(ValueError, match='账户身份不明'):
        finance_service.register(db, payment(customer, bank, 'later', bank_reference='NEW'), user)
    with pytest.raises(ValueError, match='账户身份不明'):
        finance_service.refund(db, local.id, cmd('blocked', 2, amount=10, bank_reference='LOCAL-REFUND'), user)
    before = [count(db, model) for model in (ReceiptBatch, FinanceEvent, ReturnReceipt)]
    identity = reconcile(db, row)
    assert identity.amount == Decimal('600') and identity.currency == 'USD'
    assert identity.payment_ref == f'legacy-return-paid:{row.id}'
    assert identity.payer_evidence['original_cash_evidence'] == row.cash_evidence[0]
    assert reconcile(db, row).id == identity.id
    assert before == [count(db, model) for model in (ReceiptBatch, FinanceEvent, ReturnReceipt)]
    assert unmapped_legacy_money(db) == []
    finance_service.refund(db, local.id, cmd('resumed', 2, amount=10, bank_reference='LOCAL-REFUND'), user)
    assert local.refunded_amount == Decimal('10')
    with pytest.raises(ValueError, match='不归'):
        gates.claim_bank_identity(db, domain_id=identity.domain_id, transaction_id='NEW-LEGACY',
            route='legacy', currency='USD', amount=600, payer_evidence={'bank_identity_verified': True})


def test_recovery_requires_two_distinct_permanent_bank_movements(db, cash_case):
    row, (customer, user, bank) = cash_case
    move(db, row, 'paid')
    move(db, row, 'recovered')
    assert unmapped_legacy_money(db) == [f'legacy-return-paid:{row.id}', f'legacy-return-recovered:{row.id}']
    paid = reconcile(db, row)
    with pytest.raises(ValueError, match='第二份'):
        reconcile(db, row, 'recovered', 'OLD-PAID')
    assert unmapped_legacy_money(db) == [f'legacy-return-recovered:{row.id}']
    recovered = reconcile(db, row, 'recovered', 'OLD-RECOVERED')
    assert paid.id != recovered.id and count(db, BankIdentity) == 2
    with pytest.raises(ValueError, match='跨线'):
        finance_service.register(db, payment(customer, bank, gross_amount=600, bank_reference='OLD-RECOVERED'), user)
    assert count(db, ReceiptBatch) == 0
    policy = db.get(PlatformPolicy, 1)
    with pytest.raises(ValueError, match='尚未核清'):
        gates.set_policy(db, phase='local_only', expected_version=policy.version)


def test_existing_native_bank_transaction_cannot_be_reclassified_as_old_refund(db, cash_case):
    row, (customer, user, bank) = cash_case
    finance_service.register(db, payment(customer, bank, gross_amount=600), user)
    move(db, row, 'paid')
    with pytest.raises(ValueError, match='跨线'):
        reconcile(db, row, transaction='BANK-1')
    assert count(db, BankIdentity) == 1
    assert unmapped_legacy_money(db) == [f'legacy-return-paid:{row.id}']


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'zero'])
def test_status_without_valid_actual_cash_evidence_never_authorizes_identity(db, cash_case, damage):
    row, _ = cash_case
    move(db, row, 'paid')
    if damage == 'missing':
        row.cash_evidence = []
    elif damage == 'duplicate':
        row.cash_evidence = row.cash_evidence * 2
    else:
        row.refund_amount = 0
    db.flush()
    with pytest.raises(ValueError, match='实际支付'):
        reconcile(db, row)
    assert count(db, BankIdentity) == 0
    assert unmapped_legacy_money(db) == [f'legacy-return-paid:{row.id}']


def test_return_reconciliation_requires_current_return_admin(db, cash_case):
    row, _ = cash_case
    move(db, row, 'paid')
    domain_id, return_id = db.scalar(select(BankAccountDomain.id)), row.id
    client, _ = client_for(db, ['commerce_transition:admin', 'receipt:admin'],
        stale_permissions=['commerce_transition:admin', 'receipt:admin', 'sales_return:admin'])
    response = client.post('/api/commerce-transition/bank-identities/reconcile-legacy', json={
        'domain_id':domain_id, 'transaction_id':'OLD-PAID', 'sales_return_id':return_id,
        'cash_movement':'paid', 'statement_reference':'Bank statement reviewed'})
    assert response.status_code == 403
    assert count(db, BankIdentity) == 0


@pytest.mark.parametrize('source', [{}, {'receipt_id':1,'batch_id':2}, {'sales_return_id':1},
    {'receipt_id':1,'cash_movement':'paid'}, {'sales_return_id':1,'cash_movement':'not_paid'}])
def test_reconciliation_payload_rejects_ambiguous_cash_source(source):
    with pytest.raises(ValidationError):
        LegacyBankReconciliation(domain_id=1,transaction_id='TX',statement_reference='Statement',**source)


def test_reversed_return_keeps_both_actual_cash_reservations(db, cash_case):
    row, _ = cash_case
    move(db, row, 'paid')
    move(db, row, 'recovered')
    service.reverse(db, row.id, schemas.Reverse(version=row.version,
        request_key='reverse-cash-bank-case', reason='Correction after actual money recovery'), USER)
    assert row.status == 'reversed'
    assert unmapped_legacy_money(db) == [f'legacy-return-paid:{row.id}', f'legacy-return-recovered:{row.id}']
    reconcile(db, row)
    reconcile(db, row, 'recovered', 'OLD-RECOVERED')
    assert unmapped_legacy_money(db) == []


def test_return_bank_http_reconciliation_preserves_cash_and_permission_contract(db, cash_case):
    row, _ = cash_case
    move(db, row, 'paid')
    domain_id, return_id = db.scalar(select(BankAccountDomain.id)), row.id
    client, _ = client_for(db, [], role_name='super_admin')
    response = client.post('/api/commerce-transition/bank-identities/reconcile-legacy', json={
        'domain_id':domain_id, 'transaction_id':'HTTP-OLD-PAID', 'sales_return_id':return_id,
        'cash_movement':'paid', 'statement_reference':'Bank statement reviewed'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['payment_ref'] == f'legacy-return-paid:{return_id}'
    assert count(db, ReceiptBatch) == 0 and count(db, ReturnReceipt) == 1
