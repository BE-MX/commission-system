"""State, revocation, frozen evidence, and transaction-capture regressions."""
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4
import importlib.util

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.time import beijing_today, beijing_now
from app.domestic.models import DomesticCustomer, DomesticProduct, DomesticOrder, DomesticOrderItem
from app.domestic_decision.models import DecisionEvent, DecisionRun, DecisionJob, DecisionAction
from app.domestic_decision import scope, run_service, state_service, job_service
from app.domestic_decision.schemas import AnalysisRequest
from app.domestic_decision.state_schemas import ActionCreate, ActionUpdate, ViewCreate, JobCreate
from app.domestic_decision.router import router


@pytest.fixture
def portfolio(db):
    permissions = ["domestic_decision:read", "domestic_decision_action:write", "domestic_decision_report:write"]
    user = ArkUser(username="decision-state", real_name="分析员", password_hash="unused")
    other = ArkUser(username="decision-other", real_name="其他人", password_hash="unused")
    role = ArkRole(name="decision-state-role", label="决策测试")
    db.add_all([user, other, role])
    db.flush()
    db.add(ArkUserRole(user_id=user.id, role_id=role.id))
    for code in permissions:
        perm = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
        db.add(perm)
        db.flush()
        db.add(ArkRolePermission(role_id=role.id, permission_id=perm.id))
    customer = DomesticCustomer(shop_name="证据客户", owner_user_id=user.id, created_by=user.id, balance=0)
    product = DomesticProduct(attrs_key="decision-state-cap", name="头套", product_type="cap", craft="test", length="15厘米")
    db.add_all([customer, product])
    db.flush()
    order = DomesticOrder(domestic_no="DO-STATE", order_no="state", customer_id=customer.id, order_date=beijing_today(), total_amount=100, charged_amount=0, created_by=user.id, status=1)
    db.add(order)
    db.flush()
    item = DomesticOrderItem(order_id=order.id, line_no=1, product_id=product.id, product_name="头套", order_qty=1, unit_price=100, original_price=100, discount_amount=0, labor_fee=0, pricing_rule="base_price", pricing_version="test", base_price_version_snapshot=1, attrs_snapshot={"product_type": "cap", "craft": "test", "length": "15厘米"})
    db.add(item)
    db.commit()
    actor = scope.live_actor(db, {"sub": str(user.id)})
    query = AnalysisRequest(start_date=beijing_today(), end_date=beijing_today())
    return user, other, role, customer, order, item, actor, query


def test_events_capture_delete_and_rollback_in_original_transaction(db, portfolio):
    user, _, _, customer, order, item, _, _ = portfolio
    initial = db.query(DecisionEvent).count()
    db.info["domestic_actor_id"] = user.id
    item.attrs_snapshot = {"product_type": "cap", "craft": "changed", "length": "20厘米"}
    db.flush()
    db.flush()
    changed = db.query(DecisionEvent).filter_by(entity_type="item", entity_id=item.id, event_type="changed").one()
    assert changed.before["attrs_snapshot"]["craft"] == "test"
    assert changed.after["attrs_snapshot"]["craft"] == "changed"
    assert changed.actor_user_id == user.id
    db.rollback()
    assert db.query(DecisionEvent).count() == initial
    assert item.attrs_snapshot["craft"] == "test"
    db.expunge(changed)
    item_id = item.id
    db.delete(item)
    db.commit()
    deleted = db.query(DecisionEvent).filter_by(entity_type="item", entity_id=item_id, event_type="deleted").one()
    assert deleted.before["order_qty"] == 1
    assert deleted.after is None
    assert deleted.customer_id == customer.id
    assert deleted.order_id == order.id
    assert "phone" not in deleted.before and "guest_name" not in deleted.before


def test_snapshot_source_change_requires_whole_analysis_refresh(db, portfolio):
    _, _, _, _, order, item, actor, query = portfolio
    result = run_service.create_run(db, actor, query)
    run_id = result["meta"]["run_id"]
    assert run_service.rows(db, actor, run_id, kind="items")["total"] == 1
    item.unit_price = 90
    item.discount_amount = 10
    order.total_amount = 90
    db.commit()
    with pytest.raises(HTTPException) as error:
        run_service.rows(db, actor, run_id)
    assert error.value.status_code == 409
    assert db.get(DecisionRun, run_id).result_json["summary"]["amount"] == 100


def test_old_snapshot_and_report_revoke_immediately_after_owner_transfer(db, portfolio):
    _, other, _, customer, _, _, actor, query = portfolio
    result = run_service.create_run(db, actor, query)
    job, _ = job_service.create_job(db, actor, JobCreate(run_id=result["meta"]["run_id"], request_key="transfer-report"), "brief")
    customer.owner_user_id = other.id
    db.commit()
    with pytest.raises(HTTPException) as error:
        run_service.require_run(db, actor, result["meta"]["run_id"])
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        job_service.get_job(db, actor, job["id"])
    assert error.value.status_code == 403


def test_action_dedup_actual_results_and_changed_condition(db, portfolio):
    _, _, _, customer, order, _, actor, query = portfolio
    result = run_service.create_run(db, actor, query)
    insight = next(row for row in result["insights"] if row.get("customer_id") == customer.id and row["rule_key"] == "customer_concentration")
    payload = ActionCreate(run_id=result["meta"]["run_id"], customer_id=customer.id, rule_key=insight["rule_key"], request_key="action-state-key", due_date=beijing_today())
    first = state_service.create_action(db, actor, payload)
    second = state_service.create_action(db, actor, payload.model_copy(update={"request_key": "action-other-key"}))
    assert first["id"] == second["id"]
    assert db.query(DecisionAction).count() == 1
    with pytest.raises(HTTPException) as error:
        state_service.update_action(db, actor, first["id"], ActionUpdate(expected_version=1, status="done"))
    assert error.value.status_code == 422
    order.status = 4
    db.commit()
    listed = state_service.list_actions(db, actor)
    assert listed[0]["condition_changed"] is True
    assert listed[0]["version"] == 2
    with pytest.raises(HTTPException) as error:
        state_service.update_action(db, actor, first["id"], ActionUpdate(expected_version=1, status="done", result="已核对", result_type="reconciled"))
    assert error.value.status_code == 409
    updated = state_service.update_action(db, actor, first["id"], ActionUpdate(expected_version=2, status="done", result="已核对，原单终止", result_type="reconciled"))
    assert updated["status"] == "done"


def test_views_share_only_filters_not_authorization(db, portfolio):
    _, other, _, customer, _, _, actor, query = portfolio
    view = state_service.save_view(db, actor, ViewCreate(name="单客户", query=query.model_copy(update={"customer_ids": [customer.id]}), shared=True))
    other_actor = {"id": other.id, "roles": [], "permissions": ["domestic_decision:read"]}
    assert state_service.list_views(db, other_actor)[0]["id"] == view["id"]
    # Sharing does not produce an aggregate or bypass owner resolution.
    with pytest.raises(HTTPException):
        scope.require_customer(db, other_actor, customer.id)


def test_job_request_hash_prevents_replay_for_different_content(db, portfolio):
    *_, actor, query = portfolio
    result = run_service.create_run(db, actor, query)
    payload = JobCreate(run_id=result["meta"]["run_id"], request_key="stable-report-key")
    first, created = job_service.create_job(db, actor, payload, "brief")
    second, created_again = job_service.create_job(db, actor, payload, "brief")
    assert created and not created_again and first["id"] == second["id"]
    with pytest.raises(HTTPException) as error:
        job_service.create_job(db, actor, payload.model_copy(update={"focus": "product"}), "brief")
    assert error.value.status_code == 409


def test_export_preserves_precision_and_blocks_spreadsheet_formulas():
    result = {"meta": {"period": {"start": "2026-01-01"}}, "evidence": {"orders": [{"total_amount": 4400.01, "shop_name": "=HYPERLINK(\"bad\")"}]}}
    exported = job_service.export_result(result, "csv")["content"]
    assert "4400.01" in exported
    assert "'=HYPERLINK" in exported


@pytest.mark.parametrize("format", ["csv", "json"])
def test_filtered_export_excludes_history_and_unrequested_focus(format):
    result = {"meta": {"period": {"start_date": "2026-10-01"}},
              "evidence": {"orders": [{"id": 1}], "items": [{"id": 2, "color": "red"}],
                           "ledger": [{"id": 3}], "history_orders": [{"id": 900}],
                           "history_items": [{"color": "DO_NOT_EXPORT"}], "history_ledger": [{"id": 902}]},
              "customers": [{"history": "DO_NOT_EXPORT"}], "insights": [{"description": "DO_NOT_EXPORT"}]}
    export = job_service.export_result(result, format, "product")["content"]
    assert "DO_NOT_EXPORT" not in export and "history_" not in export
    assert "ledger" not in export and "orders" not in export
    assert "red" in export


def test_new_owner_direct_claim_inherits_without_listing_first(db, portfolio):
    user, other, role, customer, _, _, actor, query = portfolio
    initial = run_service.create_run(db, actor, query)
    first = state_service.create_action(db, actor, ActionCreate(run_id=initial["meta"]["run_id"], customer_id=customer.id, rule_key="customer_concentration", request_key="transfer-direct-old", due_date=beijing_today()))
    customer.owner_user_id = other.id
    db.add(ArkUserRole(user_id=other.id, role_id=role.id))
    db.commit()
    new_actor = scope.live_actor(db, {"id": other.id})
    new_run = run_service.create_run(db, new_actor, query)
    inherited = state_service.create_action(db, new_actor, ActionCreate(run_id=new_run["meta"]["run_id"], customer_id=customer.id, rule_key="customer_concentration", request_key="transfer-direct-new", due_date=beijing_today()))
    assert inherited["id"] == first["id"]
    assert inherited["assignee_user_id"] == other.id
    assert db.query(DecisionAction).count() == 1


def test_unique_conflict_rechecks_request_content_under_stale_initial_read(db, portfolio, monkeypatch):
    from sqlalchemy.orm import Query
    _, _, _, customer, _, _, actor, query = portfolio
    run = run_service.create_run(db, actor, query)
    payload = ActionCreate(run_id=run["meta"]["run_id"], customer_id=customer.id, rule_key="customer_concentration", request_key="stale-conflict-key", due_date=beijing_today())
    state_service.create_action(db, actor, payload)
    original_first, original_all = Query.first, Query.all
    hidden = [False]
    def first(query):
        if query.column_descriptions[0].get("entity") is DecisionAction and not hidden[0]:
            hidden[0] = True
            return None  # MySQL RR initial snapshot missed the committed row.
        return original_first(query)
    def all_rows(query):
        if query.column_descriptions[0].get("entity") is DecisionAction:
            return []
        return original_all(query)
    monkeypatch.setattr(Query, "first", first)
    monkeypatch.setattr(Query, "all", all_rows)
    with pytest.raises(HTTPException) as error:
        state_service.create_action(db, actor, payload.model_copy(update={"due_date": beijing_today() + timedelta(days=1)}))
    assert error.value.status_code == 409
    assert "其他行动内容" in error.value.detail


def test_router_uses_live_permissions_and_safe_evidence(db, portfolio):
    user, _, role, _, order, item, _, _ = portfolio
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic-decision")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user.id), "roles": ["super_admin"], "permissions": ["domestic_decision_finance:read"]}
    client = TestClient(app)
    evidence = client.get(f"/api/domestic-decision/evidence/item/{item.id}")
    assert evidence.status_code == 200
    assert "guest_name" not in evidence.json()["data"]
    assert "membership_level_snapshot" not in evidence.json()["data"]
    assert client.get("/api/domestic-decision/evidence/ledger/1").status_code == 403
    db.query(ArkRolePermission).filter(ArkRolePermission.role_id == role.id).delete(synchronize_session=False)
    db.commit()
    assert client.get(f"/api/domestic-decision/evidence/order/{order.id}").status_code == 403


def test_real_http_jobs_finish_and_private_export_downloads(db, portfolio, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    user, _, _, _, _, _, _, query = portfolio
    monkeypatch.setattr(job_service, "SessionLocal", sessionmaker(bind=db.get_bind()))
    def unavailable(*args, **kwargs):
        raise RuntimeError("isolated test has no external provider")
    monkeypatch.setattr("app.ai.service.chat", unavailable)
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic-decision")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user.id)}
    client = TestClient(app)
    result = client.post("/api/domestic-decision/analysis-runs", json=query.model_dump(mode="json"))
    assert result.status_code == 200
    run_id = result.json()["data"]["meta"]["run_id"]
    for path, extra in [("briefs", {}), ("query-plans", {"question": "最近7天的订单数量"}), ("exports", {"focus": "product", "format": "json"})]:
        response = client.post(f"/api/domestic-decision/{path}", json={"run_id": run_id, "request_key": f"http-job-{path}", **extra})
        assert response.status_code == 200
        job_id = response.json()["data"]["id"]
        ready = client.get(f"/api/domestic-decision/{path}/{job_id}")
        assert ready.status_code == 200 and ready.json()["data"]["status"] == "succeeded"
        if path == "query-plans":
            preview = ready.json()["data"]["result"]
            assert preview["requires_apply"] is True
            assert client.post("/api/domestic-decision/analysis-runs", json=preview["query"]).status_code == 200
        if path == "exports":
            downloaded = client.get(f"/api/domestic-decision/exports/{job_id}/download")
            assert downloaded.status_code == 200
            assert list(downloaded.json()["evidence"]) == ["items", "reports"]
            assert "membership_level_snapshot" not in downloaded.text
    assert len(client.get("/api/domestic-decision/briefs").json()["data"]) == 1


def test_interrupted_persistent_job_reports_failure_after_timeout(db, portfolio):
    *_, actor, query = portfolio
    result = run_service.create_run(db, actor, query)
    job, _ = job_service.create_job(db, actor, JobCreate(run_id=result["meta"]["run_id"], request_key="interrupted-job-key"), "brief")
    row = db.get(DecisionJob, job["id"])
    row.created_at = beijing_now() - timedelta(minutes=11)
    db.commit()
    read = job_service.get_job(db, actor, job["id"])
    assert read.status == "failed" and read.finished_at is not None
    assert "中断" in read.error_message


def test_completed_signal_deduplicates_window_and_transfer_reassigns(db, portfolio):
    user, other, _, customer, _, _, actor, query = portfolio
    run = run_service.create_run(db, actor, query)
    payload = ActionCreate(run_id=run["meta"]["run_id"], customer_id=customer.id, rule_key="customer_concentration", request_key="done-dedup-key", due_date=beijing_today())
    first = state_service.create_action(db, actor, payload)
    state_service.update_action(db, actor, first["id"], ActionUpdate(expected_version=1, status="done", result="已联系并核对采购计划", result_type="contacted"))
    second = state_service.create_action(db, actor, payload.model_copy(update={"request_key": "after-done-another"}))
    assert first["id"] == second["id"]
    assert db.query(DecisionAction).count() == 1
    customer.owner_user_id = other.id
    db.commit()
    new_actor = {"id": other.id, "roles": [], "permissions": ["domestic_decision:read", "domestic_decision_action:write"]}
    assert state_service.list_actions(db, actor) == []
    inherited = state_service.list_actions(db, new_actor)
    assert inherited[0]["assignee_user_id"] == other.id
    assert inherited[0]["status"] == "done"


def test_non_product_dimension_drilldown_preserves_group(db, portfolio):
    _, _, _, customer, _, _, actor, query = portfolio
    customer.province = "浙江"
    db.commit()
    run = run_service.create_run(db, actor, query.model_copy(update={"dimensions": ["province", "order_channel"]}))
    rows = run_service.rows(db, actor, run["meta"]["run_id"], kind="items", dimension="province", value="浙江")
    assert rows["total"] == 1
    assert run_service.rows(db, actor, run["meta"]["run_id"], kind="orders", dimension="province", value="浙江")["total"] == 1


def test_frozen_rows_sort_full_result_before_page_and_reject_unknown_fields(db, portfolio):
    _, _, _, _, order, item, actor, query = portfolio
    extra = []
    for line, price in [(2, 9), (3, 500)]:
        row = DomesticOrderItem(order_id=order.id, line_no=line, product_id=item.product_id, product_name="头套", order_qty=1, unit_price=price, original_price=price, discount_amount=0, labor_fee=0, pricing_rule="base_price", pricing_version="test", base_price_version_snapshot=1, attrs_snapshot=item.attrs_snapshot)
        db.add(row)
        extra.append(row)
    order.total_amount = 609
    db.commit()
    result = run_service.create_run(db, actor, query)
    run_id = result["meta"]["run_id"]
    highest = run_service.rows(db, actor, run_id, kind="items", page_size=1, sort_field="unit_price", sort_order="desc")
    assert highest["items"][0]["id"] == extra[1].id and highest["total"] == 3
    assert run_service.rows(db, actor, run_id, kind="items", page=2, page_size=1, sort_field="unit_price", sort_order="desc")["items"][0]["id"] == item.id
    assert run_service.rows(db, actor, run_id, kind="items", page_size=1)["items"][0]["id"] == item.id
    with pytest.raises(HTTPException) as error:
        run_service.rows(db, actor, run_id, kind="items", sort_field="DROP TABLE", sort_order="desc")
    assert error.value.status_code == 422


def test_migration_upgrade_and_downgrade_only_in_isolated_sqlite():
    from pathlib import Path
    path = Path(__file__).parents[1] / "alembic" / "versions" / "174_domestic_decision.py"
    spec = importlib.util.spec_from_file_location("test_domestic_decision_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ark_users(id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ark_domestic_customers(id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ark_permissions(id INTEGER PRIMARY KEY, code TEXT, module TEXT, action TEXT, label TEXT, kind TEXT, is_legacy INTEGER, sort INTEGER)"))
        connection.execute(text("CREATE TABLE ark_role_permissions(role_id INTEGER, permission_id INTEGER)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT count(*) FROM ark_permissions")).scalar() == 6
            assert connection.execute(text("SELECT count(*) FROM ark_role_permissions")).scalar() == 0
            connection.execute(text("SELECT * FROM ark_domestic_analysis_events"))
            with pytest.raises(RuntimeError, match="audit data"):
                migration.downgrade()
            assert connection.execute(text("SELECT count(*) FROM ark_permissions")).scalar() == 6
            assert connection.execute(text("SELECT count(*) FROM ark_domestic_analysis_config")).scalar() == 1
