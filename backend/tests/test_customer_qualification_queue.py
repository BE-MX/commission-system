"""Research quality and customer qualification are separate, scoped decisions."""

from datetime import timedelta
import pytest

from app.customer.models import CustomerAction, CustomerAssignment, CustomerQualificationReview
from tests.test_customer_workbench import NOW, hub
from tests.test_customer_workflow import _research_task


def test_mysql_ranked_scope_uses_review_table_collation():
    """Derived CASE columns must not inherit MySQL 8's connection collation."""
    from sqlalchemy import create_mock_engine
    from sqlalchemy.dialects import mysql
    from sqlalchemy.orm import Session
    from app.customer.qualification_service import _ranked_research

    engine = create_mock_engine("mysql+pymysql://", lambda *args, **kwargs: None)
    with Session(bind=engine) as session:
        ranked = _ranked_research(session, {"sub": "1", "roles": ["super_admin"], "permissions": []})
        for name in ("scope_type", "scope_ref_id"):
            expression = str(
                ranked.element.selected_columns[name].compile(dialect=mysql.dialect())
            )
            assert "COLLATE utf8mb4_unicode_ci" in expression
        sql = str(ranked.element.compile(dialect=mysql.dialect()))
        assert "CAST(ark_sales_search_results.id AS CHAR) COLLATE utf8mb4_unicode_ci" in sql


def decision(client, task_id, **values):
    context = client.get(f"/api/customer-hub/qualification-queue/{task_id}")
    assert context.status_code == 200, context.text
    data = context.json()["data"]
    return {"decision": "approve", "reason": "官网产品与目标适配", "request_key": "qualification-unique-key",
            "context_hash": data["context_hash"], "expected_current_review_id": data["current_review_id"], **values}


def test_queue_deduplicates_and_approval_creates_action_once(db, hub):
    client, _, customer, profile, _ = hub
    older = _research_task(db, customer, task_id=201)
    older.updated_at = NOW
    newer = _research_task(db, customer, task_id=202)
    newer.updated_at = NOW + timedelta(minutes=2)
    db.flush()
    listed = client.get("/api/customer-hub/qualification-queue?page_size=1")
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"]["total"] == 1
    task_id = listed.json()["data"]["items"][0]["research_task_id"]
    assert task_id == 202
    payload = decision(client, task_id)
    response = client.post(f"/api/customer-hub/qualification-queue/{task_id}/decision", json=payload)
    assert response.status_code == 200, response.text
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 0
    replay = client.post(f"/api/customer-hub/qualification-queue/{task_id}/decision", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["replayed"] is True
    assert db.query(CustomerQualificationReview).count() == 1
    assert db.query(CustomerAction).count() == 1
    assert db.query(CustomerAssignment).filter_by(customer_id=customer.id).count() == 1


def test_deferred_reappears_only_at_review_time(db, hub, monkeypatch):
    from app.customer import qualification_service
    from app.sales_automation import public_pool_service

    monkeypatch.setattr(qualification_service, "beijing_now", lambda: NOW)
    monkeypatch.setattr(public_pool_service, "beijing_now", lambda: NOW)
    client, _, customer, *_ = hub
    task = _research_task(db, customer)
    payload = decision(client, task.id, decision="defer", review_after="2026-09-07T09:00:00+08:00")
    response = client.post(f"/api/customer-hub/qualification-queue/{task.id}/decision", json=payload)
    assert response.status_code == 200, response.text
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 0
    monkeypatch.setattr(qualification_service, "beijing_now", lambda: NOW + timedelta(days=2))
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 1


def test_quality_review_and_permission_are_required(db, hub):
    client, identity, customer, *_ = hub
    task = _research_task(db, customer)
    task.result_review_status = "pending"
    db.commit()
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 0
    assert client.get(f"/api/customer-hub/qualification-queue/{task.id}").status_code == 404
    task.result_review_status = "accepted"
    db.flush()
    payload = decision(client, task.id)
    identity["permissions"].remove("sales_automation:write")
    assert client.post(f"/api/customer-hub/qualification-queue/{task.id}/decision", json=payload).status_code == 403


def test_target_scope_decision_does_not_hide_other_targets_but_global_does(db, hub):
    from tests.test_customer_workflow import _review, _search_result

    client, _, customer, *_ = hub
    public = _research_task(db, customer)
    public.source_ref_type = None
    for index, profile_id in enumerate((901, 902)):
        job, result = _search_result(db, customer, job_id=110 + index, result_id=120 + index)
        job.profile_id = profile_id
        task = _research_task(db, customer, task_id=210 + index)
        task.source_ref_type, task.source_ref_id = "search_result", str(result.id)
    db.flush()
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 3
    _review(db, customer, review_source="search_result", source_ref_id="120",
            scope_type="target_profile", scope_ref_id="901")
    rows = client.get("/api/customer-hub/qualification-queue").json()["data"]["items"]
    assert {row["scope_ref_id"] for row in rows} == {"public_pool", "902"}
    _review(db, customer, review_source="manual", source_ref_id=str(customer.id), review_id=302)
    assert client.get("/api/customer-hub/qualification-queue").json()["data"]["total"] == 0


@pytest.mark.parametrize("change", ["rejected", "result", "profile", "newer"])
def test_changed_research_or_profile_cannot_use_old_context(db, hub, change):
    from sqlalchemy.orm import Session
    from app.customer.models import CustomerAccount, CustomerResearchTask

    client, _, customer, profile, _ = hub
    task = _research_task(db, customer)
    task.updated_at = NOW
    db.commit()
    payload = decision(client, task.id)
    with Session(db.get_bind()) as other_session:
        other_task = other_session.get(CustomerResearchTask, task.id)
        if change == "rejected":
            other_task.result_review_status = "rejected"
        elif change == "result":
            other_task.result_json = {"claims": [{"section": "risk", "statement": "研究已更新"}]}
        elif change == "profile":
            other_session.get(CustomerAccount, customer.id).current_profile_version_id = None
        else:
            new = _research_task(other_session, customer, task_id=202)
            new.updated_at = NOW + timedelta(minutes=2)
        other_session.commit()
    response = client.post(f"/api/customer-hub/qualification-queue/{task.id}/decision", json=payload)
    assert response.status_code in (404, 409), response.text
    assert db.query(CustomerQualificationReview).count() == 0
    assert db.query(CustomerAction).count() == 0


def test_qualification_snapshot_rejects_expired_evidence(db, hub):
    from tests.test_customer_evidence_choices import fact

    client, _, customer, *_ = hub
    evidence = fact(db, customer)
    task = _research_task(db, customer)
    task.evidence_fact_ids = [evidence.id]
    db.commit()
    payload = decision(client, task.id)
    evidence.expires_at = NOW - timedelta(days=1)
    db.commit()
    response = client.post(f"/api/customer-hub/qualification-queue/{task.id}/decision", json=payload)
    assert response.status_code == 409, response.text
    assert db.query(CustomerQualificationReview).count() == 0


def test_serializable_boundary_is_set_before_sql_and_never_restarts_a_transaction():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.customer.qualification_transaction import begin_qualification_transaction

    db = Mock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    db.in_transaction.return_value = False
    begin_qualification_transaction(db)
    db.connection.assert_called_once_with(execution_options={"isolation_level": "SERIALIZABLE"})
    db.in_transaction.return_value = True
    with pytest.raises(RuntimeError, match="ALREADY_STARTED"):
        begin_qualification_transaction(db)
    db.rollback.assert_not_called()
