"""Actual native commands cannot escape physical or bank route ownership."""
from decimal import Decimal
from datetime import date
import pytest
from sqlalchemy import select
from app.commerce_transition import service as gates
from app.commerce_transition.models import BankIdentity, PlatformPolicy
from app.finance import service as finance_service
from app.finance.transition_identity import reserve
from app.invoice.settlement_models import ReceiptBatch
from app.inventory.models import StockLedger
from app.inventory.service import post_document
from app.receipt.models import Receipt
from tests.test_finance_local import finance, payment, cmd
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock, command


def test_transition_stock_requires_exclusive_bucket_even_with_native_writer(db, stock):
    sku, (warehouse, other) = stock
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    with pytest.raises(ValueError, match='排他'):
        post_document(db, command('missing-scope', 'receipt', warehouse, sku, 3), actor_id=None)
    assert db.scalar(select(StockLedger.id)) is None
    gates.register_resource_scope(db, route='local', resource_kind='sku', resource_key=str(sku.id),
        warehouse_key=str(warehouse.id), evidence={'checkpoint': 'test-count',
            'old_responsibilities_cleared': True, 'writers_enforced': True})
    post_document(db, command('owned', 'receipt', warehouse, sku, 3), actor_id=None)
    with pytest.raises(ValueError, match='排他'):
        post_document(db, command('wrong-warehouse', 'receipt', other, sku, 3), actor_id=None)
    with pytest.raises(ValueError, match='不归'):
        gates.require_resource_scope(db, 'legacy', 'sku', str(sku.id), str(warehouse.id))
    assert len(db.scalars(select(StockLedger)).all()) == 1


def test_weak_old_money_freezes_account_domain_after_complete_checkbox(db, finance):
    customer, user, bank = finance
    from app.invoice.models import Invoice
    invoice = Invoice(invoice_no='OLD-INVOICE', customer_id='old-customer', customer_name='Old buyer',
        invoice_date=date(2026, 10, 3), created_by=int(user['sub']), transaction_mode='legacy')
    db.add(invoice)
    db.flush()
    row = Receipt(receipt_no='OLD-WEAK', source='manual', invoice_id=invoice.id, customer_id='old-customer',
        request_key='old-weak', request_hash='x' * 64, amount=Decimal('600'), bank_charge=0,
        currency='USD', collection_date=date(2026, 10, 3), payment_type='bank_transfer',
        collect_status=1, sync_status='synced', created_by=int(user['sub']))
    db.add(row)
    db.flush()
    with pytest.raises(ValueError, match='账户身份不明'):
        finance_service.register(db, payment(customer, bank), user)
    assert db.scalar(select(ReceiptBatch.id)) is None
    assert db.scalar(select(BankIdentity.id)) is None


def test_confirmed_bank_principal_and_refund_never_release_on_replay(db, finance):
    customer, user, bank = finance
    row = finance_service.register(db, payment(customer, bank), user)
    finance_service.confirm(db, row.id, cmd('confirm', 1), user)
    with pytest.raises(ValueError, match='仅未确认'):
        finance_service.void_registration(db, row.id, cmd('void-confirmed', 2), user)
    finance_service.refund(db, row.id, cmd('refund', 2, amount=1000, bank_reference='BANK-REFUND'), user)
    with pytest.raises(ValueError, match='流水'):
        finance_service.register(db, payment(customer, bank, 'second-principal', bank_reference='BANK-REFUND'), user)
    assert row.refunded_amount == Decimal('1000')
    identities = db.scalars(select(BankIdentity).order_by(BankIdentity.id)).all()
    assert len(identities) == 2
    assert identities[0].payment_ref == f'local:{row.id}'
    assert identities[1].payment_ref.startswith('local-refund:')


def test_voided_registration_replay_keeps_released_reservation_audit(db, finance):
    customer, user, bank = finance
    row = finance_service.register(db, payment(customer, bank), user)
    body = cmd('void', 1)
    finance_service.void_registration(db, row.id, body, user)
    assert finance_service.void_registration(db, row.id, body, user).id == row.id
    identity = db.scalar(select(BankIdentity))
    assert identity.payment_ref is None
    assert identity.payer_evidence['voided_registration_history'][0]['payment_ref'] == f'local:{row.id}'
    corrected = finance_service.register(db, payment(customer, bank, 'corrected', gross_amount=900), user)
    assert db.scalar(select(BankIdentity)).id == identity.id
    assert identity.payment_ref == f'local:{corrected.id}'
    assert identity.payer_evidence['voided_registration_history'][0]['amount'] == '1000.00'


def test_known_old_bank_account_cannot_reconcile_into_another_domain(db, finance):
    from app.finance.models import BankAccount
    from app.finance.transition_identity import reconcile_legacy_identity
    from app.core.config import get_settings
    customer, user, bank = finance
    policy = db.get(PlatformPolicy, 1)
    gates.set_policy(db, phase='transition', expected_version=policy.version)
    other = BankAccount(code='SECOND-ALIAS', name='A different real bank account', currency='USD')
    db.add(other)
    db.flush()
    settings = get_settings()
    wrong = gates.register_bank_domain(db, subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY,
        account_key='different-real-settlement-account', channel=settings.COMMERCE_BANK_CHANNEL,
        legacy_identity_complete=True, enforced=True, bank_account_ids=[other.id],
        evidence={'statement_checkpoint': 'known separate account'})
    batch = ReceiptBatch(batch_no='OLD-BATCH', customer_id='old-customer', currency='USD', gross_amount=600,
        transaction_mode='legacy', bank_account_id=bank.id, collection_date=date(2026, 10, 3),
        payment_type='bank_transfer', request_key='old-batch', request_hash='a' * 64, created_by=int(user['sub']))
    db.add(batch)
    db.flush()
    with pytest.raises(ValueError, match='已知银行账户'):
        reconcile_legacy_identity(db, domain_id=wrong.id, transaction_id='BANK-EXISTING', batch_id=batch.id,
            statement_reference='Real original statement reference', actor_id=int(user['sub']))
    assert db.scalar(select(BankIdentity.id)) is None
    with pytest.raises(ValueError, match='多个真实结算账户域'):
        gates.register_bank_domain(db, subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY,
            account_key='arbitrary-second-alias', channel=settings.COMMERCE_BANK_CHANNEL,
            legacy_identity_complete=True, enforced=True, bank_account_ids=[bank.id],
            evidence={'attempt': 'alias cannot split canonical account domain'})
