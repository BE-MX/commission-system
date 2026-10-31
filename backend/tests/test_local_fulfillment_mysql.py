"""Actual migration178 and dispatch/inspection races on isolated MySQL."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.schema import CreateColumn
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.finance import service as finance_service
from app.finance.schemas import AllocationCreate
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement, SettlementItem, ShipmentOutbound, SettlementEvent
from app.invoice import local_fulfillment as service
from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate, LocalShipmentAction
from app.inventory.reservation_service import reserve_line, release_line
from app.inventory.models import StockBalance, StockDocument
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from app.shipping_inspection import service as inspection_service
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_stock_reservations_mysql import orders, compete
from tests.test_finance_mysql import finance_rows, USER, DAY


@pytest.fixture
def fulfillment(mysql_engine, finance_rows, stock_ids):
    previous = MetaData()
    for model in (ShipmentSettlement, SettlementItem, ShipmentOutbound, SettlementEvent, ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission):
        Table(model.__tablename__, previous, *[Column(col.name, col.type, primary_key=col.primary_key,
            autoincrement=col.autoincrement, nullable=col.nullable, server_default=col.server_default)
            for col in model.__table__.columns if col.name not in {"local_outbound_id", "local_outbound_version"}])
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("ALTER TABLE ark_invoices DROP COLUMN local_deposit_amount, DROP COLUMN local_deposit_charge")
        for column in ArkUser.__table__.columns:
            if column.name != "id":
                ddl = str(CreateColumn(Column(column.name, column.type, nullable=True)).compile(dialect=conn.dialect))
                conn.exec_driver_sql("ALTER TABLE ark_users ADD COLUMN " + ddl)
        conn.exec_driver_sql("INSERT INTO ark_users(id, username, real_name, password_hash, is_active) VALUES (1, 'worker', 'Worker', 'unused', 1)")
        path = Path(__file__).parents[1] / "alembic/versions/212_local_fulfillment.py"
        spec = spec_from_file_location("fulfillment_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    with Session(mysql_engine) as db:
        identity, target, batch = finance_rows[0]
        invoice = db.get(Invoice, identity)
        invoice.product_amount, invoice.total_amount, invoice.commerce_version = 1000, 1000, 1
        invoice.items[0].total_price, invoice.items[0].price_per_piece = 1000, 100
        db.flush()
        reserve_line(db, invoice.items[0].id, stock_ids[2], 10, "reserve", 1)
        finance_service.allocate(db, batch, AllocationCreate(request_key="allocate", expected_version=1,
            invoice_id=identity, receivable_id=target, amount=1000, business_date=DAY), USER)
        body = LocalShipmentQuote(business_date=DAY, warehouse_id=stock_ids[2],
            items=[dict(invoice_item_id=invoice.items[0].id, quantity=7)])
        quote = service.quote(db, identity, body, USER)
        row = service.create(db, identity, LocalShipmentCreate(**body.model_dump(), request_key="create",
            expected_version=1, quote_hash=quote["quote_hash"]), USER)
        service.act(db, row.id, LocalShipmentAction(request_key="ready", expected_version=1,
            business_date=DAY, reason="funded"), USER, "ready")
        outbound = db.scalar(select(ShipmentOutbound).where(ShipmentOutbound.settlement_id == row.id))
        inspection = inspection_service.get_or_create_draft(db, service.record_id(outbound), 1)
        db.add(ShippingInspectionPhoto(inspection_id=inspection.id, file_path="test.jpg", media_type="image"))
        db.flush()
        inspection_service.submit(db, outbound_record_id=service.record_id(outbound), user_id=1, commit=False)
        result = (row.id, inspection.id, row.version, inspection.edit_version)
        db.commit()
    return result


def shipping(values, key):
    return LocalShipmentAction(request_key=key, expected_version=values[2], inspection_version=values[3],
        business_date=DAY, reason="physically shipped")


def test_two_dispatch_commands_consume_stock_once(mysql_engine, fulfillment):
    results = compete(mysql_engine, [lambda db: service.act(db, fulfillment[0], shipping(fulfillment, "ship-one"), USER, "ship"),
                                    lambda db: service.act(db, fulfillment[0], shipping(fulfillment, "ship-two"), USER, "ship")])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 3
        assert len(db.scalars(select(StockDocument).where(StockDocument.kind == "sale_issue")).all()) == 1


def test_unreserved_production_dispatch_race_reserves_and_consumes_once(mysql_engine, fulfillment):
    with Session(mysql_engine) as db:
        row = db.get(ShipmentSettlement, fulfillment[0])
        invoice = db.get(Invoice, row.invoice_id)
        invoice.order_type = "production"
        item = invoice.items[0]
        from app.inventory.models import StockReservation
        responsibility = db.scalar(select(StockReservation).where(StockReservation.invoice_item_id == item.id))
        release_line(db, item.id, responsibility.warehouse_id, 10, "release-fixture", "unreserved native dispatch", 1)
        db.commit()
    results = compete(mysql_engine, [lambda db: service.act(db, fulfillment[0], shipping(fulfillment, "ship-one"), USER, "ship"),
                                    lambda db: service.act(db, fulfillment[0], shipping(fulfillment, "ship-two"), USER, "ship")])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 3
        assert db.scalar(select(StockBalance.reserved)) == 0
        assert len(db.scalars(select(StockDocument).where(StockDocument.kind == "sale_issue")).all()) == 1


def test_recall_and_dispatch_are_serialized(mysql_engine, fulfillment):
    results = compete(mysql_engine, [lambda db: service.act(db, fulfillment[0], shipping(fulfillment, "ship"), USER, "ship"),
                                    lambda db: inspection_service.recall(db, fulfillment[1], 1, fulfillment[3])])
    assert sorted(row[0] for row in results) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        shipment = db.get(ShipmentSettlement, fulfillment[0])
        inspection = db.get(ShippingInspection, fulfillment[1])
        assert (shipment.state, inspection.status) in {("shipped", "submitted"), ("ready", "draft")}
        assert db.scalar(select(StockBalance.on_hand)) == (3 if shipment.state == "shipped" else 10)


def test_old_rr_inspection_snapshot_cannot_dispatch_after_recall(mysql_engine, fulfillment):
    with Session(mysql_engine) as stale:
        assert stale.get(ShippingInspection, fulfillment[1]).status == "submitted"
        with Session(mysql_engine) as fresh:
            inspection_service.recall(fresh, fulfillment[1], 1, fulfillment[3])
        with pytest.raises(ValueError, match="检验"):
            service.act(stale, fulfillment[0], shipping(fulfillment, "ship-stale"), USER, "ship")
        stale.rollback()
    with Session(mysql_engine) as db:
        assert db.scalar(select(StockBalance.on_hand)) == 10
