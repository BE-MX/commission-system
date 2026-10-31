"""Actual migration177 plus production/material races on isolated MySQL."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, Table, String, select
from sqlalchemy.orm import Session
from app.production import local_service as service
from app.production.local_models import ProductionSupply, ProductionMaterial
from app.production.local_schemas import ProductionCreate, ProductionLine, QuantityCommand, ReceiptCreate, SupplyCreate, MaterialCommand
from app.production.models import ProcessRoute, OrderProductProcessProgress
from app.stock.models import ProductionOrder, ProductionOrderItem
from app.invoice.models import InvoiceItem
from app.inventory.models import StockBalance
from app.catalog.models import CatalogProduct
from app.semifinished.models import SemifinishedMaterial, InventoryBalance, InventoryLedger
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_stock_reservations_mysql import orders, compete

USER = {"sub": "1", "roles": ["super_admin"]}


@pytest.fixture
def production_rows(mysql_engine, stock_ids, orders):
    previous = MetaData()
    added = {"transaction_mode", "local_sku_id", "process_route_id", "completed_qty", "supplied_qty", "supplied_received_qty", "local_version", "local_event_id"}
    for model in (ProductionOrder, ProductionOrderItem, ProcessRoute, OrderProductProcessProgress, SemifinishedMaterial, InventoryBalance, InventoryLedger):
        Table(model.__tablename__, previous, *[
            Column(col.name, String(100) if model is ProductionOrderItem and col.name == "model" else
                   String(255) if model is ProductionOrderItem and col.name == "product_name" else col.type,
                   primary_key=col.primary_key, autoincrement=col.autoincrement, unique=bool(col.unique),
                   nullable=False if model is ProductionOrderItem and col.name == "product_id" else col.nullable,
                   server_default=col.server_default)
            for col in model.__table__.columns if col.name not in added])
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("INSERT INTO ark_users(id) VALUES (1)")
        # The shared reservation fixture includes later scalar ORM columns for
        # test compatibility; restore the exact pre177 boundary for this test.
        conn.exec_driver_sql("ALTER TABLE ark_invoice_items DROP COLUMN production_pending_quantity")
        path = Path(__file__).parents[1] / "alembic/versions/211_local_production.py"
        spec = spec_from_file_location("production_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    ids = []
    with Session(mysql_engine) as db:
        product = db.get(CatalogProduct, stock_ids[0])
        product.name, product.model = "N" * 512, "M" * 200
        for index in range(2):
            row = service.create(db, ProductionCreate(request_key=f"production-{index}", batch_no=f"P{index}",
                items=[ProductionLine(local_sku_id=stock_ids[1], quantity=10)]), USER)
            ids.append(db.scalar(select(ProductionOrderItem.id).where(ProductionOrderItem.order_id == row.id)))
        db.commit()
    return ids


def test_two_receipts_cannot_receive_same_completed_units(mysql_engine, stock_ids, production_rows):
    item_id = production_rows[0]
    with Session(mysql_engine) as db:
        service.complete(db, item_id, QuantityCommand(request_key="done", expected_version=1, quantity=10, reason="done"), USER)
        db.commit()
    def body(key):
        return ReceiptCreate(request_key=key, expected_version=2, quantity=7, warehouse_id=stock_ids[2], reason="accepted")
    result = compete(mysql_engine, [lambda db: service.receive(db, item_id, body("receive-1"), USER),
                                    lambda db: service.receive(db, item_id, body("receive-2"), USER)])
    assert sorted(x[0] for x in result) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(ProductionOrderItem, item_id).received_qty == 7
        assert db.scalar(select(StockBalance.on_hand)) == 17  # fixture opening10 plus accepted7


def test_two_production_orders_cannot_overpromise_one_sales_line(mysql_engine, production_rows, orders):
    result = compete(mysql_engine, [
        lambda db, identity=identity: service.link_supply(db, identity,
            SupplyCreate(request_key=f"link-{identity}", expected_version=1, quantity=7,
                         invoice_item_id=orders[0], reason="planned"), USER) for identity in production_rows])
    assert sorted(x[0] for x in result) == ["ok", "rejected"]
    with Session(mysql_engine) as db:
        assert db.get(InvoiceItem, orders[0]).production_pending_quantity == 7
        assert len(db.scalars(select(ProductionSupply)).all()) == 1


def test_unrelated_first_supply_rows_do_not_gap_deadlock(mysql_engine, production_rows, orders):
    result = compete(mysql_engine, [
        lambda db, identity=identity, sale=sale: service.link_supply(db, identity,
            SupplyCreate(request_key=f"link-{identity}", expected_version=1, quantity=7,
                         invoice_item_id=sale, reason="planned"), USER) for identity, sale in zip(production_rows, orders)])
    assert [x[0] for x in result] == ["ok", "ok"]


@pytest.mark.parametrize("shared", [True, False])
def test_material_issues_serialize_and_distinct_pairs_do_not_gap_deadlock(mysql_engine, production_rows, shared):
    with Session(mysql_engine) as db:
        material_ids = []
        for index in range(2):
            material = SemifinishedMaterial(material_code=f"M{index}", size="20", color_code=f"C{index}", color_key=f"c{index}")
            db.add(material)
            db.flush()
            db.add(InventoryBalance(material_id=material.id, on_hand_grams=70, reserved_grams=0))
            material_ids.append(material.id)
        db.commit()
    actions = [lambda db, index=index: service.material(db, production_rows[index], "issue",
        MaterialCommand(request_key=f"issue-{index}", expected_version=1, material_id=material_ids[0 if shared else index],
                        quantity_grams=50, reason="issued"), USER) for index in range(2)]
    result = compete(mysql_engine, actions)
    assert sorted(x[0] for x in result) == (["ok", "rejected"] if shared else ["ok", "ok"])
    with Session(mysql_engine) as db:
        assert all(value >= 0 for value in db.scalars(select(InventoryBalance.on_hand_grams)))
        assert len(db.scalars(select(ProductionMaterial)).all()) == (1 if shared else 2)
