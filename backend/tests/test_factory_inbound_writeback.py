from dataclasses import asdict

import pytest
from sqlalchemy import func, select

from app.factory_inbound.allocation_plan import PlanLine, Target, plan_allocations
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.matching_rules import Candidate
from app.factory_inbound.models import Line, Note
from app.factory_inbound.purchase_readback import PurchaseReadbackError
from app.factory_inbound.recognition_service import queue_values
from app.factory_inbound.writeback_service import WritebackConflict, apply_writeback, record_completed_readback
from app.stock.models import ProductionAuditLog, ProductionOrder, ProductionOrderItem


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    rows = [Candidate(100 + i, 200 + i, 'Fixture', '22', '#4', '20g') for i in (1, 2)]
    monkeypatch.setattr('app.factory_inbound.writeback_service.load_catalog', lambda db: rows)
    return rows


def build_batch(db, *, quantities=(3,)):
    order = ProductionOrder(order_no="PO-FIXTURE", batch_no="#20261184", created_by=1)
    note = Note(inbound_no="FI-FIXTURE", factory_code="fixture", scan_path="test.jpg", created_by=1,
                **queue_values())
    db.add_all([order, note])
    db.flush()
    plan_lines = []
    targets = []
    items = []
    for idx, qty in enumerate(quantities, 1):
        item = ProductionOrderItem(order_id=order.id, product_id=100 + idx, product_name="Fixture",
                                   order_qty=qty, received_qty=0)
        line = Line(note_id=note.id, line_no=idx, raw={}, values={}, match_status="matched",
                    match_data={}, created_by=1)
        db.add_all([item, line])
        db.flush()
        plan_lines.append(PlanLine(line.id, item.product_id, 200 + idx, qty, "order", "production_order", order.id))
        targets.append(Target("production_item", item.id, order.id, item.product_id, 200 + idx, qty, order.created_at))
        items.append(item)

    request = {
        "invoice_warehouse_id": 12, "supplier_id": 33, "currency": "USD", "remark": "FI-FIXTURE-1",
        "record_list": [{"product_id": line.product_id, "sku_id": line.sku_id,
                         "inbound_count": line.quantity, "purchase_price": 1} for line in plan_lines],
    }
    batch = Batch(note_id=note.id, batch_no="FI-FIXTURE-1", idempotency_key="local-fixture", confirmed_by=1,
                  sync_status="drafted", request_snapshot=request, plan_snapshot=[asdict(line) for line in plan_lines])
    db.add(batch)
    db.flush()
    for line, plan in zip(plan_lines, plan_allocations(plan_lines, targets), strict=True):
        db.get(Line, line.id).batch_id = batch.id
        for target in plan["allocations"]:
            db.add(Allocation(
                batch_id=batch.id, line_id=line.id, target_kind=target["target_kind"], target_id=target["target_id"],
                quantity=target["quantity"], target_snapshot={
                    "order_id": target["order_id"], "product_id": line.product_id, "sku_id": line.sku_id,
                },
            ))
    db.commit()
    return batch, order, items


def complete(db, batch, status=2):
    request = batch.request_snapshot
    response = {
        **request, "inbound_invoice_id": 412, "serial_id": "CGRK412", "status": status, "type": 28, "delete_flag": 0,
        "record_list": [{**line, "warehouse_id": request["invoice_warehouse_id"]} for line in request["record_list"]],
    }
    record_completed_readback(db, batch.id, response, inbound_id=412, serial_id="CGRK412")


def test_done_readback_and_repeated_writeback_increment_once(db):
    batch, order, items = build_batch(db, quantities=(2, 3))
    complete(db, batch)
    db.commit()
    assert batch.writeback_status == "pending"
    assert order.status == 0
    assert [item.received_qty for item in items] == [0, 0]
    for _ in range(2):
        assert apply_writeback(db, batch.id, operator_name="仓库测试").writeback_status == "done"
        db.commit()
    assert order.status == 2
    assert [(item.received_qty, item.status) for item in items] == [(2, 2), (3, 2)]
    assert list(db.scalars(select(Allocation.status))) == ["applied", "applied"]
    assert db.scalar(select(func.count(ProductionAuditLog.id))) == 2


def test_draft_is_not_a_proof_for_writeback(db):
    batch, _, items = build_batch(db)
    with pytest.raises(PurchaseReadbackError, match="已完成"):
        complete(db, batch, status=1)
    db.rollback()
    with pytest.raises(WritebackConflict, match="完成凭据"):
        apply_writeback(db, batch.id, operator_name="仓库测试")
    db.rollback()
    assert items[0].received_qty == 0
    assert batch.sync_status == "drafted"


def test_cross_writeback_reassigns_an_invalid_target_and_fills_confirmed_remainder(db):
    batch, _, items = build_batch(db, quantities=(5,))
    original, = items
    batch.plan_snapshot = [{**batch.plan_snapshot[0], "route": "cross", "order_kind": None, "order_id": None}]
    held = db.scalar(select(Allocation).where(Allocation.batch_id == batch.id))
    held.quantity = 2
    original.status = 1
    order = ProductionOrder(order_no="PO-OTHER-FIXTURE", batch_no="#20261185", created_by=1)
    db.add(order)
    db.flush()
    normal = ProductionOrderItem(order_id=order.id, product_id=101, product_name="Fixture", order_qty=5)
    urgent = ProductionOrderItem(order_id=order.id, product_id=101, product_name="Fixture", order_qty=3, is_urgent=1)
    db.add_all([normal, urgent])
    db.flush()
    complete(db, batch)
    db.commit()

    for _ in range(2):
        assert apply_writeback(db, batch.id, operator_name="仓库测试").writeback_status == "done"
        db.commit()

    assert (original.received_qty, normal.received_qty, urgent.received_qty) == (0, 2, 3)
    assert held.status == "released"
    applied = db.scalars(select(Allocation).where(Allocation.status == "applied"))
    assert {row.target_id: row.quantity for row in applied} == {normal.id: 2, urgent.id: 3}


def test_a_line_must_be_held_by_the_confirmed_batch(db):
    batch, _, items = build_batch(db)
    complete(db, batch)
    db.commit()
    line = db.scalar(select(Line).where(Line.batch_id == batch.id))
    line.batch_id = None
    db.commit()
    with pytest.raises(WritebackConflict, match="批次归属"):
        apply_writeback(db, batch.id, operator_name="仓库测试")
    db.rollback()
    assert items[0].received_qty == 0
    assert batch.writeback_status == "pending"


def test_an_additional_sku_blocks_applying_quantities_to_unresolved_product(db, catalog):
    batch, _, items = build_batch(db)
    complete(db, batch)
    db.commit()
    catalog.append(Candidate(101, 898, "Alternate fixture", "22", "#4", "20g"))
    with pytest.raises(WritebackConflict, match="不再唯一"):
        apply_writeback(db, batch.id, operator_name="仓库测试")
    db.rollback()
    assert items[0].received_qty == 0
    assert batch.sync_status == "synced"


def test_failed_order_application_keeps_remote_completion_without_partial_effects(db):
    batch, order, items = build_batch(db, quantities=(2, 3))
    complete(db, batch)
    db.commit()
    items[1].status = 1
    db.commit()
    with pytest.raises(WritebackConflict, match="已失效"):
        apply_writeback(db, batch.id, operator_name="仓库测试")
    db.rollback()
    assert order.status == 0
    assert items[0].received_qty == 0
    assert list(db.scalars(select(Allocation.status))) == ["pending", "pending"]
    assert db.scalar(select(func.count(ProductionAuditLog.id))) == 0
    assert batch.sync_status == "synced"
    assert batch.writeback_status == "pending"
    assert batch.completion_evidence["inbound_invoice_id"] == 412
