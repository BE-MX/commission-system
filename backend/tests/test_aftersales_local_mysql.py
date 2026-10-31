"""Actual migration180 and local-return races in disposable loopback MySQL.

Prerequisite fixtures apply the actual stock, order, finance and fulfillment
migrations. This fixture supplies only historical aftersales structures before
applying migration180 unchanged; it never creates execution tables from the ORM.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, UniqueConstraint, func, select
from sqlalchemy.orm import Session

from app.aftersales import service
from app.aftersales.local_execution import ReturnReceive, receive_return
from app.aftersales.models import AfterSalesCase, AfterSalesEvent, AfterSalesExecution, AfterSalesReview
from app.aftersales.local_replacement import ReplacementCreate, create_replacement
from app.aftersales.schemas import CaseCreate
from app.auth.models import ArkUser
from app.catalog.models import CatalogProduct, CatalogSku
from app.customer.models import CustomerAccount, CustomerAssignment
from app.core.time import beijing_now
from app.inventory.models import StockBalance, StockDocument, StockLedger, Warehouse
from app.inventory.service import post_document
from app.invoice import commerce_service, local_fulfillment
from app.invoice.commerce_schemas import LocalInvoiceAction, LocalInvoiceDraft
from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import SettlementItem, Receivable, ReceiptBatch
from app.production import local_service as manufacturing
from app.production.local_schemas import ProductionCreate, ProductionLine, QuantityCommand, SupplyCreate, ReceiptCreate, ReceiptAllocation
from app.production.models import ProcessRoute, OrderProductProcessProgress
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger
from app.receipt.models import Receipt
from app.system.models import SysDict
from app.trade.models import SalesRoster
from tests.test_aftersales_workflow import _payload
from tests.test_finance_mysql import finance_rows, USER, DAY
from tests.test_inventory_mysql import mysql_engine, stock_ids, body as stock_command
from tests.test_local_fulfillment_mysql import fulfillment, shipping
from tests.test_local_fulfillment import create_batch, act, inspect, allocate
from tests.test_stock_reservations_mysql import orders, compete


def local_payload(invoice, line, **changes):
    values = {**_payload().model_dump(), "product_id": None, "local_invoice_item_id": line.id,
        "order_id": f"local:{invoice.id}", "customer_id": invoice.customer_id,
        "purchase_date": invoice.invoice_date, "feedback_date": DAY, "quantity": Decimal(7)}
    values.update(changes)
    return CaseCreate.model_validate(values)


@pytest.fixture
def returned_order(mysql_engine, fulfillment):
    previous = MetaData()
    # Runtime prerequisites now include native confirmation-time department lookup.
    # 185 DDL is exercised independently in test_trade_mysql.
    for model in (AfterSalesCase, AfterSalesEvent, SysDict, SalesRoster):
        table = Table(model.__tablename__, previous, *[
            Column(col.name, String(256) if col.name == "product_name_snapshot" else col.type,
                primary_key=col.primary_key, autoincrement=col.autoincrement,
                nullable=col.nullable, server_default=col.server_default)
            for col in model.__table__.columns if col.name != "local_invoice_item_id"])
        for constraint in model.__table__.constraints:
            if isinstance(constraint, UniqueConstraint):
                table.append_constraint(UniqueConstraint(
                    *(col.name for col in constraint.columns), name=constraint.name))
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        path = Path(__file__).parents[1] / "alembic/versions/214_local_aftersales.py"
        spec = spec_from_file_location("aftersales_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with Session(mysql_engine) as db:
        local_fulfillment.act(db, fulfillment[0], shipping(fulfillment, "ship-for-return"), USER, "ship")
        item = db.scalar(select(SettlementItem).where(SettlementItem.settlement_id == fulfillment[0]))
        line = db.get(InvoiceItem, item.invoice_item_id)
        invoice = db.get(Invoice, line.invoice_id)
        actor = db.get(ArkUser, 1)
        cases = []
        for _ in range(2):
            case = service.create_case(db, local_payload(invoice, line), actor, scope=USER)
            case.current_status, case.requires_return = "approved", True
            db.flush()
            cases.append(case.id)
        result = (cases, item.id, line.id)
        db.commit()
    return result


def command(key, item_id, warehouse_id, quantity=4, version=1):
    return ReturnReceive(request_key=key, expected_version=version, settlement_item_id=item_id,
        warehouse_id=warehouse_id, quantity=quantity, business_date=DAY, reason="customer returned goods")


def row_count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_migration180_freezes_full_local_snapshot_and_validates_real_purchase_date(mysql_engine, returned_order):
    _, _, line_id = returned_order
    with Session(mysql_engine) as db:
        line = db.get(InvoiceItem, line_id)
        invoice = db.get(Invoice, line.invoice_id)
        actor = db.get(ArkUser, 1)
        before = row_count(db, AfterSalesCase)
        forged_date = local_payload(invoice, line, purchase_date=DAY-timedelta(days=2),
                                    feedback_date=DAY-timedelta(days=1))
        with pytest.raises(ValueError, match="反馈日期"):
            service.create_case(db, forged_date, actor, scope=USER)
        assert row_count(db, AfterSalesCase) == before
        # The catalog and invoice snapshot both allow 512 characters. Migration
        # 180 must actually widen the previous 256-character aftersales column.
        line.product_name = "H" * 512
        db.flush()
        payload = local_payload(invoice, line, product_name_snapshot="caller label",
            customer_name_snapshot="caller customer", order_no_snapshot="caller order",
            purchase_date=DAY-timedelta(days=2))
        case = service.create_case(db, payload, actor, scope=USER)
        assert case.product_id is None and not case.is_custom_product
        assert case.product_name_snapshot == line.product_name
        assert case.customer_name_snapshot == invoice.customer_name
        assert case.order_no_snapshot == invoice.invoice_no
        assert case.purchase_date == invoice.invoice_date
        identity = case.id
        db.commit()
    with Session(mysql_engine) as db:
        assert len(db.get(AfterSalesCase, identity).product_name_snapshot) == 512


def test_inactive_sku_return_is_atomic_scoped_and_idempotent(mysql_engine, stock_ids, returned_order):
    cases, item_id, line_id = returned_order
    with Session(mysql_engine) as db:
        db.add(ArkUser(id=2, username="outsider", real_name="Outsider", password_hash="unused"))
        db.get(CatalogProduct, stock_ids[0]).active = False
        db.get(CatalogSku, stock_ids[1]).active = False
        db.commit()
    with Session(mysql_engine) as db:
        request = command("receive", item_id, stock_ids[2])
        with pytest.raises(HTTPException) as denied:
            receive_return(db, cases[0], request, {"sub": "2"})
        assert denied.value.status_code == 404
        counts = {model: row_count(db, model) for model in (AfterSalesExecution, StockDocument, StockLedger)}
        with pytest.raises(ValueError, match="仓库"):
            receive_return(db, cases[0], request.model_copy(update={"warehouse_id": 999999}), USER)
        assert all(row_count(db, model) == count for model, count in counts.items())
        assert db.get(AfterSalesCase, cases[0]).version == 1
        assert db.get(AfterSalesCase, cases[0]).current_status == "approved"
        # Failed attempts do not occupy the request key. A discontinued SKU can
        # then be received using the shipped identity, without becoming sellable.
        execution = receive_return(db, cases[0], request, USER)
        assert receive_return(db, cases[0], request, USER).id == execution.id
        with pytest.raises(ValueError, match="幂等"):
            receive_return(db, cases[0], request.model_copy(update={"quantity": 3}), USER)
        db.commit()
    with Session(mysql_engine) as db:
        balances = {row.quality: row for row in db.scalars(select(StockBalance)).all()}
        assert balances["quarantine"].on_hand == 4 and balances["quarantine"].reserved == 0
        assert balances["sellable"].on_hand == 3
        assert db.get(InvoiceItem, line_id).stock_shipped_quantity == 7
        assert db.get(SettlementItem, item_id).quantity == 7
        assert row_count(db, AfterSalesExecution) == 1
        execution = db.scalar(select(AfterSalesExecution))
        assert db.get(StockDocument, execution.stock_document_id).kind == "sales_return"


def test_two_cases_cannot_concurrently_return_more_than_shipped(mysql_engine, stock_ids, returned_order):
    cases, item_id, _ = returned_order
    results = compete(mysql_engine, [lambda db, case=case: receive_return(db, case,
        command(f"return-{case}", item_id, stock_ids[2]), USER) for case in cases])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.quality == "quarantine")) == 4
        assert row_count(db, AfterSalesExecution) == 1


def test_duplicate_concurrent_return_posts_one_stock_document(mysql_engine, stock_ids, returned_order):
    cases, item_id, _ = returned_order
    request = command("same-return", item_id, stock_ids[2])
    action = lambda db: receive_return(db, cases[0], request, USER)
    results = compete(mysql_engine, [action, action])
    assert results[0] == results[1] and results[0][0] == "ok"
    with Session(mysql_engine) as db:
        assert row_count(db, AfterSalesExecution) == 1
        assert len(db.scalars(select(StockDocument).where(StockDocument.kind == "sales_return")).all()) == 1
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.quality == "quarantine")) == 4


def test_old_rr_snapshot_sees_returned_quantity_from_other_case(mysql_engine, stock_ids, returned_order):
    cases, item_id, line_id = returned_order
    with Session(mysql_engine) as stale:
        assert row_count(stale, AfterSalesExecution) == 0
        with Session(mysql_engine) as writer:
            receive_return(writer, cases[0], command("first-return", item_id, stock_ids[2]), USER)
            writer.commit()
        with pytest.raises(ValueError, match="超过"):
            receive_return(stale, cases[1], command("excess-return", item_id, stock_ids[2]), USER)
        stale.rollback()
    with Session(mysql_engine) as db:
        receive_return(db, cases[1], command("remaining-return", item_id, stock_ids[2], quantity=3), USER)
        db.commit()
    with Session(mysql_engine) as db:
        assert row_count(db, AfterSalesExecution) == 2
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.quality == "quarantine")) == 7
        assert db.get(InvoiceItem, line_id).stock_shipped_quantity == 7


@pytest.fixture
def replacement_case(mysql_engine, stock_ids, returned_order):
    # finance_rows provides the complete current customer contract. Replacement
    # also needs its approval and customer-assignment tables in this partial schema.
    with mysql_engine.begin() as conn:
        AfterSalesReview.__table__.create(conn)
        CustomerAssignment.__table__.create(conn)
    cases, _, line_id = returned_order
    with Session(mysql_engine) as db:
        customer = db.get(CustomerAccount, 1)
        customer.customer_code, customer.display_name = "RETURN-BUYER", "Buyer"
        customer.entity_type, customer.identity_status = "registered_company", "verified"
        customer.relationship_stage, customer.record_status = "active_customer", "active"
        customer.relationship_stage_changed_at = beijing_now()
        customer.relationship_stage_reason = "verified buyer"
        customer.identity_confidence, customer.profile_completeness, customer.profile_input_seq = 1, 100, 1
        invoice = db.get(Invoice, db.get(InvoiceItem, line_id).invoice_id)
        invoice.sales_user_id, invoice.sales_user_name = 1, "Worker"
        case = db.get(AfterSalesCase, cases[0])
        action = dict(code="replacement", quantity=2, local_sku_id=stock_ids[1],
                      product="approved replacement", estimated_cost_usd="10")
        case.selected_actions_json = [action]
        db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
            reviewer_user_id=1, reviewer_name_snapshot="Director", decision="approve",
            compensation_snapshot_json={"actions": [action]}, created_at=datetime(2026, 10, 3, 9)))
        post_document(db, stock_command("replacement-stock", stock_ids, 2), actor_id=1)
        db.commit()
    return cases[0]


def replacement_command(key, warehouse, version=1):
    return ReplacementCreate(request_key=key, expected_version=version, action_index=0,
        quantity=2, warehouse_id=warehouse, business_date=DAY, reason="approved replacement")


def test_replacement_concurrency_cannot_use_one_approval_twice(mysql_engine, stock_ids, replacement_case):
    results = compete(mysql_engine, [lambda db, key=key: create_replacement(db, replacement_case,
        replacement_command(key, stock_ids[2]), USER) for key in ("replace-first", "replace-second")])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        execution = db.scalar(select(AfterSalesExecution))
        invoice = db.get(Invoice, execution.related_invoice_id)
        assert row_count(db, AfterSalesExecution) == 1
        assert invoice.total_amount == 0 and invoice.commerce_status == "confirmed"
        assert invoice.items[0].quantity == invoice.items[0].stock_reserved_quantity == 2
        assert db.scalar(select(StockBalance.reserved).where(StockBalance.quality == "sellable")) == 5


def test_cancelled_replacement_can_be_rearranged_without_duplicate_reservations(mysql_engine, stock_ids, replacement_case):
    with Session(mysql_engine) as db:
        first_request = replacement_command("first-replacement", stock_ids[2])
        execution = create_replacement(db, replacement_case, first_request, USER)
        invoice = db.get(Invoice, execution.related_invoice_id)
        first_invoice_id = invoice.id
        commerce_service.cancel(db, invoice.id, LocalInvoiceAction(request_key="cancel-replacement",
            expected_version=invoice.commerce_version, reason="change replacement arrangement"), USER)
        case = db.get(AfterSalesCase, replacement_case)
        # Replaying the first command still refers to the historical cancelled
        # order. A new command may reuse the released approval quantity.
        assert create_replacement(db, replacement_case, first_request, USER).id == execution.id
        replacement = create_replacement(db, replacement_case,
            replacement_command("replacement-rearranged", stock_ids[2], case.version), USER)
        assert replacement.related_invoice_id != first_invoice_id
        db.commit()
    with Session(mysql_engine) as db:
        assert row_count(db, AfterSalesExecution) == 2
        assert db.get(Invoice, first_invoice_id).commerce_status == "cancelled"
        assert db.scalar(select(StockBalance.reserved).where(StockBalance.quality == "sellable")) == 5


@pytest.fixture
def replacement_production(mysql_engine, replacement_case):
    # Restore only the production prerequisite boundary, then run actual177.
    # Existing fixture invoice lines have no production supply at this point.
    previous = MetaData()
    added = {"transaction_mode", "local_sku_id", "process_route_id", "completed_qty", "supplied_qty",
             "supplied_received_qty", "local_version", "local_event_id"}
    for model in (ProductionOrder, ProductionOrderItem, ProcessRoute, OrderProductProcessProgress,
                  SemifinishedMaterial, InventoryBalance, InventoryLedger):
        Table(model.__tablename__, previous, *[
            Column(col.name, String(100) if model is ProductionOrderItem and col.name == "model" else
                String(255) if model is ProductionOrderItem and col.name == "product_name" else col.type,
                primary_key=col.primary_key, autoincrement=col.autoincrement, unique=bool(col.unique),
                nullable=False if model is ProductionOrderItem and col.name == "product_id" else col.nullable,
                server_default=col.server_default)
            for col in model.__table__.columns if col.name not in added])
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("ALTER TABLE ark_invoice_items DROP COLUMN production_pending_quantity")
        path = Path(__file__).parents[1] / "alembic/versions/211_local_production.py"
        spec = spec_from_file_location("aftersales_production_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    return replacement_case


def test_production_replacement_requires_acceptance_and_inspected_dispatch(mysql_engine, stock_ids, returned_order, replacement_production):
    with Session(mysql_engine) as db:
        case = db.get(AfterSalesCase, replacement_production)
        # This approval promises a remake without requiring physical return.
        case.requires_return = False
        warehouse = db.get(Warehouse, stock_ids[2])
        sku = db.get(CatalogSku, stock_ids[1])
        product = db.get(CatalogProduct, stock_ids[0])
        body = replacement_command("production-replacement", warehouse.id).model_copy(update={"order_type": "production"})
        before = row_count(db, Invoice)
        for row in (sku, product):
            row.active = False
            db.flush()
            with pytest.raises(ValueError, match="停用"):
                create_replacement(db, case.id, body, USER)
            assert row_count(db, Invoice) == before and row_count(db, AfterSalesExecution) == 0
            row.active = True
            db.flush()
        execution = create_replacement(db, case.id, body, USER)
        invoice = db.get(Invoice, execution.related_invoice_id)
        assert invoice.order_type == "production" and invoice.items[0].stock_reserved_quantity == 0
        order = manufacturing.create(db, ProductionCreate(request_key="remake-production", batch_no="REMAKE",
            items=[ProductionLine(local_sku_id=sku.id, quantity=2)]), USER)
        item = db.scalar(select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id))
        supply = manufacturing.link_supply(db, item.id, SupplyCreate(request_key="remake-supply", expected_version=item.local_version,
            invoice_item_id=invoice.items[0].id, quantity=2, reason="approved remake"), USER)
        manufacturing.complete(db, item.id, QuantityCommand(request_key="remake-complete", expected_version=item.local_version,
            quantity=2, reason="manufacturing complete"), USER)
        assert invoice.items[0].production_pending_quantity == 2 and invoice.items[0].stock_reserved_quantity == 0
        manufacturing.receive(db, item.id, ReceiptCreate(request_key="remake-accept", expected_version=item.local_version,
            quantity=2, warehouse_id=warehouse.id, reason="QC accepted",
            allocations=[ReceiptAllocation(supply_id=supply.id, quantity=2)]), USER)
        assert invoice.items[0].production_pending_quantity == 0 and invoice.items[0].stock_reserved_quantity == 2
        shipment = create_batch(db, invoice, USER, warehouse, 2, "remake-shipment")
        act(db, shipment, USER, "ready-remake", "ready")
        with pytest.raises(ValueError, match="检验出库"):
            service.close_case(db, case.id, db.get(ArkUser, 1), "Customer acknowledged")
        with pytest.raises(ValueError, match="检验"):
            act(db, shipment, USER, "missing-inspection", "ship", inspection_version=0)
        inspection = inspect(db, shipment, USER)
        act(db, shipment, USER, "dispatch-remake", "ship", inspection_version=inspection.edit_version)
        assert invoice.commerce_status == "shipped" and invoice.items[0].stock_shipped_quantity == 2
        assert db.get(InvoiceItem, returned_order[2]).stock_shipped_quantity == 7
        assert db.scalar(select(StockBalance.on_hand).where(StockBalance.quality == "sellable")) == 5
        assert not db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id)).all()
        service.close_case(db, case.id, db.get(ArkUser, 1), "Customer acknowledged")
        assert case.current_status == "closed" and str(execution.id) in case.execution_result
        db.commit()


def test_mixed_gift_and_paid_lines_preserve_payment_gate(mysql_engine, stock_ids, replacement_case):
    with Session(mysql_engine) as db:
        warehouse = db.get(Warehouse, stock_ids[2])
        invoice = commerce_service.create_draft(db, LocalInvoiceDraft(request_key="mixed-order", local_customer_id=1,
            sales_user_id=1, invoice_date=DAY, items=[
                dict(local_sku_id=stock_ids[1], quantity=1, price_per_piece=0),
                dict(local_sku_id=stock_ids[1], quantity=1, price_per_piece=5)]), USER)
        commerce_service.confirm(db, invoice.id, LocalInvoiceAction(request_key="mixed-confirm",
            expected_version=invoice.commerce_version, warehouse_id=warehouse.id, reason="mixed gift and paid items"), USER)
        gift = create_batch(db, invoice, USER, warehouse, 1, "gift-shipment")
        assert gift.quote["new_payment_due"] == "0.00"
        act(db, gift, USER, "ready-gift", "ready")
        gift_inspection = inspect(db, gift, USER)
        act(db, gift, USER, "dispatch-gift", "ship", inspection_version=gift_inspection.edit_version)
        quote_body = LocalShipmentQuote(business_date=DAY, warehouse_id=warehouse.id,
            items=[dict(invoice_item_id=invoice.items[1].id, quantity=1)])
        quote = local_fulfillment.quote(db, invoice.id, quote_body, USER)
        paid = local_fulfillment.create(db, invoice.id, LocalShipmentCreate(**quote_body.model_dump(),
            request_key="paid-shipment", expected_version=invoice.commerce_version, quote_hash=quote["quote_hash"]), USER)
        with pytest.raises(ValueError, match="不足"):
            act(db, paid, USER, "unpaid", "ready")
        assert not db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id)).all()
        target = db.scalar(select(Receivable).where(Receivable.invoice_id == invoice.id))
        # The fixture's second confirmed customer payment remains unallocated.
        payment = db.scalar(select(ReceiptBatch).order_by(ReceiptBatch.id.desc()).limit(1))
        allocate(db, invoice, payment, USER, target, 5, "mixed-funds")
        act(db, paid, USER, "ready-paid", "ready")
        with pytest.raises(ValueError, match="检验"):
            act(db, paid, USER, "paid-missing-inspection", "ship", inspection_version=0)
        paid_inspection = inspect(db, paid, USER)
        act(db, paid, USER, "dispatch-paid", "ship", inspection_version=paid_inspection.edit_version)
        assert invoice.commerce_status == "shipped" and target.paid_amount == target.amount == 5
        assert [line.stock_shipped_quantity for line in invoice.items] == [1, 1]
        db.commit()


def test_stale_case_identity_cannot_close_a_reopened_case(mysql_engine, stock_ids, returned_order):
    cases, item_id, _ = returned_order
    with Session(mysql_engine) as db:
        receive_return(db, cases[0], command("all-returned", item_id, stock_ids[2], quantity=7), USER)
        db.commit()
    with Session(mysql_engine) as stale:
        cached = stale.get(AfterSalesCase, cases[0])
        assert cached.current_status == "processing"
        with Session(mysql_engine) as fresh:
            actor = fresh.get(ArkUser, 1)
            service.close_case(fresh, cases[0], actor, "Initially resolved")
            fresh.commit()
            service.reopen_case(fresh, cases[0], actor, "Customer reported another unresolved issue")
            fresh.commit()
        with pytest.raises(ValueError, match="执行结果|状态"):
            service.close_case(stale, cases[0], stale.get(ArkUser, 1), "Stale close request")
        stale.rollback()
    with Session(mysql_engine) as db:
        assert db.get(AfterSalesCase, cases[0]).current_status == "returned"
