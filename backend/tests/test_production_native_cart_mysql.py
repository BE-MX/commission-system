"""Native cart first writers on actual 187 DDL in isolated MySQL RR."""
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Index, MetaData, String, Table, UniqueConstraint, event, func, select
from sqlalchemy.orm import Session

from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockLedger
from app.production.local_models import ProductionEvent, ProductionSupply
from app.production.models import ProcessRoute
from app.semifinished.models import CartPlan, SemifinishedMaterial, SemifinishedOrder, SemifinishedOrderItem
from app.stock import local_cart_service as cart
from app.stock.models import ProductionCart, ProductionOrder, ProductionOrderItem
from app.stock.schemas import OrderCreateRequest
from tests.test_inventory_mysql import mysql_engine, stock_ids


@pytest.fixture
def native_carts(mysql_engine, stock_ids):
    # Keep all cart fields and indexes, restoring only the pre-187 boundary.
    # The actual migration supplies the native key, FK and widened snapshots.
    previous = MetaData()
    Table(ProductionCart.__tablename__, previous, *[
        Column(column.name,
               String(255) if column.name == "product_name" else
               String(100) if column.name == "model" else column.type,
               primary_key=column.primary_key, autoincrement=column.autoincrement,
               nullable=False if column.name == "product_id" else column.nullable,
               server_default=column.server_default)
        for column in ProductionCart.__table__.columns if column.name != "local_sku_id"
    ], UniqueConstraint("user_id", "product_id", name="uk_cart_user_product"),
       Index("idx_production_cart_user_id", "user_id"))
    with mysql_engine.begin() as conn:
        previous.create_all(conn)
        conn.exec_driver_sql("""CREATE TABLE ark_safety_stock (
            id INT PRIMARY KEY AUTO_INCREMENT, product_id BIGINT NOT NULL UNIQUE,
            safety_stock INT NOT NULL DEFAULT 0, lead_time_days SMALLINT NOT NULL DEFAULT 30,
            safety_factor DECIMAL(4,2) NOT NULL DEFAULT 1.5, source SMALLINT NOT NULL DEFAULT 0,
            updated_by INT NOT NULL, updated_at DATETIME NOT NULL, created_at DATETIME NOT NULL)""")
        conn.exec_driver_sql("ALTER TABLE ark_users ADD is_active TINYINT NOT NULL DEFAULT 1, ADD deleted_at DATETIME NULL")
        conn.exec_driver_sql("INSERT INTO ark_users(id) VALUES (1),(2)")
        spec = spec_from_file_location("native_cart_migration",
            Path(__file__).parents[1] / "alembic/versions/221_local_replenishment.py")
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        SemifinishedMaterial.__table__.create(conn)
        CartPlan.__table__.create(conn)
    with Session(mysql_engine) as db:
        product = CatalogProduct(code="P2", name="Second", display_name="Second")
        db.add(product)
        db.flush()
        sku = CatalogSku(product_id=product.id, code="S2")
        materials = [SemifinishedMaterial(material_code=f"M{index}", size="18",
            color_code=f"C{index}", color_key=f"c{index}") for index in (1, 2)]
        db.add_all([sku, *materials])
        db.flush()
        identities = [(1, stock_ids[1], materials[0].id), (2, sku.id, materials[1].id)]
        db.commit()
    return identities


def _first_adds(engine, identities, *, plans):
    gate = Barrier(2)
    target = "ark_semifinished_cart_plans" if plans else "ark_production_cart"

    def synchronize_inserts(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {target} "):
            gate.wait(timeout=10)

    def add(identity):
        user_id, sku_id, material_id = identity
        with Session(engine) as db:
            return cart.add(db, user_id, f"ark:sku:{sku_id}", 2, "native race",
                [{"material_id": material_id, "quantity_grams": "20"}] if plans else [])

    event.listen(engine, "before_cursor_execute", synchronize_inserts)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(add, identities))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_inserts)


def test_different_users_first_adds_do_not_gap_deadlock(mysql_engine, native_carts):
    results = _first_adds(mysql_engine, native_carts, plans=False)
    assert [result["action"] for result in results] == ["created", "created"]
    with Session(mysql_engine) as db:
        rows = db.scalars(select(ProductionCart).order_by(ProductionCart.user_id)).all()
        assert [(row.user_id, row.local_sku_id, row.order_qty) for row in rows] == [
            (user_id, sku_id, 2) for user_id, sku_id, _ in native_carts]
        for user_id, sku_id, _ in native_carts:
            assert [item["local_sku_id"] for item in cart.list_items(db, user_id)] == [sku_id]


@pytest.mark.parametrize("existing_cart", [False, True])
def test_different_users_first_material_plans_do_not_gap_deadlock(mysql_engine, native_carts, existing_cart):
    if existing_cart:
        for user_id, sku_id, _ in native_carts:
            with Session(mysql_engine) as db:
                cart.add(db, user_id, f"ark:sku:{sku_id}", 1, None, [])
    results = _first_adds(mysql_engine, native_carts, plans=True)
    assert [result["action"] for result in results] == ["updated" if existing_cart else "created"] * 2
    with Session(mysql_engine) as db:
        plans = db.execute(select(ProductionCart.user_id, CartPlan.material_id, CartPlan.quantity_grams)
            .join(CartPlan, CartPlan.production_cart_id == ProductionCart.id)
            .order_by(ProductionCart.user_id)).all()
        assert [tuple(row) for row in plans] == [
            (user_id, material_id, 20) for user_id, _, material_id in native_carts]


def test_stale_snapshot_replaces_current_cart_and_material_plans(mysql_engine, native_carts):
    user_id, sku_id, material_id = native_carts[0]
    other_material_id = native_carts[1][2]
    with Session(mysql_engine) as stale:
        assert stale.scalar(select(ProductionCart.id)) is None
        assert stale.scalar(select(CartPlan.id)) is None
        with Session(mysql_engine) as writer:
            original = cart.add(writer, user_id, f"ark:sku:{sku_id}", 3, None, [
                {"material_id": material_id, "quantity_grams": "30"},
                {"material_id": other_material_id, "quantity_grams": "15"}])
        updated = cart.add(stale, user_id, f"ark:sku:{sku_id}", 5, "replacement", [
            {"material_id": material_id, "quantity_grams": "50"}])
        assert updated == {"id": original["id"], "action": "updated"}
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(ProductionCart)) == 1
        assert db.get(ProductionCart, original["id"]).order_qty == 5
        assert [tuple(row) for row in db.execute(select(CartPlan.material_id, CartPlan.quantity_grams))] == [(material_id, 50)]


@pytest.fixture
def checkout(mysql_engine, native_carts):
    # Current production schema is the structural prerequisite here; migration
    # 177 itself is exercised by test_production_mysql. Keep actual FK/uniques.
    with mysql_engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE ark_invoice_items (id BIGINT PRIMARY KEY)")
        for model in (ProcessRoute, ProductionOrder, ProductionOrderItem, ProductionSupply,
                      ProductionEvent, SemifinishedOrder, SemifinishedOrderItem):
            model.__table__.create(conn)
    user_id, sku_id, material_id = native_carts[0]
    with Session(mysql_engine) as db:
        added = cart.add(db, user_id, f"ark:sku:{sku_id}", 3, None,
            [{"material_id": material_id, "quantity_grams": "30"}])
    body = OrderCreateRequest(cart_ids=[added["id"]], batch_no="NATIVE-CHECKOUT", request_key="cart-checkout")
    return body, {"sub": str(user_id), "roles": ["super_admin"]}, material_id


def test_same_key_concurrent_checkout_replays_after_old_snapshot(mysql_engine, checkout):
    body, user, _ = checkout
    gate = Barrier(2)

    def create():
        with Session(mysql_engine) as db:
            assert db.scalar(select(ProductionOrder.id)) is None
            gate.wait(timeout=10)
            result = cart.create_order(db, body, user)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert results[0] == results[1]
    with Session(mysql_engine) as db:
        assert db.scalar(select(func.count()).select_from(ProductionOrder)) == 1
        assert db.scalar(select(func.count()).select_from(SemifinishedOrder)) == 1
        assert db.scalar(select(func.count()).select_from(ProductionCart)) == 0
        line = db.scalar(select(ProductionOrderItem))
        assert (line.order_qty, line.completed_qty, line.received_qty) == (3, 0, 0)
        assert db.scalar(select(func.count()).select_from(StockLedger)) == 0


def test_checkout_cannot_consume_another_users_cart(mysql_engine, checkout):
    body, _, _ = checkout
    with Session(mysql_engine) as db:
        with pytest.raises(ValueError, match="明细已变化"):
            cart.create_order(db, body, {"sub": "2", "roles": ["super_admin"]})
        assert db.scalar(select(func.count()).select_from(ProductionCart)) == 1
        assert db.scalar(select(func.count()).select_from(ProductionOrder)) == 0
        assert db.scalar(select(func.count()).select_from(ProductionEvent)) == 0


def test_material_failure_rolls_back_checkout_and_events(mysql_engine, checkout):
    body, user, material_id = checkout
    with Session(mysql_engine) as db:
        db.get(SemifinishedMaterial, material_id).status = "inactive"
        db.commit()
        with pytest.raises(ValueError, match="半成品"):
            cart.create_order(db, body, user)
        assert db.scalar(select(func.count()).select_from(ProductionCart)) == 1
        assert db.scalar(select(func.count()).select_from(ProductionOrder)) == 0
        assert db.scalar(select(func.count()).select_from(SemifinishedOrder)) == 0
        assert db.scalar(select(func.count()).select_from(ProductionEvent)) == 0
        assert db.scalar(select(func.count()).select_from(StockLedger)) == 0
