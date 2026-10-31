"""Real MySQL serializes commission consumers with the same finance book."""
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pytest

from app.commission.models import CommissionBasis, CommissionEventProjection
from app.commission.service import ROLES
from app.finance import service
from app.finance.models import FinanceEvent
from app.finance.schemas import FinanceAction
from app.models.commission import SyncedPayment, CommissionBatch, CommissionDetail, PaymentCommissionStatus
from app.services.commission_calculator import calculate_commission, confirm_batch, void_batch
from tests.test_finance_mysql import finance_rows, allocation, USER, DAY
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_stock_reservations_mysql import orders, compete


@pytest.fixture
def native_income(mysql_engine, finance_rows):
    with Session(mysql_engine) as db:
        ids = finance_rows[0]
        receipt = service.allocate(db, ids[2], allocation(ids, "native", 100), USER)
        basis = db.scalar(select(CommissionBasis))
        basis.snapshot = {"source_snapshot_id": 1, "rule_version": "native-2026-10-03",
            **{f"{role}_id": "ark:1" if role == "salesperson" else None for role in ROLES},
            **{f"{role}_rate": "0.02" if role == "salesperson" else "0" for role in ROLES},
            **{f"{role}_original_commission": "2.00" if role == "salesperson" else "0.00" for role in ROLES}}
        batches = [CommissionBatch(batch_name=f"test-{i}", period_start=DAY, period_end=DAY, status="draft") for i in range(3)]
        db.add_all(batches)
        db.flush()
        result = receipt.id, [row.id for row in batches]
        db.commit()
    return result


def test_two_batches_only_consume_each_native_event_once(mysql_engine, native_income):
    _, batches = native_income
    def calculate(db, identity):
        calculate_commission(db, identity)
        return db.get(CommissionBatch, identity)
    results = compete(mysql_engine, [lambda db: calculate(db, batches[0]), lambda db: calculate(db, batches[1])])
    assert [row[0] for row in results] == ["ok", "ok"]
    with Session(mysql_engine) as db:
        assert len(db.scalars(select(CommissionEventProjection)).all()) == 1
        assert len(db.scalars(select(CommissionDetail)).all()) == 1
        assert len(db.scalars(select(PaymentCommissionStatus)).all()) == 1


def test_confirmed_original_allows_later_refund_without_rewriting_income(mysql_engine, native_income):
    receipt_id, batches = native_income
    with Session(mysql_engine) as db:
        assert calculate_commission(db, batches[0]).total_payments == 1
        confirm_batch(db, batches[0], "admin")
        db.commit()
    with Session(mysql_engine) as db:
        service.reverse_allocation(db, receipt_id, FinanceAction(request_key="refund-source", expected_version=1,
            business_date=DAY, reason="approved"), USER)
        db.commit()
    with Session(mysql_engine) as db:
        result = calculate_commission(db, batches[1])
        assert result.total_payments == 1 and result.total_salesperson_commission == Decimal("-2")
        original = db.scalar(select(CommissionDetail).where(CommissionDetail.batch_id == batches[0]))
        assert original.status == "confirmed" and original.salesperson_commission == Decimal("2")
        db.commit()


def test_old_rr_snapshot_does_not_reproject_committed_native_event(mysql_engine, native_income):
    _, batches = native_income
    with Session(mysql_engine) as stale:
        assert stale.scalar(select(func.count()).select_from(CommissionEventProjection)) == 0
        with Session(mysql_engine) as writer:
            assert calculate_commission(writer, batches[0]).total_payments == 1
            writer.commit()
        result = calculate_commission(stale, batches[1])
        assert result.total_payments == 0
        stale.commit()
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(CommissionEventProjection)) == 1
        assert db.scalar(select(func.count()).select_from(CommissionDetail)) == 1
        assert db.scalar(select(func.count()).select_from(PaymentCommissionStatus)) == 1


def test_old_rr_snapshot_reuses_projection_after_original_batch_is_voided(mysql_engine, native_income):
    _, batches = native_income
    with Session(mysql_engine) as stale:
        assert stale.scalar(select(func.count()).select_from(CommissionEventProjection)) == 0
        with Session(mysql_engine) as writer:
            assert calculate_commission(writer, batches[0]).total_payments == 1
            void_batch(writer, batches[0])
            writer.commit()
        result = calculate_commission(stale, batches[1])
        assert result.total_payments == 1
        assert result.total_salesperson_commission == Decimal("2")
        stale.commit()
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(CommissionEventProjection)) == 1
        assert db.scalar(select(func.count()).select_from(CommissionDetail).where(CommissionDetail.status != "voided")) == 1
        assert db.scalar(select(func.count()).select_from(PaymentCommissionStatus)) == 1


def test_old_rr_snapshot_sees_sources_of_newly_committed_allocation(mysql_engine, native_income, finance_rows):
    _, batches = native_income
    with Session(mysql_engine) as stale:
        assert stale.scalar(select(func.count()).select_from(CommissionBasis)) == 1
        with Session(mysql_engine) as writer:
            original_basis = writer.scalar(select(CommissionBasis))
            ids = finance_rows[1]
            receipt = service.allocate(writer, ids[2], allocation(ids, "later-native", 100), USER)
            later_basis = writer.scalar(select(CommissionBasis).join(FinanceEvent, FinanceEvent.id == CommissionBasis.event_id)
                .where(FinanceEvent.receipt_id == receipt.id))
            later_basis.snapshot = dict(original_basis.snapshot)
            writer.commit()
        result = calculate_commission(stale, batches[0])
        assert result.total_payments == 2
        assert result.total_salesperson_commission == Decimal("4")
        stale.commit()
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(CommissionEventProjection)) == 2
        assert db.scalar(select(func.count()).select_from(PaymentCommissionStatus)) == 2
