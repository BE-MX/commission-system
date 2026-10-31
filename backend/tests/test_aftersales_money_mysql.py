"""Actual migration181 and approved money races in isolated loopback MySQL."""
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, Table, func, select
from sqlalchemy.orm import Session
from app.aftersales.local_money import execute_money
from app.aftersales.money_schemas import MoneyExecute
from app.aftersales.models import AfterSalesCase, AfterSalesExecution, AfterSalesReview
from app.finance import service as finance_service
from app.finance.models import FinanceEvent
from app.invoice.settlement_models import SettlementApplication, ReceiptBatch, Receivable
from app.receipt.models import Receipt
from tests.test_aftersales_local_mysql import returned_order
from tests.test_finance_mysql import finance_rows, USER, DAY
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_local_fulfillment_mysql import fulfillment
from tests.test_stock_reservations_mysql import orders, compete


@pytest.fixture
def approved_money(mysql_engine, returned_order):
    previous = MetaData()
    Table(AfterSalesReview.__tablename__, previous, *[
        Column(col.name, col.type, primary_key=col.primary_key, autoincrement=col.autoincrement,
               nullable=col.nullable, server_default=col.server_default)
        for col in AfterSalesReview.__table__.columns])
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("ALTER TABLE ark_settlement_applications DROP COLUMN released_amount, DROP COLUMN released_bank_charge")
        path = Path(__file__).parents[1] / "alembic/versions/215_aftersales_money_release.py"
        spec = spec_from_file_location("aftersales_money_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with Session(mysql_engine) as db:
        cases, item_id, _ = returned_order
        for identity in cases:
            case = db.get(AfterSalesCase, identity)
            case.requires_return = False
            case.approved_at = datetime.combine(DAY, datetime.min.time())
            case.selected_actions_json = [dict(code="cash_refund", currency="USD", amount_usd="700")]
            db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
                reviewer_user_id=1, reviewer_name_snapshot="Director", decision="approve",
                compensation_snapshot_json={"actions": case.selected_actions_json}, created_at=case.approved_at))
        app = db.scalar(select(SettlementApplication).where(SettlementApplication.component == "goods"))
        result = (cases, item_id, app.id, app.receipt_id)
        db.commit()
    return result


def command(data, key, amount="400"):
    return MoneyExecute(request_key=key, expected_version=1, settlement_item_id=data[1], application_id=data[2],
        quantity=7, action="cash_refund", amount=amount, currency="USD", disbursement="bank_refund",
        bank_reference="BANK-" + key, business_date=DAY, reason="approved refund")


def test_two_cases_cannot_release_same_shipment_share(mysql_engine, approved_money):
    data = approved_money
    results = compete(mysql_engine, [lambda db, case=case: execute_money(db, case, command(data, f"refund-{case}"), USER)
                                     for case in data[0]])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(SettlementApplication, data[2]).released_amount == 400
        assert db.get(Receipt, data[3]).reversed_amount == 400
        assert db.scalar(select(func.count()).select_from(FinanceEvent).where(FinanceEvent.action == "refund")) == 1


def test_same_concurrent_request_refunds_once(mysql_engine, approved_money):
    data = approved_money
    action = lambda db: execute_money(db, data[0][0], command(data, "same-refund"), USER)
    results = compete(mysql_engine, [action, action])
    assert results[0] == results[1] and results[0][0] == "ok"
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(AfterSalesExecution)) == 1
        assert db.scalar(select(func.count()).select_from(FinanceEvent).where(FinanceEvent.action == "refund")) == 1


def test_old_rr_snapshot_reads_prior_release(mysql_engine, approved_money):
    data = approved_money
    with Session(mysql_engine) as stale:
        assert stale.get(SettlementApplication, data[2]).released_amount == 0
        assert stale.scalar(select(func.count()).select_from(AfterSalesExecution)) == 0
        with Session(mysql_engine) as writer:
            execute_money(writer, data[0][0], command(data, "first"), USER)
            writer.commit()
        with pytest.raises(ValueError, match="金额份额|余额"):
            execute_money(stale, data[0][1], command(data, "stale"), USER)
        stale.rollback()
    with Session(mysql_engine) as db:
        execute_money(db, data[0][1], command(data, "remaining", "300"), USER)
        db.commit()
    with Session(mysql_engine) as db:
        assert db.get(SettlementApplication, data[2]).released_amount == 700
        assert db.get(Receipt, data[3]).effective_amount == 300


def test_refund_failure_rolls_back_all_components(mysql_engine, approved_money, monkeypatch):
    data = approved_money
    def fail(*args, **kwargs):
        raise ValueError("bank failure")
    monkeypatch.setattr(finance_service, "refund", fail)
    with Session(mysql_engine) as db:
        receipt = db.get(Receipt, data[3])
        target = db.get(Receivable, receipt.receivable_id)
        before = (target.paid_amount, target.adjustment_amount, receipt.reversed_amount)
        with pytest.raises(ValueError, match="bank failure"):
            execute_money(db, data[0][0], command(data, "failure"), USER)
        assert (target.paid_amount, target.adjustment_amount, receipt.reversed_amount) == before
        assert db.get(SettlementApplication, data[2]).released_amount == 0
        assert db.scalar(select(func.count()).select_from(AfterSalesExecution)) == 0
        db.commit()
