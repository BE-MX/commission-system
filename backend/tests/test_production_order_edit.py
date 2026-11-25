"""Submitted legacy orders support atomic product and quantity changes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.database import get_db
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.models import Line, Note
from app.factory_inbound.recognition_service import queue_values
from app.mini.service import submit_report
from app.production.models import (
    OrderProductProcessProgress, Process, ProcessRoute, ProcessRouteStep, ProductProcessRoute, UserProcessBinding,
)
from app.production.report_service import generate_qr_data, handle_production_report
from app.stock.models import ProductionAuditLog, ProductionOrder, ProductionOrderItem
from app.stock.router import router

ROOT = "/stock/production/orders"
REPLACEMENT_ID = 9007199254740993


@pytest.fixture
def order_editor(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "legacy")
    db.execute(text("""
        CREATE TABLE lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY, name TEXT, cn_name TEXT, model TEXT, disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products VALUES
        (9007199254740993, 'Replacement/12/#1/#2/90g', '', 'R12', 0),
        (22, 'Extra/14/#2/100g', '', 'E14', 0),
        (23, 'Disabled', '', 'D15', 1)
    """))
    order = ProductionOrder(order_no="PO-EDIT", batch_no="EDIT", created_by=12)
    db.add(order)
    db.flush()
    rows = [
        ProductionOrderItem(order_id=order.id, product_id=product_id, product_name=name,
                            order_qty=quantity, model="original")
        for product_id, name, quantity in [(11, "Replace me", 5), (12, "Change quantity", 8), (13, "Keep me", 3)]
    ]
    db.add_all(rows)
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/stock")
    app.dependency_overrides[get_db] = lambda: db
    user = {"sub": "12", "roles": [], "permissions": ["production:read", "production:write"]}
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, order, rows, user


def _progress_route(db, name):
    process = Process(name=f"{name} step")
    route = ProcessRoute(name=name)
    db.add_all([process, route])
    db.flush()
    db.add(ProcessRouteStep(route_id=route.id, process_id=process.id, step_order=1))
    return route, process


def _change(item, qty, product_id=None):
    change = {"item_id": item.id, "expected_order_qty": item.order_qty, "order_qty": qty}
    if product_id is not None:
        change["product_id"] = str(product_id)
    return change


def test_order_edit_replaces_qty_and_appends_in_one_save(db, order_editor):
    client, order, (replace, resize, keep), _ = order_editor
    route, process = _progress_route(db, "Old route")
    new_route, new_process = _progress_route(db, "New route")
    old_card = generate_qr_data(replace.id)
    old_id = replace.id
    db.add_all([
        OrderProductProcessProgress(order_product_id=old_id, process_id=process.id,
                                    route_id=route.id, step_order=1, status=0),
        ProductProcessRoute(product_id=REPLACEMENT_ID, route_id=new_route.id),
    ])
    db.commit()
    url = f"{ROOT}/{order.id}"
    assert client.get(url).json()["data"]["items_editable"]
    payload = {
        "remark": "revised",
        "item_updates": [_change(replace, 7, REPLACEMENT_ID), _change(resize, 10)],
        "new_items": [{"product_id": "22", "order_qty": 4}],
    }
    response = client.put(url, json=payload)
    assert response.status_code == 200, response.text

    detail = client.get(url).json()["data"]
    by_product = {item["product_id"]: item for item in detail["items"]}
    assert (detail["remark"], detail["status"]) == ("revised", 0)
    assert set(by_product) == {12, 13, 22, REPLACEMENT_ID}
    assert by_product[12]["id"] == resize.id and by_product[12]["order_qty"] == 10
    assert by_product[13]["id"] == keep.id and by_product[13]["order_qty"] == 3
    assert by_product[22]["order_qty"] == 4
    changed = by_product[REPLACEMENT_ID]
    assert changed["id"] != old_id
    assert (changed["model"], changed["product_name"], changed["order_qty"], changed["received_qty"]) == (
        "R12", "Replacement/12/#1/#2/90g", 7, 0,
    )
    assert changed["spec_info"] == "Replacement/12/#1/#2/90g"
    assert db.get(ProductionOrderItem, old_id) is None
    assert not handle_production_report(db, old_card, "test-worker")["success"]
    assert not submit_report(db, progress_id=1, order_product_id=old_id, current_user=None)["success"]
    progress = db.scalars(select(OrderProductProcessProgress)).all()
    assert [(step.order_product_id, step.process_id) for step in progress] == [(changed["id"], new_process.id)]
    logs = db.scalars(select(ProductionAuditLog)).all()
    assert {log.action for log in logs} == {"update", "replace_product", "add_item"}
    replacement_log = next(log for log in logs if log.action == "replace_product")
    assert replacement_log.snapshot["previous_item_id"] == old_id
    assert client.put(url, json=payload).status_code == 400
    assert len(client.get(url).json()["data"]["items"]) == 4


@pytest.mark.parametrize("reason", ["received", "historical_receipt", "reported", "pending", "completed", "opening"])
def test_model_change_rejects_active_references_and_leaves_order_unchanged(db, order_editor, reason):
    client, order, (item, _, _), _ = order_editor
    if reason == "received":
        item.received_qty = 1
    if reason == "historical_receipt":
        db.add(ProductionAuditLog(order_id=order.id, item_id=item.id, operator_id=12, operator_name="test",
                                  action="update_received", snapshot={"old_received": 1, "new_received": 0}))
    if reason == "reported":
        route, process = _progress_route(db, "Reported route")
        db.add(OrderProductProcessProgress(order_product_id=item.id, process_id=process.id,
                                           route_id=route.id, step_order=1, status=1))
    if reason == "pending":
        note = Note(inbound_no="FI-EDIT", factory_code="fixture", scan_path="test.jpg",
                    created_by=12, **queue_values())
        db.add(note)
        db.flush()
        line = Line(note_id=note.id, line_no=1, raw={}, values={}, match_status='matched', match_data={}, created_by=12)
        batch = Batch(note_id=note.id, batch_no="EDIT-PENDING", idempotency_key="edit-pending",
                      confirmed_by=12, request_snapshot={}, plan_snapshot={})
        db.add_all([line, batch])
        db.flush()
        db.add(Allocation(batch_id=batch.id, line_id=line.id, target_kind="production_item",
                          target_id=item.id, quantity=1, target_snapshot={}))
    if reason == "completed":
        order.status = 2
    if reason == "opening":
        order.transaction_mode = "opening"
    db.commit()
    response = client.put(f"{ROOT}/{order.id}", json={
        "remark": "must roll back", "item_updates": [_change(item, 7, REPLACEMENT_ID)],
        "new_items": [{"product_id": "22", "order_qty": 4}],
    })
    assert response.status_code == 400, response.text
    assert order.remark is None and item.product_id == 11
    assert db.scalar(select(ProductionOrderItem.id).where(ProductionOrderItem.product_id == 22)) is None


def test_quantity_floor_stale_edits_duplicate_and_inactive_products(db, order_editor):
    client, order, (item, _, _), user = order_editor
    url = f"{ROOT}/{order.id}"
    item.received_qty = 2
    db.commit()
    cases = [
        ({"item_updates": [_change(item, 1)]}, "已入库数量"),
        ({"item_updates": [{**_change(item, 3), "expected_order_qty": 9}]}, "已变化"),
        ({"new_items": [{"product_id": "23", "order_qty": 1}]}, "停用"),
    ]
    for payload, expected in cases:
        response = client.put(url, json=payload)
        assert response.status_code == 400 and expected in response.json()["detail"]
    add = {"new_items": [{"product_id": "22", "order_qty": 1}]}
    assert client.put(url, json=add).status_code == 200
    response = client.put(url, json=add)
    assert response.status_code == 400 and "已在订单中" in response.json()["detail"]
    assert client.put(url, json={"item_updates": [_change(item, 4)]}).status_code == 200
    assert item.order_qty == 4 and item.received_qty == 2
    user["permissions"] = ["production:read"]
    assert client.put(url, json=add).status_code == 403


def test_submitted_mini_report_cannot_be_discarded_by_model_change(db, order_editor):
    client, order, (item, _, _), _ = order_editor
    route, process = _progress_route(db, "First process")
    second = Process(name="Second process")
    worker = ArkUser(username="order-edit-worker", real_name="Worker", password_hash="fixture", wx_id="worker")
    db.add_all([second, worker])
    db.flush()
    first_step = OrderProductProcessProgress(order_product_id=item.id, process_id=process.id,
                                             route_id=route.id, step_order=1, status=0)
    next_step = OrderProductProcessProgress(order_product_id=item.id, process_id=second.id,
                                            route_id=route.id, step_order=2, status=0)
    db.add_all([first_step, next_step, UserProcessBinding(user_id=worker.id, process_id=process.id)])
    db.commit()

    result = submit_report(db, first_step.id, item.id, worker)
    assert result["success"] and not result["all_done"]
    db.commit()
    response = client.put(f"{ROOT}/{order.id}", json={
        "item_updates": [_change(item, item.order_qty, REPLACEMENT_ID)],
    })
    assert response.status_code == 400 and "已有工序报工" in response.json()["detail"]
    assert item.status == 0
    assert first_step.status == 1 and next_step.status == 0
