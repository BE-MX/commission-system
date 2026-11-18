import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.models import ArkUser, ArkUserExternalBinding
from app.core.config import get_settings
from app.factory_inbound import batch_prepare, matching_service
from app.factory_inbound.batch_models import Allocation, Batch
from app.factory_inbound.matching_rules import Candidate
from app.factory_inbound.models import Alias, Line, LineType, Note
from app.factory_inbound.recognition_service import queue_values
from app.factory_inbound.schemas import ConfirmBatch, PreviewBatch
from app.stock import production_order_service as production
from app.stock.models import ProductionOrder, ProductionOrderItem


@pytest.fixture
def reviewed_note(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "OKKI_CLIENT_ID", "warehouse-fixture")
    monkeypatch.setattr(settings, "FACTORY_INBOUND_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "FACTORY_INBOUND_OKKI_SUPPLIER_ID", 33)
    monkeypatch.setattr(settings, "FACTORY_INBOUND_OKKI_WAREHOUSE_ID", 12)
    monkeypatch.setattr(settings, "FACTORY_INBOUND_OKKI_PURCHASING_STATUS_ID", 2)
    monkeypatch.setattr(settings, "TRANSACTION_MODE", "legacy")
    catalog = [Candidate(101, 201, "Genius Weft", '22', '#4', '20g'),
               Candidate(102, 202, "Genius Weft", '22', '#6', '20g')]
    monkeypatch.setattr(matching_service, "load_catalog", lambda db: catalog)
    user = ArkUser(username="fixture-warehouse", password_hash="fixture", real_name="仓库测试")
    note = Note(inbound_no="FI-FIXTURE", factory_code="fixture", scan_path="test.jpg", created_by=1, **queue_values())
    note.recognition_status = "done"
    note.delivery_no = "710001"
    order = ProductionOrder(order_no="PO-FIXTURE", batch_no="#20261184", created_by=1)
    db.add_all([user, note, order, Alias(kind="process", factory_term="PU", target="Genius Weft", source="seed"),
                LineType(code="inbound", label="到货", is_inbound=True)])
    db.flush()
    note.created_by = user.id
    db.add(ArkUserExternalBinding(ark_user_id=user.id, provider="okki", external_account_id="781"))
    items = [ProductionOrderItem(order_id=order.id, product_id=101, product_name="Fixture", order_qty=5),
             ProductionOrderItem(order_id=order.id, product_id=102, product_name="Fixture", order_qty=4)]
    db.add_all(items)
    context = matching_service.MatchingContext(db, set())
    lines = []
    for index, (color, sku, quantity) in enumerate((("#4", 201, 3), ("#6", 202, 2), ("#4", 201, 4)), 1):
        values = {"line_type": "inbound", "process_raw": "PU", "length_raw": "22", "color_raw": color,
                  "weight_raw": "20g", "quantity": quantity, "quantity_unit": "条"}
        decision = {"sku_id": sku}
        status, data = context.match(values, decision)
        assert status == "matched"
        lines.append(Line(note_id=note.id, line_no=index, raw={}, values=values, selected=True, match_status=status,
                          match_data=data, decision=decision, created_by=user.id))
    db.add_all(lines)
    db.commit()
    credentials = {"sub": str(user.id), "roles": [], "permissions": ["factory_inbound:write"]}
    return note, lines, order, items, credentials


def _approve(db, fixture, indexes=(0, 1), key="factory-test-key-01"):
    note, lines, _, _, user = fixture
    request = PreviewBatch(version=note.version, line_ids=[lines[index].id for index in indexes])
    preview = batch_prepare.preview_batch(db, note.id, request, user)
    prices = {(row["product_id"], row["sku_id"]) for row in preview["lines"]}
    approved = ConfirmBatch(**request.model_dump(), preview_digest=preview["preview_digest"],
                            idempotency_key=key, confirm_cross=True, unit_prices=[
                                {"product_id": product, "sku_id": sku, "unit_price": 7}
                                for product, sku in sorted(prices)
                            ])
    return preview, approved


def test_confirm_freezes_two_skus_and_supplement_reuses_only_unreserved_capacity(db, reviewed_note):
    note, lines, _, items, user = reviewed_note
    preview, approved = _approve(db, reviewed_note)
    assert preview["requires_cross_confirmation"]
    assert [row["sku_id"] for row in preview["lines"]] == ["201", "202"]
    batch = batch_prepare.confirm_batch(db, note.id, approved, user)
    assert batch.purchase_intent["handler_id"] == 781
    assert [row["unit_price"] for row in batch.purchase_intent["lines"]] == [7, 7]
    assert [line.batch_id for line in lines] == [batch.id, batch.id, None]
    assert [item.received_qty for item in items] == [0, 0]
    assert batch_prepare.confirm_batch(db, note.id, approved, user).id == batch.id
    wrong = approved.model_copy(update={"unit_prices": approved.unit_prices[:1]})
    with pytest.raises(HTTPException) as exc:
        batch_prepare.confirm_batch(db, note.id, wrong, user)
    assert exc.value.status_code == 409
    db.rollback()

    supplement, next_request = _approve(db, reviewed_note, indexes=(2,), key="factory-test-key-02")
    assert supplement["lines"][0]["unallocated_qty"] == 2
    assert supplement["lines"][0]["allocations"][0]["quantity"] == 2
    second = batch_prepare.confirm_batch(db, note.id, next_request, user)
    assert second.id != batch.id
    assert list(db.scalars(select(Allocation.quantity).order_by(Allocation.id))) == [3, 2, 2]


def test_changed_capacity_requires_new_confirmation(db, reviewed_note):
    note, lines, _, items, user = reviewed_note
    _, approved = _approve(db, reviewed_note)
    items[0].received_qty = 4
    db.commit()
    with pytest.raises(HTTPException) as exc:
        batch_prepare.confirm_batch(db, note.id, approved, user)
    assert exc.value.status_code == 409
    assert exc.value.detail["preview"]["lines"][0]["unallocated_qty"] == 2
    db.rollback()
    assert db.scalar(select(Batch.id)) is None
    assert all(line.batch_id is None for line in lines)


def test_cross_reallocation_requires_consent_even_when_no_target_is_open(db, reviewed_note):
    note, lines, order, _, user = reviewed_note
    order.status = 1
    db.commit()
    preview, approved = _approve(db, reviewed_note, indexes=(0,))
    assert preview["lines"][0]["allocations"] == []
    assert preview["requires_cross_confirmation"]
    without_consent = approved.model_copy(update={"confirm_cross": False})
    with pytest.raises(HTTPException, match="跨单") as exc:
        batch_prepare.confirm_batch(db, note.id, without_consent, user)
    assert exc.value.status_code == 422
    db.rollback()
    assert lines[0].batch_id is None


def test_manual_production_operations_cannot_invalidate_pending_quantities(db, reviewed_note):
    note, _, order, items, user = reviewed_note
    _, approved = _approve(db, reviewed_note)
    batch_prepare.confirm_batch(db, note.id, approved, user)
    order_id, item_id = order.id, items[0].id
    commands = [
        lambda: production.update_item_received(db, item_id, 3),
        lambda: production.update_order_item(db, item_id, order_qty=2),
        lambda: production.update_item_status(db, item_id, 2),
        lambda: production.update_order(db, order_id, status=1),
        lambda: production.delete_order_item(db, item_id),
        lambda: production.delete_order(db, order_id),
    ]
    for command in commands:
        with pytest.raises(ValueError, match="工厂到货预占"):
            command()
        db.rollback()
