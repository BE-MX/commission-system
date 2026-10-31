"""Actual migration 229 and financial races against isolated MySQL RR schemas."""
from datetime import date
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, Numeric, Table, UniqueConstraint, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateColumn

from app.finance import service
from app.finance.models import Currency, BankAccount, FinanceEvent
from app.finance.schemas import AllocationCreate, FinanceAction
from app.customer.models import CustomerAccount, CustomerOrder, CustomerOrderItem, CustomerObjectOwnership
from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable, SettlementApplication, BatchAttachment
from app.receipt.models import Receipt
from app.models.customer import CustomerCommissionSnapshot
from app.models.commission import SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_stock_reservations_mysql import orders, compete

USER = {"sub": "1", "roles": ["super_admin"]}
DAY = date(2026, 10, 3)


@pytest.fixture
def finance_rows(mysql_engine, orders):
    added = {"transaction_mode", "local_customer_id", "bank_account_id", "bank_reference", "finance_status",
             "actual_bank_fee", "net_amount", "allocated_amount", "refunded_amount", "rate_to_cny", "rate_to_usd",
             "confirmed_by", "confirmed_at", "confirmed_date", "paid_amount", "adjustment_amount", "due_date",
             "reversed_amount", "reversed_bank_charge"}
    previous = MetaData()
    for model in (ReceiptBatch, Receivable, Receipt, SettlementApplication, BatchAttachment):
        table = Table(model.__tablename__, previous, *[
            Column(col.name, col.type, primary_key=col.primary_key, autoincrement=col.autoincrement,
                   nullable=col.nullable, server_default=col.server_default)
            for col in model.__table__.columns if col.name not in added])
        if model is Receipt:
            table.append_constraint(UniqueConstraint("batch_id", "receivable_id", name="uq_receipt_batch_target"))
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        path = Path(__file__).parents[1] / "alembic/versions/229_local_finance.py"
        spec = spec_from_file_location("finance_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        path = Path(__file__).parents[1] / "alembic/versions/232_partial_receipt_reversal.py"
        spec = spec_from_file_location("partial_reversal_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        # Finance resolves the current customer identity, including merged and
        # disputed states. Upgrade the reservation fixture's empty PK-only
        # prerequisite before inserting an actual current-model customer.
        for column in CustomerAccount.__table__.columns:
            if column.name != "id":
                conn.exec_driver_sql("ALTER TABLE ark_customer_accounts ADD COLUMN " +
                    str(CreateColumn(column).compile(dialect=conn.dialect)))
        # Logical payer resolution reads the order projection/ownership even
        # before a new invoice has been projected. Empty current tables must be
        # present; no mock or fallback bypasses those identity checks.
        customer_prerequisites = MetaData()
        for model in (CustomerOrder, CustomerOrderItem, CustomerObjectOwnership):
            Table(model.__tablename__, customer_prerequisites, *[
                Column(col.name, col.type, primary_key=col.primary_key, autoincrement=col.autoincrement,
                       nullable=col.nullable, server_default=col.server_default, unique=col.unique)
                for col in model.__table__.columns
                if not (model is CustomerOrderItem and col.name == "local_invoice_item_id")])
        customer_prerequisites.create_all(conn)
        CustomerCommissionSnapshot.__table__.create(conn)
        from app.sales_return.models import SalesReturn
        SalesReturn.__table__.create(conn)
        commission_previous = MetaData()
        for model in (SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus):
            Table(model.__tablename__, commission_previous, *[
                Column(col.name, Numeric(12, 2) if col.name in {"payment_amount", "salesperson_commission", "supervisor_commission", "second_supervisor_commission"}
                    else Numeric(12, 6) if model is SyncedPayment and col.name == "exchange_rate" else col.type,
                    primary_key=col.primary_key, autoincrement=col.autoincrement, nullable=col.nullable,
                    server_default=col.server_default, unique=col.unique)
                for col in model.__table__.columns])
        commission_previous.create_all(conn)
        path = Path(__file__).parents[1] / "alembic/versions/235_local_commission.py"
        spec = spec_from_file_location("local_commission_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        # Current commission reads include the frozen RMB values introduced by
        # 242. Apply its actual DDL, preserving the earlier migration coverage.
        path = Path(__file__).parents[1] / "alembic/versions/242_commerce_opening_links.py"
        spec = spec_from_file_location("commission_fx_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with Session(mysql_engine) as db:
        db.add(CustomerAccount(id=1, customer_code="MYSQL-FINANCE", display_name="Buyer",
            entity_type="registered_company", identity_status="verified",
            relationship_stage="active_customer", relationship_stage_changed_at=beijing_now(),
            relationship_stage_reason="verified test buyer", record_status="active",
            identity_confidence=1, profile_completeness=100, profile_input_seq=1))
        db.add(Currency(code="USD", name="USD", rate_to_cny=7))
        db.flush()
        bank = BankAccount(code="USD1", name="USD1", currency="USD")
        db.add(bank)
        db.flush()
        from app.core.config import get_settings
        from app.commerce_transition import service as transition
        settings = get_settings()
        domain = transition.register_bank_domain(db, subject_key=settings.COMMERCE_RECEIVING_ENTITY_KEY,
            account_key="synthetic-usd-bank", channel=settings.COMMERCE_BANK_CHANNEL,
            legacy_identity_complete=True, enforced=True, bank_account_ids=[bank.id],
            evidence={"synthetic_empty_schema": True})
        ids = []
        for invoice in db.scalars(select(Invoice).order_by(Invoice.id)).all():
            invoice.local_customer_id, invoice.customer_id = 1, "ark:1"
            invoice.internal_balance, invoice.internal_received = 1000, 0
            target = Receivable(invoice_id=invoice.id, business_key=f"test:{invoice.id}", kind="goods", amount=1000,
                                currency="USD", customer_id="ark:1", remote_status="not_applicable")
            db.add(target)
            db.flush()
            batch = ReceiptBatch(batch_no=f"PAY-{invoice.id}", transaction_mode="local", local_customer_id=1,
                customer_id="ark:1", currency="USD", gross_amount=1000, net_amount=980, actual_bank_fee=20,
                bank_account_id=bank.id, bank_reference=f"BANK-{invoice.id}", finance_status="confirmed",
                collection_date=DAY, payment_type="bank_transfer", request_key=f"reg-{invoice.id}", request_hash="a"*64,
                rate_to_cny=7, rate_to_usd=1, created_by=1, confirmed_date=DAY)
            db.add(batch)
            db.flush()
            identity = transition.claim_bank_identity(db, domain_id=domain.id,
                transaction_id=batch.bank_reference, route="local", currency="USD", amount=batch.gross_amount,
                payer_evidence={"bank_identity_verified": True, "synthetic_fixture": True}).identity
            transition.bind_bank_payment(db, identity.id, f"local:{batch.id}")
            ids.append((invoice.id, target.id, batch.id))
        db.commit()
    return ids


def allocation(ids, key, amount=700):
    return AllocationCreate(request_key=key, expected_version=1, invoice_id=ids[0], receivable_id=ids[1],
                            amount=amount, business_date=DAY)


def test_same_payment_two_orders_cannot_overallocate(mysql_engine, finance_rows):
    first, second = finance_rows
    result = compete(mysql_engine, [
        lambda db: service.allocate(db, first[2], allocation(first, "one"), USER),
        lambda db: service.allocate(db, first[2], allocation(second, "two"), USER),
    ])
    assert sorted(x[0] for x in result) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(ReceiptBatch, first[2]).allocated_amount == 700
        assert sum(db.scalars(select(Receivable.paid_amount))) == 700


def test_two_payments_cannot_overpay_same_receivable(mysql_engine, finance_rows):
    first, second = finance_rows
    result = compete(mysql_engine, [
        lambda db: service.allocate(db, first[2], allocation(first, "one"), USER),
        lambda db: service.allocate(db, second[2], allocation(first, "two"), USER),
    ])
    assert sorted(x[0] for x in result) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(Receivable, first[1]).paid_amount == 700
        assert sum(db.scalars(select(ReceiptBatch.allocated_amount))) == 700


def test_duplicate_allocation_and_refund_vs_allocation(mysql_engine, finance_rows):
    first, _ = finance_rows
    body = allocation(first, "same", 400)
    call = lambda db: service.allocate(db, first[2], body, USER)
    result = compete(mysql_engine, [call, call])
    assert result[0] == result[1] and result[0][0] == "ok"
    refund = FinanceAction(request_key="refund", expected_version=2, amount=600, bank_reference="REFUND1", reason="test", business_date=DAY)
    allocate = body.model_copy(update={"request_key": "more", "expected_version": 2, "amount": Decimal("600")})
    result = compete(mysql_engine, [lambda db: service.refund(db, first[2], refund, USER),
                                    lambda db: service.allocate(db, first[2], allocate, USER)])
    assert sorted(x[0] for x in result) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        batch = db.get(ReceiptBatch, first[2])
        assert batch.allocated_amount + batch.refunded_amount == 1000
        assert len(db.scalars(select(FinanceEvent)).all()) == 2


def test_old_rr_snapshot_cannot_ignore_committed_allocation(mysql_engine, finance_rows):
    first, second = finance_rows
    with Session(mysql_engine) as stale:
        assert stale.get(Receivable, first[1]).paid_amount == 0
        with Session(mysql_engine) as fresh:
            service.allocate(fresh, first[2], allocation(first, "first"), USER)
            fresh.commit()
        with pytest.raises(ValueError, match="余额|未核销"):
            service.allocate(stale, second[2], allocation(first, "second"), USER)
        stale.rollback()
    with Session(mysql_engine) as db:
        assert db.get(Receivable, first[1]).paid_amount == 700
