"""Local payments preserve cash, allocation and AR identities independently."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance.models import BankAccount, Currency, FinanceEvent
from app.finance.schemas import PaymentCreate, FinanceAction, AllocationCreate, AdjustmentCreate
from app.finance import service
from app.invoice.settlement_models import Receivable
from app.receipt.models import Receipt
from app.invoice.commerce_service import create_draft, confirm
from tests.test_invoice_commerce import buyer, draft, action
from tests.test_inventory_local import stock


@pytest.fixture
def finance(db, buyer):
    customer, user = buyer
    db.add_all([Currency(code="CNY", name="人民币", rate_to_cny=1),
                Currency(code="USD", name="美元", rate_to_cny=7)])
    account = BankAccount(code="USD-1", name="USD bank", currency="USD")
    db.add(account)
    db.flush()
    from app.commerce_transition.service import register_bank_domain
    from app.core.config import get_settings
    settings = get_settings()
    register_bank_domain(db, subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY,
        account_key=account.code, channel=settings.COMMERCE_BANK_CHANNEL,
        bank_account_ids=[account.id],
        legacy_identity_complete=True, enforced=True, exclusive_route='local',
        evidence={'isolated_fixture_empty_legacy_account': True})
    return customer, user, account


def payment(customer, account, key="pay", **changes):
    values = dict(request_key=key, local_customer_id=customer.id, bank_account_id=account.id,
                  bank_reference="BANK-1", currency="USD", gross_amount="1000", actual_bank_fee="20",
                  collection_date=date(2026, 10, 3), payment_type="bank_transfer", attachment_ids=[])
    values.update(changes)
    return PaymentCreate(**values)


def cmd(key, version, **values):
    return FinanceAction(request_key=key, expected_version=version, business_date=date(2026, 10, 3), reason="test", **values)


def order(db, stock, buyer):
    sku, _ = stock
    customer, user = buyer
    invoice = create_draft(db, draft(customer, user, sku, order_type="production", shipping_fee=0,
                          surcharge_amount=0, items=[dict(local_sku_id=sku.id, quantity=10, price_per_piece=100)]), user)
    confirm(db, invoice.id, action("confirm-order", 1), user)
    return invoice, db.scalar(select(Receivable).where(Receivable.invoice_id == invoice.id))


def test_unallocated_prepayment_confirmation_and_net_cash(db, finance):
    customer, user, account = finance
    batch = service.register(db, payment(customer, account), user)
    assert batch.finance_status == "registered"
    assert batch.net_amount == Decimal("980") and batch.allocated_amount == 0
    assert service.register(db, payment(customer, account), user).id == batch.id
    assert service.describe(db, batch, user)["available_amount"] == "0.00"
    service.confirm(db, batch.id, cmd("confirm-payment", 1), user)
    assert service.describe(db, batch, user)["available_amount"] == "1000.00"
    assert batch.rate_to_cny == 7 and batch.rate_to_usd == 1
    assert len(db.scalars(select(FinanceEvent)).all()) == 2


def test_partial_allocate_reverse_reallocate_and_refund(db, finance, stock, buyer):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    batch = service.register(db, payment(customer, account), user)
    service.confirm(db, batch.id, cmd("confirm-payment", 1), user)
    body = AllocationCreate(request_key="allocate", expected_version=2, receivable_id=target.id,
                            invoice_id=invoice.id, amount="400", business_date=date(2026, 10, 3))
    receipt = service.allocate(db, batch.id, body, user)
    assert service.allocate(db, batch.id, body, user).id == receipt.id
    assert target.paid_amount == 400 and batch.allocated_amount == 400
    assert receipt.collect_status == 1 and receipt.sync_status == "not_applicable"
    service.reverse_allocation(db, receipt.id, cmd("reverse", 1), user)
    assert target.paid_amount == 0 and batch.allocated_amount == 0
    receipt2 = service.allocate(db, batch.id, body.model_copy(update={"request_key": "reallocate", "expected_version": 4}), user)
    assert receipt2.id != receipt.id
    service.refund(db, batch.id, cmd("refund", 5, amount="600", bank_reference="REFUND-1"), user)
    assert batch.refunded_amount == 600 and service.describe(db, batch, user)["available_amount"] == "0.00"
    with pytest.raises(ValueError, match="可退"):
        service.refund(db, batch.id, cmd("excess-refund", 6, amount="0.01", bank_reference="REFUND-2"), user)


def test_registration_is_not_credit_and_same_bank_reference_is_unique(db, finance, stock, buyer):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    batch = service.register(db, payment(customer, account), user)
    with pytest.raises(ValueError, match="确认"):
        service.allocate(db, batch.id, AllocationCreate(request_key="early", expected_version=1,
            invoice_id=invoice.id, receivable_id=target.id, amount=10, business_date=date(2026, 10, 3)), user)
    with pytest.raises(ValueError, match="流水"):
        service.register(db, payment(customer, account, key="duplicate"), user)
    assert not db.scalars(select(Receipt)).all()


def test_credit_note_cannot_hide_allocated_funds_or_exceed_ar(db, finance, stock, buyer):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    adjust = AdjustmentCreate(request_key="credit", expected_version=1, invoice_id=invoice.id,
        amount="-100", business_date=date(2026, 10, 3), reason="Approved return")
    service.adjust_receivable(db, target.id, adjust, user)
    assert target.adjustment_amount == -100
    batch = service.register(db, payment(customer, account), user)
    service.confirm(db, batch.id, cmd("confirm-payment", 1), user)
    service.allocate(db, batch.id, AllocationCreate(request_key="allocate", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount=900, business_date=date(2026, 10, 3)), user)
    with pytest.raises(ValueError, match="已核销"):
        service.adjust_receivable(db, target.id, adjust.model_copy(update={"request_key": "too-far", "expected_version": target.version}), user)
    assert target.adjustment_amount == -100 and target.paid_amount == 900


def test_bank_reference_is_shared_by_receipts_and_refunds_and_void_can_correct(db, finance):
    customer, user, account = finance
    row = service.register(db, payment(customer, account), user)
    service.void_registration(db, row.id, cmd("void", 1), user)
    assert row.bank_reference is None
    original = db.scalar(select(FinanceEvent).where(FinanceEvent.action == "register"))
    assert original.payload["body"]["bank_reference"] == "BANK-1"
    corrected = service.register(db, payment(customer, account, "correction", gross_amount=900), user)
    service.confirm(db, corrected.id, cmd("confirm-corrected", 1), user)
    with pytest.raises(ValueError, match="流水"):
        service.refund(db, corrected.id, cmd("duplicate-direction", 2, amount=10, bank_reference="BANK-1"), user)
    service.refund(db, corrected.id, cmd("valid-refund", 2, amount=10, bank_reference="REFUND1"), user)
    with pytest.raises(ValueError, match="流水"):
        service.register(db, payment(customer, account, "refund-as-payment", bank_reference="REFUND1"), user)
    assert corrected.refunded_amount == 10


def test_cannot_backdate_allocation_or_refund_before_confirmation(db, finance, stock, buyer):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    invoice.invoice_date = date(2026, 10, 1)
    batch = service.register(db, payment(customer, account, collection_date=date(2026, 10, 1)), user)
    service.confirm(db, batch.id, cmd("confirm", 1), user)
    with pytest.raises(ValueError, match="确认"):
        service.allocate(db, batch.id, AllocationCreate(request_key="backdate", expected_version=2,
            invoice_id=invoice.id, receivable_id=target.id, amount=100, business_date=date(2026, 10, 2)), user)
    with pytest.raises(ValueError, match="确认"):
        service.refund(db, batch.id, cmd("back-refund", 2, amount=100, bank_reference="REF1").model_copy(
            update={"business_date": date(2026, 10, 2)}), user)
    assert batch.allocated_amount == 0 and batch.refunded_amount == 0


def test_closed_period_and_idempotent_replay(db, finance):
    from app.finance.reference_service import close_period
    customer, user, account = finance
    body = payment(customer, account, collection_date=date(2026, 10, 1))
    batch = service.register(db, body, user)
    close_period(db, cmd("close", 1).model_copy(update={"business_date": date(2026, 10, 2)}), user)
    assert service.register(db, body, user).id == batch.id
    with pytest.raises(ValueError, match="结账"):
        service.register(db, payment(customer, account, "closed", bank_reference="BANK2", collection_date=date(2026, 10, 2)), user)
    service.confirm(db, batch.id, cmd("confirm", 1), user)
    assert batch.finance_status == "confirmed"


def test_fee_allocation_uses_frozen_fx_and_reversal_exactly_negates(db, finance, stock, buyer):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    target.handling_amount = 30
    batch = service.register(db, payment(customer, account), user)
    service.confirm(db, batch.id, cmd("confirm", 1), user)
    db.get(Currency, "USD").rate_to_cny = 8
    body = AllocationCreate(request_key="allocate", expected_version=2, receivable_id=target.id,
                            invoice_id=invoice.id, amount=1000, business_date=date(2026, 10, 3))
    row = service.allocate(db, batch.id, body, user)
    assert row.bank_charge == 30 and batch.actual_bank_fee == 20 and batch.rate_to_cny == 7
    assert db.scalar(select(FinanceEvent.commission_amount_usd).where(FinanceEvent.action == "allocate")) == 970
    service.reverse_allocation(db, row.id, cmd("reverse", 1), user)
    assert sum(db.scalars(select(FinanceEvent.commission_amount_usd))) == 0


def test_due_date_aging_and_reconciliation_detect_projection_drift(db, finance, stock, buyer, monkeypatch):
    from app.finance import query_service
    from app.finance.schemas import ReceivableTerms
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    batch = service.register(db, payment(customer, account), user)
    service.confirm(db, batch.id, cmd("confirm", 1), user)
    service.allocate(db, batch.id, AllocationCreate(request_key="allocate", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount=400, business_date=date(2026, 10, 3)), user)
    assert query_service.aging(db, user)["by_currency"]["USD"]["undated"] == "600.00"
    service.set_due_date(db, target.id, ReceivableTerms(request_key="due", expected_version=target.version,
        invoice_id=invoice.id, due_date=date(2026, 10, 3), business_date=date(2026, 10, 3), reason="Agreed terms"), user)
    monkeypatch.setattr(query_service, "beijing_today", lambda: date(2026, 11, 3))
    assert query_service.aging(db, user)["by_currency"]["USD"]["31_60"] == "600.00"
    assert query_service.reconcile(db, user)["differences"] == []
    target.paid_amount = 401
    batch.refunded_amount = 1
    db.flush()
    mismatches = query_service.reconcile(db, user)["differences"]
    assert {x["field"] for x in mismatches} == {"paid_amount", "refunded_amount"}


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-02T15:59:59+00:00", "2026-10-02T23:59:59"),
    ("2026-10-02T16:00:00+00:00", "2026-10-03T00:00:00"),
])
def test_payment_audit_uses_beijing_at_midnight(db, finance, monkeypatch, instant, expected):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.core import time as business_time
    fixed = datetime.fromisoformat(instant)
    class ServerDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz or ZoneInfo("America/New_York"))
    monkeypatch.setattr(business_time, "datetime", ServerDateTime)
    customer, user, account = finance
    day = date.fromisoformat(expected[:10])
    batch = service.register(db, payment(customer, account, collection_date=day), user)
    service.confirm(db, batch.id, cmd("confirm", 1).model_copy(update={"business_date": day}), user)
    assert batch.created_at.isoformat() == expected and batch.confirmed_at.isoformat() == expected
    assert all(event.created_at.isoformat() == expected for event in db.scalars(select(FinanceEvent)))
