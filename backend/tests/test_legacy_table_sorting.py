"""Cross-page list sort contracts, using only the in-memory SQLite fixture."""
import inspect
from datetime import date

import pytest
from fastapi.params import Param

from app.api import supervisor, employee, customer, payment, commission
from app.ai import log_service
from app.auth import admin_router
from app.color import blend_service, swatch_service
from app.design import router as design_router
from app.governance import concept_service
from app.tracking import shipment_service
from app.training import service as training_service
from app.training.models import TrainingDigest
from app.ai_gateway import admin_service as gateway_service
from app.ai_gateway.models import GatewayApp, GatewayRequest
from app.asset import asset_service
from app.asset.models import Asset
from app.insight import item_service
from app.auth.models import ArkUser
from app.models.commission import SyncedPayment


def call_endpoint(fn, db, **overrides):
    kwargs = {key: value.default.default for key, value in inspect.signature(fn).parameters.items()
              if isinstance(value.default, Param)}
    kwargs.update(db=db, **overrides)
    return fn(**kwargs)


@pytest.mark.parametrize("fn, fields, args", [
    (supervisor.list_supervisor_relations, "salesperson_id salesperson_name supervisor_id supervisor_name second_supervisor_id second_supervisor_name effective_start", {}),
    (employee.list_employees, "user_id full_name nickname current_attribute", {}),
    (customer.list_customer_snapshots, "customer_id customer_name salesperson_name salesperson_attribute salesperson_rate supervisor_name supervisor_attribute supervisor_rate second_supervisor_name second_supervisor_rate remark first_receipt_date is_complete source", {}),
    (payment.list_synced_payments, "payment_id order_id customer_name payment_date payment_amount service_fee exchange_rate real_amount_rmb is_calculated batch_id", {"date_start": "2026-01-01", "date_end": "2026-12-31"}),
    (commission.list_batches, "batch_name period_type period_start period_end status confirmed_count confirmation_status feedback_count created_at", {}),
    (commission.list_commission_details, "payment_id order_id customer_name payment_amount salesperson_name salesperson_rate salesperson_commission supervisor_name supervisor_rate supervisor_commission second_supervisor_name second_supervisor_rate second_supervisor_commission calc_rule_note", {"batch_id": 1}),
    (admin_router.list_users, "username real_name email phone dingtalk_id roles is_active last_login_at", {}),
    (design_router.list_requests, "request_no customer_name customer_level salesperson_name shoot_type expect_start_date priority remark created_at attachments conflict_detail", {"_user": {"sub": "1", "roles": ["super_admin"], "permissions": []}}),
    (design_router.list_tasks, "task_no customer_name salesperson_name shoot_type designer_name plan_start_date priority remark status created_at", {"_user": {"sub": "1", "roles": ["super_admin"], "permissions": []}}),
])
def test_endpoint_sort_fields_compile_and_execute_on_empty_sqlite(db, fn, fields, args):
    for field in fields.split():
        for direction in ("asc", "desc"):
            call_endpoint(fn, db, sort_field=field, sort_order=direction, **args)


def test_training_full_result_sort_numeric_nulls_ties_and_tag_filter(db):
    author = ArkUser(username="sort-author", password_hash="hash", real_name="A")
    db.add(author)
    db.flush()
    values = [("B", 100), ("C", 2), ("A", 10), ("D", 2)]
    for name, count in values:
        db.add(TrainingDigest(title=name, status="published", trained_at=date(2026, 10, 1),
                              created_by=author.id, useful_count=count, tags_json=["sort"]))
    db.commit()
    common = dict(user_id=author.id, page_size=2, tag="sort", sort_field="useful_count")
    first = training_service.list_digests(db, page=1, sort_order="asc", **common)
    second = training_service.list_digests(db, page=2, sort_order="asc", **common)
    assert [r["useful_count"] for r in first["items"] + second["items"]] == [2, 2, 10, 100]
    assert [r["title"] for r in first["items"]] == ["C", "D"]
    assert first["total"] == second["total"] == 4
    desc = training_service.list_digests(db, page=1, sort_order="desc", **common)
    assert [r["useful_count"] for r in desc["items"]] == [100, 10]
    for field in ("tags", "org_lecturer", "creator_name", "read_minutes", "trained_at", "title"):
        training_service.list_digests(db, page=1, page_size=2, user_id=author.id, sort_field=field, sort_order="asc")


def test_service_extra_columns_compile(db):
    for fn, fields, args in [
        (blend_service.list_blends, "blend_code display_name blend_type computed_hex components source", {}),
        (swatch_service.list_swatches, "id color_id target_hex model_used delta_e status created_at", {}),
        (log_service.list_logs, "id caller_module provider_type model tokens_used duration_ms status created_at", {}),
        (shipment_service.list_shipments, "waybill_no carrier_name receiver_name receiver_country current_status current_status_text current_location estimated_delivery_date last_event_time dingtalk_user_name short_code is_active", {"current_user": {"roles": ["super_admin"]}}),
    ]:
        for field in fields.split():
            fn(db, sort_field=field, sort_order="asc", **args)


def test_asset_and_insight_whitelists_execute(db):
    db.add(Asset(file_name="sort.png", file_type="image", file_format="png", storage_path="sort.png", uploader_id=1))
    db.commit()
    for field in ("file_name", "file_type", "file_size", "thumbnail_path", "tags", "created_at"):
        total, rows, _ = asset_service.query_assets(db, sort_by=field, sort_order="asc")
        assert total == len(rows) == 1
    for field in ("title", "credibility_label", "item_type", "status"):
        item_service.list_items(db, sort_by=field, sort_desc=False)
    for field in ("id", "name_zh", "name_en", "layer", "status", "confidence", "owner", "updated_at"):
        concept_service.list_concepts(db, sort_field=field, sort_order="asc")


def test_gateway_computed_usage_sort_before_page(db):
    author = ArkUser(username="gateway-author", password_hash="hash", real_name="Owner")
    db.add(author)
    db.flush()
    apps = []
    for name, tokens in [("One", 100), ("Two", 2), ("Three", 10)]:
        app = GatewayApp(name=name, owner_user_id=author.id, key_hash=name, key_hint="hint", created_by=author.id, updated_by=author.id)
        db.add(app)
        db.flush()
        db.add(GatewayRequest(app_id=app.id, request_id=name, owner_user_id=author.id, preset_id=1,
            preset_name="test", model="test", status="success", tokens_prompt=tokens, tokens_completion=1))
        apps.append(app)
    db.commit()
    first = gateway_service.list_apps(db, 1, 1, sort_field="tokens_prompt", sort_order="asc")
    second = gateway_service.list_apps(db, 2, 1, sort_field="tokens_prompt", sort_order="asc")
    assert first["total"] == second["total"] == 3
    assert [r["name"] for r in first["items"] + second["items"]] == ["Two", "Three"]
    for field in ("name", "owner_name", "is_enabled", "today_calls", "tokens_prompt", "unknown_usage", "failures", "occupied", "last_used_at"):
        gateway_service.list_apps(db, 1, 1, sort_field=field, sort_order="desc")
    for field in ("request_id", "preset_name", "created_at", "status", "tokens_prompt", "error_code", "resolution_reason"):
        gateway_service.list_requests(db, apps[0].id, 1, 1, sort_field=field, sort_order="asc")


def test_payment_numeric_date_null_and_clear_across_pages(db):
    for pid, amount, rate, day in [("P-C", 100, None, 3), ("P-A", 2, 7.1, 1), ("P-B", 10, 7.2, 2)]:
        db.add(SyncedPayment(payment_id=pid, order_id=pid, customer_id="not-mapped", payment_date=date(2026, 10, day),
                             payment_amount=amount, exchange_rate=rate))
    db.commit()
    args = dict(date_start="2026-10-01", date_end="2026-10-31", page_size=1)
    rows = [call_endpoint(payment.list_synced_payments, db, page=page, sort_field="payment_amount", sort_order="asc", **args).data.items[0]
            for page in (1, 2, 3)]
    assert [r.payment_amount for r in rows] == [2, 10, 100]
    for direction in ("asc", "desc"):
        last = call_endpoint(payment.list_synced_payments, db, page=3, sort_field="exchange_rate", sort_order=direction, **args)
        assert last.data.items[0].payment_id == "P-C"
    cleared = call_endpoint(payment.list_synced_payments, db, page=1, sort_field="", sort_order="", **args)
    assert cleared.data.items[0].payment_id == "P-C"  # default payment_date descending
