"""Native returns retain shipped facts and cannot manufacture sellable stock."""
from datetime import date, datetime
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.aftersales import service
from app.aftersales.local_execution import ReturnReceive, receive_return
from app.aftersales.models import AfterSalesExecution
from app.auth.models import ArkUser
from app.invoice.settlement_models import Receivable, SettlementItem
from app.inventory.models import StockBalance, StockDocument
from tests.test_aftersales_workflow import _payload
from tests.test_local_fulfillment import setup_order, allocate, create_batch, act, inspect
from tests.test_invoice_commerce import buyer
from tests.test_finance_local import finance
from tests.test_inventory_local import stock, balance


def shipped_case(db, stock, finance, *, currency='USD'):
    invoice, payment, user, warehouse = setup_order(db, stock, finance, currency=currency)
    for target in db.scalars(select(Receivable)).all():
        allocate(db, invoice, payment, user, target, target.amount, target.kind)
    shipment = create_batch(db, invoice, user, warehouse, 3, "ship-all")
    act(db, shipment, user, "ready", "ready")
    inspection = inspect(db, shipment, user)
    act(db, shipment, user, "ship", "ship", inspection_version=inspection.edit_version)
    actor = db.get(ArkUser, int(user["sub"]))
    payload = type(_payload()).model_validate({**_payload().model_dump(), "product_id": None,"local_invoice_item_id": invoice.items[0].id,
        "order_id": f"local:{invoice.id}", "customer_id": invoice.customer_id,
        "purchase_date": invoice.invoice_date, "feedback_date": date(2026, 10, 3), "quantity": Decimal(3),
        "affected_goods_currency": currency})
    case = service.create_case(db, payload, actor, scope=user)
    case.current_status = "approved"
    case.requires_return = True
    case.selected_actions_json = [{"code": "return_inspection"}]
    db.flush()
    item = db.scalar(select(SettlementItem).where(SettlementItem.settlement_id == shipment.id))
    return case, invoice, item, warehouse, user, payload


def command(case, item, warehouse, quantity=1, key="return"):
    return ReturnReceive(request_key=key, expected_version=case.version, settlement_item_id=item.id,
        warehouse_id=warehouse.id, quantity=quantity, business_date=date(2026, 10, 3), reason="customer return")


def test_return_is_quarantined_and_replay_preserves_shipment(db, stock, finance):
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance)
    body = command(case, item, warehouse)
    row = receive_return(db, case.id, body, user)
    assert receive_return(db, case.id, body, user).id == row.id
    assert balance(db, warehouse, stock[0]).on_hand == 7
    quarantine = db.scalar(select(StockBalance).where(StockBalance.quality == "quarantine"))
    assert quarantine.on_hand == 1 and quarantine.reserved == 0
    assert invoice.items[0].stock_shipped_quantity == 3 and item.quantity == 3
    assert db.get(StockDocument, row.stock_document_id).kind == "sales_return"
    assert len(db.scalars(select(AfterSalesExecution)).all()) == 1
    with pytest.raises(ValueError, match="幂等"):
        receive_return(db, case.id, body.model_copy(update={"quantity": 2}), user)


def test_return_across_cases_cannot_exceed_original_batch(db, stock, finance):
    case, invoice, item, warehouse, user, payload = shipped_case(db, stock, finance)
    receive_return(db, case.id, command(case, item, warehouse, 2), user)
    actor = db.get(ArkUser, int(user["sub"]))
    second = service.create_case(db, payload, actor, scope=user)
    second.current_status = "approved"
    second.requires_return = True
    db.flush()
    with pytest.raises(ValueError, match="超过"):
        receive_return(db, second.id, command(second, item, warehouse, 2, "excess"), user)
    assert len(db.scalars(select(AfterSalesExecution)).all()) == 1
    receive_return(db, second.id, command(second, item, warehouse, 1, "final"), user)
    assert db.scalar(select(StockBalance).where(StockBalance.quality == "quarantine")).on_hand == 3


def test_return_state_quantity_date_and_stock_failure_are_atomic(db, stock, finance):
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance)
    body = command(case, item, warehouse)
    case.current_status = "draft"
    db.flush()
    with pytest.raises(ValueError, match="审批"):
        receive_return(db, case.id, body, user)
    case.current_status = "approved"
    db.flush()
    with pytest.raises(ValueError, match="日期"):
        receive_return(db, case.id, body.model_copy(update={"business_date": date(2026, 10, 2)}), user)
    with pytest.raises(ValueError, match="仓库"):
        receive_return(db, case.id, body.model_copy(update={"warehouse_id": 999999}), user)
    assert not db.scalars(select(AfterSalesExecution)).all()
    assert case.current_status == "approved" and case.version == body.expected_version
    receive_return(db, case.id, body, user)


def test_local_case_rejects_spoofed_order_identity(db, stock, finance):
    case, invoice, item, warehouse, user, payload = shipped_case(db, stock, finance)
    actor = db.get(ArkUser, int(user["sub"]))
    with pytest.raises(ValueError, match="不一致"):
        service.create_case(db, payload.model_copy(update={"customer_id": "other"}), actor, scope=user)
    with pytest.raises(ValueError, match="选择本地订单行"):
        service.create_case(db, payload.model_copy(update={"local_invoice_item_id": None, "product_id": 1}), actor, scope=user)


def approve_replacement(db, case, sku, user, quantity=2):
    from app.aftersales.models import AfterSalesReview
    case.selected_actions_json = [dict(code="replacement", quantity=quantity, local_sku_id=sku.id, product="approved", estimated_cost_usd="10")]
    db.add(AfterSalesReview(case_id=case.id, workflow_round=case.workflow_round, reviewer_role="director",
        reviewer_user_id=int(user["sub"]), reviewer_name_snapshot="Director", decision="approve", created_at=datetime(2026, 10, 3),
        compensation_snapshot_json={"actions": case.selected_actions_json}))
    db.flush()


def test_replacement_uses_zero_ar_but_still_requires_inspected_dispatch(db, stock, finance):
    from app.aftersales.local_replacement import ReplacementCreate, create_replacement
    from app.invoice.models import Invoice
    from app.invoice.amendment_service import amend
    from app.invoice.commerce_schemas import LocalInvoiceAmend
    case, original, item, warehouse, user, _ = shipped_case(db, stock, finance)
    approve_replacement(db, case, stock[0], user)
    case.requires_return = False
    body = ReplacementCreate(request_key="replace", expected_version=case.version, action_index=0,
        quantity=2, warehouse_id=warehouse.id, business_date=date(2026, 10, 3), reason="approved replacement")
    execution = create_replacement(db, case.id, body, user)
    assert create_replacement(db, case.id, body, user).id == execution.id
    invoice = db.get(Invoice, execution.related_invoice_id)
    assert invoice.product_amount == invoice.total_amount == invoice.internal_balance == 0
    ar = db.scalar(select(Receivable).where(Receivable.invoice_id == invoice.id))
    assert ar.amount == ar.paid_amount == 0
    with pytest.raises(ValueError, match="批准数量"):
        create_replacement(db, case.id, body.model_copy(update={"request_key": "excess", "expected_version": case.version}), user)
    amendment = LocalInvoiceAmend(**{**body.model_dump(exclude={"action_index", "quantity", "order_type"}),
        "request_key": "bypass", "expected_version": invoice.commerce_version,
        "local_customer_id": invoice.local_customer_id, "sales_user_id": invoice.sales_user_id,
        "invoice_date": invoice.invoice_date, "items": [dict(id=invoice.items[0].id, local_sku_id=stock[0].id, quantity=3, price_per_piece=0)]})
    with pytest.raises(ValueError, match="批准方案冻结"):
        amend(db, invoice.id, amendment, user)
    with pytest.raises(ValueError, match="检验出库"):
        service.close_case(db, case.id, db.get(ArkUser, int(user["sub"])), "Customer acknowledged")
    shipment = create_batch(db, invoice, user, warehouse, 2, "replacement-shipment")
    act(db, shipment, user, "replacement-ready", "ready")
    with pytest.raises(ValueError, match="检验"):
        act(db, shipment, user, "replacement-without-inspection", "ship", inspection_version=0)
    inspection = inspect(db, shipment, user)
    act(db, shipment, user, "replacement-dispatch", "ship", inspection_version=inspection.edit_version)
    assert invoice.commerce_status == "shipped"
    assert original.items[0].stock_shipped_quantity == 3
    assert balance(db, warehouse, stock[0]).on_hand == 5
    service.close_case(db, case.id, db.get(ArkUser, int(user["sub"])), "Customer acknowledged")
    assert case.current_status == "closed" and str(execution.id) in case.execution_result


def test_replacement_failure_rolls_back_order_and_approval_usage(db, stock, finance):
    from app.aftersales.local_replacement import ReplacementCreate, create_replacement
    from app.invoice.models import Invoice
    case, original, item, warehouse, user, _ = shipped_case(db, stock, finance)
    approve_replacement(db, case, stock[0], user, quantity=8)
    body = ReplacementCreate(request_key="unavailable", expected_version=case.version, action_index=0,
        quantity=8, warehouse_id=warehouse.id, business_date=date(2026, 10, 3), reason="approved replacement")
    with pytest.raises(ValueError, match="库存不足"):
        create_replacement(db, case.id, body, user)
    assert len(db.scalars(select(Invoice)).all()) == 1
    assert not db.scalars(select(AfterSalesExecution)).all()
    assert case.version == body.expected_version


def test_unapproved_zero_value_order_cannot_bypass_funding(db, stock, finance):
    from app.invoice import commerce_service as commerce
    from tests.test_invoice_commerce import draft, action
    from app.inventory.service import post_document
    from tests.test_inventory_local import command as stock_command
    customer, user, account = finance
    sku, (warehouse, _) = stock
    post_document(db, stock_command("free-stock", "receipt", warehouse, sku, 2), actor_id=None)
    invoice = commerce.create_draft(db, draft(customer, user, sku, shipping_fee=0, surcharge_amount=0,
        internal_accessory=0, items=[dict(local_sku_id=sku.id, quantity=1, price_per_piece=0)]), user)
    commerce.confirm(db, invoice.id, action("confirm-free", 1, warehouse.id), user)
    with pytest.raises(ValueError, match="最终批准"):
        create_batch(db, invoice, user, warehouse, 1, "free-shipment")


def test_return_cannot_close_from_text_without_required_goods(db, stock, finance):
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance)
    actor = db.get(ArkUser, int(user["sub"]))
    service.execute_case(db, case.id, actor, "all returned", "claimed")
    with pytest.raises(ValueError, match="尚未收齐"):
        service.close_case(db, case.id, actor, "Customer agreed")
    receive_return(db, case.id, command(case, item, warehouse, 3), user)
    service.close_case(db, case.id, actor, "Customer agreed")
    assert case.current_status == "closed"


def test_native_selectors_and_return_api_permission(db, stock, finance):
    from tests.test_aftersales_api import _client
    from tests.authority_helpers import seed_authority
    from app.core.database import get_db
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance)
    actor = db.get(ArkUser, int(user["sub"]))
    seed_authority(db, actor.id, 'aftersales:write', 'aftersales:read')
    # Each real HTTP request starts independently of prior fixture/GET reads.
    def fresh_db():
        db.rollback()
        try:
            yield db
        finally:
            db.rollback()
    with _client(db, actor, ["aftersales:write", "aftersales:read"]) as client:
        client.app.dependency_overrides[get_db] = fresh_db
        response = client.get("/api/aftersales/local/orders/search")
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["order_id"] == f"local:{invoice.id}"
        response = client.get(f"/api/aftersales/local/orders/{invoice.id}/items")
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["shipments"][0]["settlement_item_id"] == item.id
        response = client.post(f"/api/aftersales/cases/{case.id}/local-returns", json=command(case, item, warehouse).model_dump(mode="json"))
        assert response.status_code == 403
    seed_authority(db, actor.id, 'inventory:write')
    with _client(db, actor, ["aftersales:write", "aftersales:read", "inventory:write"]) as client:
        client.app.dependency_overrides[get_db] = fresh_db
        response = client.post(f"/api/aftersales/cases/{case.id}/local-returns", json=command(case, item, warehouse).model_dump(mode="json"))
        assert response.status_code == 200, response.text
        assert response.json()["data"]["stock_document_id"] is not None
        response = client.get(f"/api/aftersales/cases/{case.id}/local-executions")
        assert len(response.json()["data"]["items"]) == 1


def test_replacement_cannot_predate_director_approval(db, stock, finance):
    from datetime import datetime, timedelta
    from app.aftersales.models import AfterSalesReview
    from app.aftersales.local_replacement import ReplacementCreate, create_replacement
    case, invoice, item, warehouse, user, _ = shipped_case(db, stock, finance)
    approve_replacement(db, case, stock[0], user)
    case.feedback_date = date(2026, 10, 1)
    review = db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id))
    review.created_at = datetime(2026, 10, 3)
    db.flush()
    body = ReplacementCreate(request_key="predated", expected_version=case.version, action_index=0,
        quantity=2, warehouse_id=warehouse.id, business_date=date(2026, 10, 2), reason="approved replacement")
    with pytest.raises(ValueError, match="最终批准日期"):
        create_replacement(db, case.id, body, user)
    assert not db.scalars(select(AfterSalesExecution)).all()
