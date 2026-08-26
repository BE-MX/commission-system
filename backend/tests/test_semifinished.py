from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.invoice import service as invoice_service_core
from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog
from app.invoice.schemas import InvoiceUpdate
from app.semifinished import invoice_service, material_service, order_service
from app.semifinished.models import (
    InventoryBalance, InventoryLedger, InvoiceAllocation, ProductComponent,
    ProductMapping, SemifinishedMaterial,
)
from app.semifinished.parser import ParsedProduct, parse_product


@pytest.mark.parametrize(
    ("name", "components", "status"),
    [
        ("Standard Double Drawn Genius Weft/16/#1/20g", ("#1",), "confirmed"),
        ("Standard Double Drawn Genius Weft/16/#P8/24/20g", ("#8", "#24"), "needs_review"),
        ("Standard Double Drawn Genius Weft/16/#5ATP8A/24/20g", ("#5AT/8A", "#5AT/24"), "needs_review"),
        ("Super Double Drawn Genius Weft/22/Cookies Cream/20g", ("COOKIES CREAM",), "confirmed"),
        ("Super Double Drawn Genius Weft/22/Salt & Pepper/20g", ("SALT & PEPPER",), "confirmed"),
        ("Standard Double Drawn Weft/18/#1006&#9ATP9A/613/60g", ("#1006", "#9AT/9A", "#9AT/613"), "needs_review"),
    ],
)
def test_product_parser_examples(name, components, status):
    result = parse_product(name)
    assert result is not None
    assert result.components == components
    assert result.parse_status == status


def test_product_parser_falls_back_for_malformed_name():
    result = parse_product(
        "Super Double Drawn Tape Hair/22/#5ATP5A/10062.5g",
        structured_size="22",
        structured_color="#5ATP5A/1006",
        structured_unit="2.5g",
    )
    assert result is not None
    assert result.unit_grams == Decimal("2.5")
    assert result.components == ("#5AT/5A", "#5AT/1006")
    assert result.parse_status == "needs_review"


def _material(db, code="SF-16-ONE", color="#1"):
    material = SemifinishedMaterial(
        material_code=code,
        size="16",
        color_code=color,
        color_key=color,
        color_type="solid",
        status="active",
    )
    db.add(material)
    db.flush()
    db.add(InventoryBalance(material_id=material.id, on_hand_grams=0, reserved_grams=0))
    db.flush()
    return material


def test_material_sync_can_replace_existing_components_without_unique_conflict(db, monkeypatch):
    material = _material(db)
    mapping = ProductMapping(
        source_type="okki",
        product_id=7001,
        product_name="Product/16/#1/20g",
        size="16",
        color_expression="#1",
        unit_grams=Decimal("20"),
        parse_status="confirmed",
        source="auto",
        parser_version="sf-v1",
    )
    db.add(mapping)
    db.flush()
    db.add(ProductComponent(
        mapping_id=mapping.id,
        material_id=material.id,
        component_order=1,
        ratio=Decimal("1"),
        grams_per_piece=Decimal("20"),
    ))
    db.commit()
    parsed = ParsedProduct(
        size="16",
        color_expression="#1",
        unit_grams=Decimal("20"),
        components=("#1",),
        color_type="solid",
        parse_status="confirmed",
    )
    monkeypatch.setattr(
        material_service,
        "_parsed_rows",
        lambda _db: ([(
            {"product_id": 7001, "product_name": "Product/16/#1/20g", "model": None},
            parsed,
        )], 0),
    )

    result = material_service.apply_sync(db)
    assert result["applied"] == 1
    assert db.query(ProductComponent).filter_by(mapping_id=mapping.id).count() == 1


def test_order_partial_receive_is_idempotent_and_completes(db):
    material = _material(db)
    order = order_service.create_order(
        db,
        items=[{"material_id": material.id, "quantity_grams": Decimal("100.000")}],
        user_id=1,
    )
    item = order.items[0]

    first = order_service.receive_item(
        db,
        item_id=item.id,
        quantity_grams=Decimal("40"),
        idempotency_key="receipt-test-0001",
        operator_id=1,
        remark=None,
    )
    replay = order_service.receive_item(
        db,
        item_id=item.id,
        quantity_grams=Decimal("40"),
        idempotency_key="receipt-test-0001",
        operator_id=1,
        remark=None,
    )
    assert first["order_status"] == "partial"
    assert replay["replayed"] is True
    assert db.query(InventoryLedger).count() == 1
    assert db.query(InventoryBalance).filter_by(material_id=material.id).one().on_hand_grams == Decimal("40.000")

    completed = order_service.receive_item(
        db,
        item_id=item.id,
        quantity_grams=Decimal("60"),
        idempotency_key="receipt-test-0002",
        operator_id=1,
        remark=None,
    )
    assert completed["order_status"] == "completed"
    assert db.query(InventoryBalance).filter_by(material_id=material.id).one().on_hand_grams == Decimal("100.000")


def test_order_list_serializes_expanded_aggregate_columns(db):
    first = _material(db, code="SF-16-LIST-1", color="#1")
    second = _material(db, code="SF-16-LIST-2", color="#2")
    order = order_service.create_order(
        db,
        items=[
            {"material_id": first.id, "quantity_grams": Decimal("100")},
            {"material_id": second.id, "quantity_grams": Decimal("50")},
        ],
        user_id=1,
    )

    result = order_service.list_orders(db, page=1, page_size=20, status=None, keyword=None)

    assert result["total"] == 1
    assert result["items"] == [{
        "id": order.id,
        "order_no": order.order_no,
        "batch_no": None,
        "source_type": "manual",
        "production_order_id": None,
        "status": "submitted",
        "is_urgent": 0,
        "expected_delivery_date": None,
        "remark": None,
        "created_by": 1,
        "created_at": order.created_at.isoformat(),
        "item_count": 2,
        "order_qty_grams": Decimal("150.000"),
        "received_qty_grams": Decimal("0.000"),
    }]


def test_order_receipt_rejects_idempotency_key_reuse_with_different_payload(db):
    material = _material(db)
    order = order_service.create_order(
        db,
        items=[{"material_id": material.id, "quantity_grams": Decimal("100")}],
        user_id=1,
    )
    item = order.items[0]
    order_service.receive_item(
        db, item_id=item.id, quantity_grams=Decimal("40"),
        idempotency_key="receipt-conflict-001", operator_id=1, remark=None,
    )

    with pytest.raises(ValueError, match="幂等键已被其他库存操作使用"):
        order_service.receive_item(
            db, item_id=item.id, quantity_grams=Decimal("30"),
            idempotency_key="receipt-conflict-001", operator_id=1, remark=None,
        )


def _invoice_with_mapping(db, available="100"):
    material = _material(db, code="SF-16-TWO", color="#8")
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    balance.on_hand_grams = Decimal(available)
    mapping = ProductMapping(
        source_type="okki",
        product_id=9001,
        product_name="Product/16/#8/20g",
        size="16",
        color_expression="#8",
        unit_grams=Decimal("20"),
        parse_status="confirmed",
        source="manual",
        parser_version="test",
    )
    db.add(mapping)
    db.flush()
    db.add(ProductComponent(
        mapping_id=mapping.id,
        material_id=material.id,
        component_order=1,
        ratio=Decimal("1"),
        grams_per_piece=Decimal("20"),
    ))
    invoice = Invoice(
        invoice_no="SC-TEST-001",
        order_type="production",
        customer_id="1",
        customer_name="Customer",
        invoice_date=date.today(),
        currency="USD",
    )
    invoice.items.append(InvoiceItem(
        sort_order=1,
        product_kind="hair",
        item_type="stock",
        product_id=9001,
        sku_id=8001,
        product_name="Product/16/#8/20g",
        product_display="Product",
        net_weight_grams="20g",
        color="#8",
        length="16",
        quantity=2,
        price_per_piece=Decimal("10"),
        total_price=Decimal("20"),
        semifinished_enabled=1,
        semifinished_plan=[{"material_id": material.id, "quantity_grams": 40}],
    ))
    db.add(invoice)
    db.commit()
    return invoice, material


def test_invoice_prepare_finalize_and_negative_delta(db):
    invoice, material = _invoice_with_mapping(db)
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    assert balance.on_hand_grams == Decimal("100.000")
    assert balance.reserved_grams == Decimal("40.000")

    invoice_service.finalize_invoice_sync(db, invoice.id, operation, operator_id=1)
    db.commit()
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    allocation = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id, material_id=material.id).one()
    assert balance.on_hand_grams == Decimal("60.000")
    assert balance.reserved_grams == Decimal("0.000")
    assert allocation.allocated_qty_grams == Decimal("40.000")

    invoice.items[0].semifinished_plan = [{"material_id": material.id, "quantity_grams": 25}]
    db.commit()
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    invoice_service.finalize_invoice_sync(db, invoice.id, operation, operator_id=1)
    db.commit()
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    allocation = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id, material_id=material.id).one()
    assert balance.on_hand_grams == Decimal("75.000")
    assert allocation.allocated_qty_grams == Decimal("25.000")


def test_invoice_prepare_detects_plan_changed_after_reservation(db):
    invoice, material = _invoice_with_mapping(db)
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    invoice = db.get(Invoice, invoice.id)
    invoice.items[0].semifinished_plan = [{"material_id": material.id, "quantity_grams": 30}]
    db.flush()

    with pytest.raises(ValueError, match="预占后发生变化"):
        invoice_service.ensure_pending_matches_invoice(db, invoice, operation)

    db.rollback()
    invoice_service.release_invoice_sync(db, invoice.id, operation, operator_id=1)
    db.commit()
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    assert balance.reserved_grams == Decimal("0.000")


def test_invoice_update_is_blocked_while_inventory_batch_is_pending(db):
    invoice, _material_row = _invoice_with_mapping(db)
    invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    payload = InvoiceUpdate(
        customer_id=invoice.customer_id,
        customer_name=invoice.customer_name,
        order_type=invoice.order_type,
        invoice_date=invoice.invoice_date,
        items=[],
    )

    with pytest.raises(ValueError, match="正在同步或等待半成品库存恢复"):
        invoice_service_core.update_invoice(db, invoice, payload, user_id=1)


def test_invoice_detail_enriches_saved_plan_with_current_inventory(db):
    invoice, material = _invoice_with_mapping(db, available="88")
    detail = invoice_service_core.serialize_detail(invoice, db)
    plan = detail["items"][0]["semifinished_plan"][0]
    assert plan["material_id"] == material.id
    assert plan["size"] == "16"
    assert plan["color_code"] == "#8"
    assert plan["available_grams"] == Decimal("88.000")


def test_invoice_sync_failure_releases_reservation(db):
    invoice, material = _invoice_with_mapping(db)
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    invoice_service.release_invoice_sync(db, invoice.id, operation, operator_id=1)
    db.commit()
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    allocation = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id, material_id=material.id).one()
    assert balance.on_hand_grams == Decimal("100.000")
    assert balance.reserved_grams == Decimal("0.000")
    assert allocation.allocated_qty_grams == Decimal("0.000")
    assert allocation.status == "allocated"


def test_invoice_recovery_requires_success_log_after_current_reservation(db):
    invoice, material = _invoice_with_mapping(db)
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    allocation = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id).one()
    invoice = db.get(Invoice, invoice.id)
    invoice.xiaoman_order_id = "OKKI-RECOVERY-1"
    db.add(InvoiceSyncLog(
        invoice_id=invoice.id,
        action="create",
        success=1,
        inventory_operation_key="different-batch",
        created_at=allocation.pending_at - timedelta(seconds=1),
    ))
    db.commit()

    with pytest.raises(ValueError, match="未找到 OKKI 已受理证据"):
        invoice_service.recover_invoice_sync(db, invoice.id, "finalize", operator_id=1)
    db.rollback()

    allocation = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id).one()
    db.add(InvoiceSyncLog(
        invoice_id=invoice.id,
        action="create",
        success=1,
        inventory_operation_key=operation,
        created_at=allocation.pending_at + timedelta(seconds=1),
    ))
    db.commit()
    result = invoice_service.recover_invoice_sync(db, invoice.id, "finalize", operator_id=1)
    assert result["operation_key"] == operation
    assert db.query(InventoryBalance).filter_by(material_id=material.id).one().on_hand_grams == Decimal("60.000")


def test_unsynced_invoice_delete_cleans_zero_allocation_rows(db):
    invoice, _material_row = _invoice_with_mapping(db)
    operation = invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    invoice_service.release_invoice_sync(db, invoice.id, operation, operator_id=1)
    db.commit()

    invoice_service_core.delete_invoice(db, invoice)
    db.commit()
    assert db.get(Invoice, invoice.id) is None
    assert db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id).count() == 0


def test_invoice_prepare_blocks_shortage_without_partial_reservation(db):
    invoice, material = _invoice_with_mapping(db, available="20")
    with pytest.raises(ValueError, match="库存不足"):
        invoice_service.prepare_invoice_sync(db, invoice, operator_id=1)
    db.rollback()
    balance = db.query(InventoryBalance).filter_by(material_id=material.id).one()
    assert balance.reserved_grams == Decimal("0.000")
