"""Permanent MySQL regressions from independent production review."""
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.schema import CreateColumn
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.catalog.models import CatalogProduct
from app.production import local_service as service
from app.production.local_schemas import Action, MaterialCommand, ProductionCreate, ProductionLine, QuantityCommand, SupplyCreate, ReceiptCreate, ReceiptAllocation
from app.production.local_models import ProductionEvent, ProductionSupply
from app.production.local_receipt_service import reverse_receipt
from app.inventory.models import StockBalance, StockDocument
from app.inventory.reservation_service import reserve_line, consume_line
from app.invoice.models import InvoiceItem
from app.production.models import Process, ProcessRoute, ProcessRouteStep, OrderProductProcessProgress, UserProcessBinding
from app.production.report_service import generate_qr_data, init_order_product_progress
from app.semifinished.models import SemifinishedMaterial, InventoryBalance
from app.stock.models import ProductionOrderItem
from tests.test_inventory_mysql import mysql_engine, stock_ids
from tests.test_stock_reservations_mysql import orders
from tests.test_production_mysql import production_rows, USER



def test_authenticated_scan_uses_current_steps_and_guards_acceptance(mysql_engine, stock_ids, production_rows):
    engine, ids, lines = mysql_engine, stock_ids, production_rows
    with engine.begin() as conn:
        # MySQL fixture uses a minimal ark_users prerequisite. Add only its real
        # ORM columns so the actual scanner can resolve a worker without mocks.
        for column in ArkUser.__table__.columns:
            if column.name != "id":
                ddl = str(CreateColumn(Column(column.name, column.type, nullable=True)).compile(dialect=conn.dialect))
                conn.exec_driver_sql("ALTER TABLE ark_users ADD COLUMN " + ddl)
        for table in [Process.__table__, ProcessRouteStep.__table__, OrderProductProcessProgress.__table__, UserProcessBinding.__table__]:
            table.create(conn, checkfirst=True)
        # Authentication prerequisites have historical signedness differences in
        # this partial fixture, so preserve their columns without unrelated FKs.
        auth_metadata = MetaData()
        for model in [ArkRole, ArkPermission, ArkUserRole, ArkRolePermission]:
            Table(model.__tablename__, auth_metadata, *[
                Column(col.name, col.type, primary_key=col.primary_key, nullable=col.nullable)
                for col in model.__table__.columns])
        auth_metadata.create_all(conn)
    with Session(engine) as db:
        worker = db.get(ArkUser, 1)
        worker.wx_id = "review-worker"
        worker.username, worker.real_name, worker.password_hash = "review", "Review", "unused"
        worker.is_active = True
        process1, process2 = Process(name="First"), Process(name="Final")
        route = ProcessRoute(name="Review route")
        db.add_all([process1, process2, route])
        db.flush()
        for index, process in enumerate([process1, process2], 1):
            db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=index))
            db.add(UserProcessBinding(user_id=1, process_id=process.id))
        item = db.get(ProductionOrderItem, lines[0])
        item.process_route_id = route.id
        db.flush()
        init_order_product_progress(db, item.id, _native_new=True)
        progress_ids = db.scalars(select(OrderProductProcessProgress.id).where(
            OrderProductProcessProgress.order_product_id == item.id).order_by(OrderProductProcessProgress.step_order)).all()
        db.commit()
    qr = generate_qr_data(lines[0])
    with Session(engine) as stale:
        stale.get(ProductionOrderItem, lines[0])  # establishes snapshot before first scan
        with Session(engine) as writer:
            from app.mini.service import submit_report
            first = submit_report(writer, progress_ids[0], lines[0], writer.get(ArkUser, 1))
            assert first["success"]
            writer.commit()
        final = submit_report(stale, progress_ids[1], lines[0], stale.get(ArkUser, 1))
        assert final["all_done"]
        stale.commit()
        print("final scan returned:", final["success"], final.get("all_done", final.get("data", {}).get("all_completed")))
    with Session(engine) as db:
        item = db.get(ProductionOrderItem, lines[0])
        states = db.scalars(select(OrderProductProcessProgress.status).order_by(OrderProductProcessProgress.step_order)).all()
        print("committed process states=", states, "completed_qty=", item.completed_qty)
        assert states == [1, 1]
        assert item.completed_qty == item.order_qty, "Final scan left manufacturing incomplete after all processes completed"
        from app.mini.service import revoke_report, get_today_history, scan_product
        worker = db.get(ArkUser, 1)
        version = item.local_version
        assert submit_report(db, progress_ids[1], item.id, worker)["success"]
        assert item.local_version == version
        assert get_today_history(db, 1)["today_count"] == 2
        service.receive(db, item.id, ReceiptCreate(request_key="scan-receive", expected_version=item.local_version,
            quantity=1, warehouse_id=ids[2], reason="accepted"), USER)
        receipt = db.scalar(select(ProductionEvent).where(ProductionEvent.request_key == "scan-receive"))
        assert not revoke_report(db, progress_ids[1], worker)["success"]
        assert item.completed_qty == 10 and item.received_qty == 1
        reverse_receipt(db, receipt.id, Action(request_key="scan-reverse", expected_version=item.local_version,
            reason="wrong acceptance"), USER)
        assert revoke_report(db, progress_ids[1], worker)["success"]
        assert item.completed_qty == item.received_qty == 0
        preview = scan_product(db, item.id, qr.split(":")[-1], worker)
        assert preview["can_submit"]
        assert submit_report(db, progress_ids[1], item.id, worker)["success"]
        assert item.completed_qty == 10
        db.commit()
        print("authenticated retry/history/preview plus receipt-protected revoke and resubmit passed without mirror tables")
        from fastapi import HTTPException
        from app.stock.router import reset_order_process
        from app.stock.production_order_service import get_order_item_list, get_order_detail
        order_id = item.order_id
        try:
            reset_order_process(order_id, db=db, user=USER)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Legacy reset accepted a local production order")
        assert db.scalars(select(OrderProductProcessProgress.status).order_by(OrderProductProcessProgress.step_order)).all() == [1, 1]
        assert len(get_order_item_list(db)["items"]) == 2
        assert get_order_detail(db, order_id)["id"] == order_id
        print("legacy reset refused without deleting progress; mixed production list/detail accepted null external product IDs")




def test_allocated_receipt_reversal_rolls_back_all_releases(mysql_engine, stock_ids, production_rows):
    engine, ids, lines = mysql_engine, stock_ids, production_rows
    with Session(engine) as db:
        item = db.get(ProductionOrderItem, lines[0])
        sales = db.scalars(select(InvoiceItem).order_by(InvoiceItem.id)).all()
        supplies = [service.link_supply(db, item.id, SupplyCreate(request_key=f"supply-{index}",
            expected_version=item.local_version, quantity=5, invoice_item_id=sale.id, reason="planned"), USER)
            for index, sale in enumerate(sales)]
        service.complete(db, item.id, QuantityCommand(request_key="complete", expected_version=item.local_version,
            quantity=10, reason="completed"), USER)
        service.receive(db, item.id, ReceiptCreate(request_key="receive", expected_version=item.local_version,
            quantity=10, warehouse_id=ids[2], reason="accepted", allocations=[
                ReceiptAllocation(supply_id=supply.id, quantity=5) for supply in supplies]), USER)
        event = db.scalar(select(ProductionEvent).where(ProductionEvent.action == "receive"))
        consume_line(db, sales[1].id, ids[2], 1, "ship-second", "shipment-review", 1)
        db.flush()
        document_count = len(db.scalars(select(StockDocument)).all())
        command = Action(request_key="reverse", expected_version=item.local_version, reason="wrong acceptance")
        try:
            reverse_receipt(db, event.id, command, USER)
        except ValueError as exc:
            assert "预占不足" in str(exc)
        else:
            raise AssertionError("Reversal ignored insufficient second sales reservation")
        assert item.received_qty == item.supplied_received_qty == 10
        assert [sale.stock_reserved_quantity for sale in sales] == [5, 4]
        assert [sale.production_pending_quantity for sale in sales] == [0, 0]
        assert [supply.received_quantity for supply in supplies] == [5, 5]
        assert len(db.scalars(select(StockDocument)).all()) == document_count
        assert not db.scalars(select(ProductionEvent).where(ProductionEvent.action == "reverse_receipt")).all()
        print("second allocation failure rolled back first release, all counters and command facts")
        reserve_line(db, sales[1].id, ids[2], 1, "replace-public-reservation", 1)
        reverse_receipt(db, event.id, command, USER)
        reverse_receipt(db, event.id, command, USER)
        assert item.received_qty == item.supplied_received_qty == 0
        assert item.completed_qty == 10
        assert [sale.stock_reserved_quantity for sale in sales] == [0, 0]
        assert [sale.production_pending_quantity for sale in sales] == [5, 5]
        assert [supply.received_quantity for supply in supplies] == [0, 0]
        assert len(db.scalars(select(ProductionEvent).where(ProductionEvent.action == "reverse_receipt")).all()) == 1
        assert db.scalar(select(StockBalance.on_hand)) == 9
        db.commit()
        print("allocated reversal retry restored both pending supplies and deducted stock exactly once")
