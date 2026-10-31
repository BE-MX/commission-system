"""Partial reversals conserve original faces, occupied components and USD cents."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance import service, query_service
from app.finance.models import FinanceEvent
from app.finance.schemas import AllocationCreate
from app.invoice import local_funding
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement
from tests.test_finance_local import finance, payment, cmd, order
from tests.test_invoice_commerce import buyer
from tests.test_inventory_local import stock


def allocated(db, finance, stock, buyer, *, amount="100", fee="100", rate="1"):
    customer, user, account = finance
    invoice, target = order(db, stock, buyer)
    # These tests exercise ordinary free allocations rather than presale plans.
    invoice.order_type = "stock"
    target.handling_amount = Decimal(fee)
    batch = service.register(db, payment(customer, account), user)
    batch.rate_to_usd = Decimal(rate)
    service.confirm(db, batch.id, cmd("confirm", 1), user)
    receipt = service.allocate(db, batch.id, AllocationCreate(request_key="allocate", expected_version=2,
        invoice_id=invoice.id, receivable_id=target.id, amount=amount, business_date=date(2026, 10, 3)), user)
    return invoice, target, batch, receipt, user


def test_partial_then_all_preserves_faces_replay_and_reconciliation(db, finance, stock, buyer):
    invoice, target, batch, row, user = allocated(db, finance, stock, buyer)
    first = cmd("partial", row.version, amount=40)
    service.reverse_allocation(db, row.id, first, user)
    assert (row.amount, row.bank_charge) == (100, 10)
    assert (row.reversed_amount, row.reversed_bank_charge) == (40, 4)
    assert (row.effective_amount, row.effective_bank_charge, row.status) == (60, 6, "active")
    assert target.paid_amount == batch.allocated_amount == invoice.internal_received == 60
    assert batch.bank_charge_total == 6
    version = row.version
    service.reverse_allocation(db, row.id, first, user)
    assert row.version == version
    with pytest.raises(ValueError, match="剩余"):
        service.reverse_allocation(db, row.id, cmd("excess", version, amount=61), user)
    assert row.reversed_amount == 40
    assert not db.scalar(select(FinanceEvent.id).where(FinanceEvent.request_key == "excess"))
    assert query_service.reconcile(db, user)["differences"] == []
    service.reverse_allocation(db, row.id, cmd("rest", version), user)
    assert (row.amount, row.bank_charge, row.reversed_amount, row.reversed_bank_charge) == (100, 10, 100, 10)
    assert row.status == "reversed" and row.collect_status == 0
    assert target.paid_amount == batch.allocated_amount == batch.bank_charge_total == 0
    assert query_service.reconcile(db, user)["differences"] == []


def test_three_small_reversals_exactly_negate_frozen_usd_event(db, finance, stock, buyer):
    _, _, batch, row, user = allocated(db, finance, stock, buyer, amount="0.03", fee="0", rate="0.5")
    original = db.scalar(select(FinanceEvent).where(FinanceEvent.action == "allocate"))
    assert original.commission_amount_usd == Decimal("0.02")
    # Subsequent reference-rate changes cannot change the stored event basis.
    batch.rate_to_usd = Decimal("2")
    for index in range(3):
        service.reverse_allocation(db, row.id, cmd(f"part-{index}", row.version, amount="0.01"), user)
    events = db.scalars(select(FinanceEvent).where(FinanceEvent.receipt_id == row.id)).all()
    assert sum(event.commission_amount_usd for event in events) == 0
    assert sum(event.amount for event in events) == 0
    assert row.reversed_amount == Decimal("0.03")


def occupy(db, invoice, receipt, *, amount, fee):
    quote = dict(goods_payment_due=str(amount), goods_payment_charge=str(fee), freight_amount="0",
                 deposit_applied="0", deposit_charge_applied="0")
    settlement = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="TEST-1", state="ready",
        is_final=0, quote=quote, quote_hash="a" * 64, request_key="settlement", request_hash="b" * 64, created_by=1)
    db.add(settlement)
    db.flush()
    app = SettlementApplication(settlement_id=settlement.id, receipt_id=receipt.id, component="goods",
        amount=amount, bank_charge=fee, status="applied")
    db.add(app)
    db.flush()
    return settlement, app


@pytest.mark.parametrize("status", ["reserved", "applied"])
def test_free_principal_can_reverse_while_all_fees_are_occupied(db, finance, stock, buyer, status):
    invoice, target, batch, row, user = allocated(db, finance, stock, buyer)
    settlement, app = occupy(db, invoice, row, amount=50, fee=10)
    app.status = status
    service.reverse_allocation(db, row.id, cmd("free-principal", row.version, amount=50), user)
    assert (row.effective_amount, row.effective_bank_charge) == (50, 10)
    assert (app.amount, app.bank_charge, app.status) == (50, 10, status)
    local_funding.validate(db, invoice, settlement, [row], {target.id: target}, [app], complete=True)
    with pytest.raises(ValueError, match="占用"):
        service.reverse_allocation(db, row.id, cmd("occupied-rest", row.version), user)
    assert row.reversed_amount == 50 and target.paid_amount == 50
    app.status = "released"
    service.reverse_allocation(db, row.id, cmd("released-rest", row.version), user)
    assert row.reversed_bank_charge == 10 and batch.bank_charge_total == 0
    assert sum(db.scalars(select(FinanceEvent.commission_amount_usd))) == 0


def test_only_free_fee_can_reverse_without_spending_occupied_principal(db, finance, stock, buyer):
    invoice, target, batch, row, user = allocated(db, finance, stock, buyer)
    settlement, app = occupy(db, invoice, row, amount=95, fee=5)
    service.reverse_allocation(db, row.id, cmd("free-fee", row.version, amount=5), user)
    assert (row.effective_amount, row.effective_bank_charge) == (95, 5)
    assert (app.amount, app.bank_charge) == (95, 5)
    event = db.scalar(select(FinanceEvent).where(FinanceEvent.action == "reverse_allocation"))
    assert event.commission_amount_usd == 0 and event.payload["reversed_bank_charge"] == "5.00"
    local_funding.validate(db, invoice, settlement, [row], {target.id: target}, [app], complete=True)


def test_reallocation_fee_pool_uses_remaining_effective_fee(db, finance, stock, buyer):
    invoice, target, batch, row, user = allocated(db, finance, stock, buyer)
    service.reverse_allocation(db, row.id, cmd("partial", row.version, amount=50), user)
    second = service.allocate(db, batch.id, AllocationCreate(request_key="allocate-again", expected_version=batch.version,
        invoice_id=invoice.id, receivable_id=target.id, amount=950, business_date=date(2026, 10, 3)), user)
    assert second.bank_charge == 95
    assert row.effective_bank_charge + second.effective_bank_charge == target.handling_amount
    assert query_service.reconcile(db, user)["differences"] == []


def test_fee_cent_and_commission_cent_both_conserve_across_partial_reversals(db, finance, stock, buyer):
    _, _, _, row, user = allocated(db, finance, stock, buyer, amount="0.03", fee="333.33", rate="0.5")
    assert row.bank_charge == Decimal("0.01")
    for index in range(3):
        service.reverse_allocation(db, row.id, cmd(f"cent-{index}", row.version, amount="0.01"), user)
    events = db.scalars(select(FinanceEvent).where(FinanceEvent.receipt_id == row.id)).all()
    assert sum(event.commission_amount_usd for event in events) == 0
    assert row.reversed_bank_charge == Decimal("0.01")
    assert sum(Decimal(event.payload["reversed_bank_charge"]) for event in events
               if event.action == "reverse_allocation") == Decimal("0.01")
    assert row.effective_amount == row.effective_bank_charge == 0


def test_migration_backfills_only_preexisting_local_full_reversals():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / "alembic/versions/213_partial_receipt_reversal.py"
    spec = importlib.util.spec_from_file_location("partial_receipt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_receipts (id INTEGER PRIMARY KEY, source TEXT, status TEXT, "
                                "amount NUMERIC(14,2), bank_charge NUMERIC(14,2))"))
        connection.execute(text("INSERT INTO ark_receipts VALUES "
            "(1,'local','reversed',100,10),(2,'local','active',80,8),(3,'manual','reversed',60,6)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        rows = connection.execute(text("SELECT id, amount, bank_charge, reversed_amount, reversed_bank_charge "
                                       "FROM ark_receipts ORDER BY id")).all()
        assert rows == [(1, 100, 10, 100, 10), (2, 80, 8, 0, 0), (3, 60, 6, 0, 0)]
    engine.dispose()
