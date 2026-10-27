from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.invoice import edit_authority, item_group_service, linked_sync_service, service
from app.invoice.linked_sync_service import edit_version
from app.invoice.models import InvoiceLinkedSync
from app.invoice.router import router
from app.invoice.schemas import InvoiceCreate, InvoiceItemGroupsUpdate, InvoiceUpdate
from tests.authority_helpers import seed_authority


@pytest.fixture
def product_boundaries(monkeypatch):
    monkeypatch.setattr(service.product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    monkeypatch.setattr(service.price_service, "resolve_price", lambda *args, **kwargs: {
        "standard_price": Decimal("20"), "customer_price": Decimal("20"), "currency": "USD",
    })


def hair(group_key=None, *, identity=None, name="Product A"):
    return {
        "id": identity,
        "product_kind": "hair",
        "item_type": "stock",
        "product_id": 1,
        "sku_id": 9001,
        "product_name": name,
        "product_display": name,
        "net_weight_grams": "100g",
        "model": "M1",
        "color": "Natural",
        "length": "18",
        "quantity": 2,
        "price_per_piece": Decimal("20"),
        "group_key": group_key,
    }


def payload(groups, items):
    return {
        "customer_id": "CUST-GROUP",
        "customer_name": "Grouped Customer",
        "customer_grade": "A",
        "inspection_requirement": "detail",
        "invoice_date": date(2026, 10, 27),
        "currency": "USD",
        "items": items,
        "item_groups": groups,
    }


def test_create_and_reload_persists_stable_groups_without_changing_business_version(db, product_boundaries):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [
            {"key": "group-a", "name": "首批", "sort_order": 1},
            {"key": "group-b", "name": "补单", "sort_order": 2},
        ],
        [hair("group-a"), hair("group-b", name="Product B")],
    )))
    db.commit()
    assert db.query(service.item_group_service.InvoiceItemGroup).filter_by(invoice_id=invoice.id).count() == 2
    db.expire_all()
    invoice = service.get_invoice(db, invoice.id)

    assert [(group.key, group.name) for group in invoice.item_groups] == [("group-a", "首批"), ("group-b", "补单")]
    assert [item.group.key for item in invoice.items] == ["group-a", "group-b"]
    business_version = edit_version(invoice)
    invoice.item_groups[0].name = "首批改名"
    invoice.items[0].group = invoice.item_groups[1]
    invoice.items[0].group_id = invoice.item_groups[1].id
    assert edit_version(invoice) == business_version

    db.rollback()
    loaded = service.get_invoice(db, invoice.id)
    detail = service.serialize_detail(loaded, db)
    assert [(group["key"], group["name"]) for group in detail["item_groups"]] == [("group-a", "首批"), ("group-b", "补单")]
    assert [item["group_key"] for item in detail["items"]] == ["group-a", "group-b"]
    assert len(detail["item_groups_version"]) == 64


def test_legacy_payload_gets_one_default_product_group(db, product_boundaries):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(None, [hair(), hair(name="Product B")])))

    assert len(invoice.item_groups) == 1
    assert invoice.item_groups[0].name
    assert {item.group_id for item in invoice.items} == {invoice.item_groups[0].id}


def test_legacy_update_after_commit_reuses_existing_default_group(db, product_boundaries):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(None, [hair()])))
    item_id = invoice.items[0].id
    db.commit()

    updated = service.update_invoice(db, invoice, InvoiceUpdate(**payload(None, [hair(identity=item_id)])))

    assert len(updated.item_groups) == 1
    assert updated.items[0].group_id == updated.item_groups[0].id


def test_update_maps_new_groups_and_preserves_old_line_creation_time(db, product_boundaries):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [{"key": "group-a", "name": "首批", "sort_order": 1}], [hair("group-a")],
    )))
    db.flush()
    old_id = invoice.items[0].id
    old_created_at = invoice.items[0].created_at

    updated = service.update_invoice(db, invoice, InvoiceUpdate(**payload(
        [
            {"key": "group-a", "name": "首批改名", "sort_order": 1},
            {"key": "group-b", "name": "二次补单", "sort_order": 2},
        ],
        [hair("group-a", identity=old_id), hair("group-b", name="Product B")],
    )))
    db.commit()
    db.expire_all()
    updated = service.get_invoice(db, updated.id)

    assert updated.items[0].created_at == old_created_at
    assert updated.items[0].group.key == "group-a"
    assert updated.items[0].group.name == "首批改名"
    assert updated.items[1].group.key == "group-b"
    assert updated.items[1].created_at is not None


def test_local_group_update_does_not_reset_business_or_sync_state(db, product_boundaries, monkeypatch):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [{"key": "group-a", "name": "首批", "sort_order": 1}], [hair("group-a")],
    )))
    invoice.sync_status = "synced"
    invoice.status = "ready"
    invoice.synced_at = datetime(2026, 10, 27, 9, 30)
    invoice.xiaoman_order_id = "OKKI-GROUP-1"
    db.commit()
    db.expire_all()
    invoice = service.get_invoice(db, invoice.id)
    item_id = invoice.items[0].id
    created_at = invoice.items[0].created_at
    business_version = edit_version(invoice)
    groups_version = item_group_service.version(invoice)
    monkeypatch.setattr(edit_authority, "prepare_local", lambda *args: (invoice, {}))

    item_group_service.update_local(db, invoice.id, InvoiceItemGroupsUpdate(
        item_groups=[
            {"key": "group-a", "name": "首批改名", "sort_order": 1},
            {"key": "group-b", "name": "二次补单", "sort_order": 2},
        ],
        items=[{"id": item_id, "group_key": "group-b"}],
        expected_version=business_version,
        expected_groups_version=groups_version,
    ), {})
    db.commit()
    db.expire_all()
    loaded = service.get_invoice(db, invoice.id)

    assert [(group.key, group.name) for group in loaded.item_groups] == [("group-a", "首批改名"), ("group-b", "二次补单")]
    assert loaded.items[0].group.key == "group-b"
    assert loaded.items[0].created_at == created_at
    assert edit_version(loaded) == business_version
    assert item_group_service.version(loaded) != groups_version
    assert loaded.sync_status == "synced"
    assert loaded.status == "ready"
    assert loaded.synced_at == datetime(2026, 10, 27, 9, 30)


def test_local_group_update_rejects_stale_versions_and_invalid_assignments(db, product_boundaries, monkeypatch):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [{"key": "group-a", "name": "首批", "sort_order": 1}], [hair("group-a")],
    )))
    db.flush()
    monkeypatch.setattr(edit_authority, "prepare_local", lambda *args: (invoice, {}))
    valid = {
        "item_groups": [{"key": "group-a", "name": "首批", "sort_order": 1}],
        "items": [{"id": invoice.items[0].id, "group_key": "group-a"}],
        "expected_version": edit_version(invoice),
        "expected_groups_version": item_group_service.version(invoice),
    }
    with pytest.raises(HTTPException) as stale:
        item_group_service.update_local(db, invoice.id, InvoiceItemGroupsUpdate(
            **{**valid, "expected_groups_version": "0" * 64},
        ), {})
    assert stale.value.status_code == 409

    with pytest.raises(ValueError, match="不能重复"):
        item_group_service.update_local(db, invoice.id, InvoiceItemGroupsUpdate(**{
            **valid,
            "item_groups": [
                {"key": "group-a", "name": "相同名称", "sort_order": 1},
                {"key": "group-b", "name": "相同名称", "sort_order": 2},
            ],
        }), {})
    with pytest.raises(ValueError, match="产品明细已变化"):
        item_group_service.update_local(db, invoice.id, InvoiceItemGroupsUpdate(**{
            **valid, "items": [{"id": 999999, "group_key": "group-a"}],
        }), {})


def test_linked_sync_rejects_group_only_changes(db, product_boundaries, monkeypatch):
    monkeypatch.setattr(linked_sync_service.remote, "order_receipts", lambda *args: [])
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [{"key": "group-a", "name": "首批", "sort_order": 1}], [hair("group-a")],
    )))
    invoice.xiaoman_order_id = "OKKI-GROUP-ONLY"
    invoice.sync_status = "synced"
    invoice.status = "ready"
    db.commit()
    db.expire_all()
    invoice = service.get_invoice(db, invoice.id)
    body = NS(
        request_key="group-only-request",
        expected_version=edit_version(invoice),
        invoice=InvoiceUpdate(**payload(
            [{"key": "group-a", "name": "只改分组名", "sort_order": 1}],
            [hair("group-a", identity=invoice.items[0].id)],
        )),
        model_dump_json=lambda: "{}",
    )

    with pytest.raises(ValueError, match="业务数据未变化"):
        linked_sync_service.create(db, invoice, body, 1)
    db.rollback()
    assert db.query(InvoiceLinkedSync).count() == 0


def group_api(db, permissions):
    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    user = {"sub": "1", "roles": [], "permissions": permissions}
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_group_http_create_patch_reopen_and_stale_version(db, product_boundaries):
    seed_authority(db, 1, "invoice:write", "invoice:read")
    with group_api(db, ["invoice:write", "invoice:read"]) as client:
        created_response = client.post("/api/invoice/invoices", json=InvoiceCreate(**payload(
            [{"key": "group-a", "name": "首批", "sort_order": 1}], [hair("group-a")],
        )).model_dump(mode="json"))
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()["data"]
        item_id = created["items"][0]["id"]
        expected_version = created["edit_version"]
        expected_groups_version = created["item_groups_version"]
        invoice = service.get_invoice(db, created["id"])
        invoice.sync_status = "synced"
        invoice.status = "ready"
        db.commit()

        response = client.patch(f"/api/invoice/invoices/{created['id']}/item-groups", json={
            "item_groups": [
                {"key": "group-a", "name": "首批改名", "sort_order": 1},
                {"key": "group-b", "name": "二次补单", "sort_order": 2},
            ],
            "items": [{"id": item_id, "group_key": "group-b"}],
            "expected_version": expected_version,
            "expected_groups_version": expected_groups_version,
        })
        assert response.status_code == 200, response.text
        updated = response.json()["data"]
        assert updated["sync_status"] == "synced"
        assert updated["status"] == "ready"
        assert updated["edit_version"] == expected_version
        assert updated["item_groups_version"] != expected_groups_version
        assert updated["items"][0]["group_key"] == "group-b"
        assert [group["name"] for group in updated["item_groups"]] == ["首批改名", "二次补单"]

        reopened = client.get(f"/api/invoice/invoices/{created['id']}")
        assert reopened.status_code == 200
        assert reopened.json()["data"]["items"][0]["group_key"] == "group-b"
        assert reopened.json()["data"]["item_groups_version"] == updated["item_groups_version"]
        stale = client.patch(f"/api/invoice/invoices/{created['id']}/item-groups", json={
            "item_groups": updated["item_groups"],
            "items": [{"id": item_id, "group_key": "group-b"}],
            "expected_version": expected_version,
            "expected_groups_version": expected_groups_version,
        })
        assert stale.status_code == 409

    with group_api(db, []) as client:
        denied = client.patch(f"/api/invoice/invoices/{created['id']}/item-groups", json={
            "item_groups": updated["item_groups"],
            "items": [{"id": item_id, "group_key": "group-b"}],
            "expected_version": expected_version,
            "expected_groups_version": updated["item_groups_version"],
        })
        assert denied.status_code == 403


def test_full_update_checks_group_version_and_allows_cyclic_renames(db, product_boundaries):
    invoice = service.create_invoice(db, InvoiceCreate(**payload(
        [
            {"key": "group-a", "name": "首批", "sort_order": 1},
            {"key": "group-b", "name": "待补", "sort_order": 2},
            {"key": "group-c", "name": "__grouping_1", "sort_order": 3},
        ],
        [hair("group-a")],
    )))
    item_id = invoice.items[0].id
    db.commit()
    db.expire_all()
    invoice = service.get_invoice(db, invoice.id)
    original_version = item_group_service.version(invoice)
    original_name = invoice.item_groups[0].name
    invoice.item_groups[0].name = "另一会话名称"
    db.commit()

    stale = InvoiceUpdate(**payload(
        [{"key": "group-a", "name": original_name, "sort_order": 1}],
        [hair("group-a", identity=item_id)],
    ))
    stale.expected_groups_version = original_version
    with pytest.raises(ValueError, match="分组已被他人修改"):
        service.update_invoice(db, invoice, stale)
    db.rollback()
    assert service.get_invoice(db, invoice.id).item_groups[0].name == "另一会话名称"

    current = service.get_invoice(db, invoice.id)
    update = InvoiceUpdate(**payload(
        [
            {"key": "group-a", "name": "__grouping_1", "sort_order": 1},
            {"key": "group-b", "name": "首批", "sort_order": 2},
            {"key": "group-c", "name": "待补", "sort_order": 3},
        ],
        [hair("group-a", identity=item_id)],
    ))
    update.expected_groups_version = item_group_service.version(current)
    updated = service.update_invoice(db, current, update)
    assert [group.name for group in updated.item_groups] == ["__grouping_1", "首批", "待补"]
