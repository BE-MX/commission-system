from datetime import date, datetime, timedelta

from app.core.time import beijing_today
from app.domestic_followup import followup_service
from app.domestic_followup.collaboration_access import create_initial_responsibility
from app.domestic_followup.collaboration_models import FollowupScope
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupTask
from tests.domestic_followup_helpers import ALL_PERMS, followup_client, grant, make_customer, make_shipment, make_user, seed_dicts


def _record(db, user, customer, key, *, day=None, summary="内部原文"):
    row = DomesticFollowup(
        customer_id=customer.id, author_user_id=user.id, followup_date=day or beijing_today(),
        request_id=key, status="confirmed", raw_text=summary,
    )
    db.add(row)
    db.flush()
    return row


def test_public_sea_release_keeps_independent_tasks_and_single_writer(db):
    seed_dicts(db)
    previous, incoming, outsider = [make_user(db, "fuc_" + label) for label in ("previous", "incoming", "outsider")]
    for user in (previous, incoming, outsider):
        grant(db, user, *ALL_PERMS)
    customer = make_customer(db, previous, "独立跟进责任")
    responsibility = create_initial_responsibility(db, customer.id, incoming.id)
    task = DomesticFollowupTask(
        customer_id=customer.id, assignee_user_id=incoming.id, source_key="plan:independent", task_type="plan",
        purpose="development", title="约定电话", due_date=beijing_today(),
    )
    db.add(task)
    db.commit()
    customer.owner_user_id = None
    db.commit()
    assert responsibility.owner_user_id == incoming.id
    assert task.status == "todo" and task.assignee_user_id == incoming.id
    for actor in (previous, outsider):
        with followup_client(db, actor, (*ALL_PERMS, "domestic_followup:read_all")) as client:
            denied = client.post("/api/domestic-followup/followups", json={
                "result_code": "有效沟通",
                "customer_id": customer.id, "raw_text": "不能抢跟", "request_id": f"denied-{actor.id}",
            })
            assert denied.status_code == 403, denied.text
            assert client.post(f"/api/domestic-followup/tasks/{task.id}/snooze", json={"days": 1}).status_code == 403


def test_former_author_retains_record_but_cannot_change_transferred_plan(db):
    seed_dicts(db)
    original, current = [make_user(db, "fuc_" + label) for label in ("author", "current")]
    for user in (original, current):
        grant(db, user, *ALL_PERMS)
    customer = make_customer(db, original, "交接后的历史")
    create_initial_responsibility(db, customer.id, current.id)
    row = _record(db, original, customer, "old-contact")
    row.next_date = beijing_today() + timedelta(days=3)
    row.next_plan = "复核型号"
    moved = DomesticFollowupTask(
        customer_id=customer.id, assignee_user_id=current.id, source_key="plan:moved", task_type="plan",
        purpose="development", title="复核型号", due_date=row.next_date, source_followup_id=row.id,
    )
    db.add(moved)
    db.commit()
    record_path = f"/api/domestic-followup/followups/{row.id}"
    body = {"version": row.version, "request_id": "edit-old-contact", "reason": "纠正客户原话",
            "result_code": "有效沟通",
            "raw_text": "原话更正", "followup_date": row.followup_date.isoformat(), "next_plan": row.next_plan,
            "next_date": row.next_date.isoformat()}
    with followup_client(db, original) as client:
        assert client.get(record_path).json()["data"]["historical_edit"] is True
        changed_due = {**body, "next_date": (row.next_date + timedelta(days=1)).isoformat()}
        assert client.put(record_path, json=changed_due).status_code == 400
        correction = client.put(record_path, json=body)
        assert correction.status_code == 200, correction.text
    assert moved.assignee_user_id == current.id and moved.due_date == row.next_date
    assert row.author_user_id == original.id and row.raw_text == "原话更正"


def test_receipt_assignment_does_not_grant_development_access(db):
    seed_dicts(db)
    owner, service = [make_user(db, "fuc_" + label) for label in ("owner", "service")]
    grant(db, owner, *ALL_PERMS)
    grant(db, service, *ALL_PERMS)
    customer = make_customer(db, owner, "有售后待办")
    create_initial_responsibility(db, customer.id, owner.id)
    receipt = DomesticFollowupTask(
        customer_id=customer.id, assignee_user_id=service.id, source_key="receipt:service", task_type="receipt",
        title="收货回访", due_date=beijing_today(),
    )
    db.add(receipt)
    db.commit()
    with followup_client(db, service) as client:
        path = "/api/domestic-followup/followups"
        body = {"request_id": "service-tries-plan", "customer_id": customer.id, "source_task_id": receipt.id,
                "result_code": "有效沟通",
                "raw_text": "收货反馈", "next_date": (beijing_today() + timedelta(days=1)).isoformat()}
        denied = client.post(path, json=body)
        assert denied.status_code == 403, denied.text
        receipt_ok = client.post(f"/api/domestic-followup/tasks/{receipt.id}/receipt-ok",
                                 json={"request_id": "service-receipt-ok"})
        assert receipt_ok.status_code == 200, receipt_ok.text
    assert receipt.status == "done"


def test_new_owner_has_paginated_communication_without_shipment_data(db):
    original, current, member = [make_user(db, "fuc_" + label) for label in ("finance", "follow", "summary")]
    for user in (original, current, member):
        grant(db, user, *ALL_PERMS)
    customer = make_customer(db, original, "有交接历史")
    create_initial_responsibility(db, customer.id, current.id)
    db.add(FollowupScope(user_id=member.id, customer_id=customer.id, scope_key=f"c:{customer.id}",
                         added_by_user_id=original.id))
    make_shipment(db, customer, original, datetime(2025, 1, 1))
    db.add_all(DomesticFollowup(customer_id=customer.id, author_user_id=original.id, followup_date=date(2025, 2, 1),
                                request_id=f"paginated-{i}", status="confirmed", raw_text=f"记录{i}")
               for i in range(102))
    db.commit()
    path = f"/api/domestic-followup/customers/{customer.id}/timeline"
    with followup_client(db, current) as client:
        first = client.get(path).json()["data"]
        second = client.get(path, params={"offset": first["next_offset"]}).json()["data"]
        assert [len(first["events"]), len(second["events"])] == [100, 2]
        assert not second["has_more"]
        assert {e["type"] for e in first["events"] + second["events"]} == {"followup"}
        assert not set(e["data"]["id"] for e in first["events"]) & set(e["data"]["id"] for e in second["events"])
    with followup_client(db, original) as client:
        assert client.get(path, params={"event_type": "shipment"}).json()["data"]["events"][0]["type"] == "shipment"
    with followup_client(db, member) as client:
        assert client.get(path).status_code == 403


def test_historical_supplement_cannot_change_live_arrangement(db):
    seed_dicts(db)
    old, current = [make_user(db, "fuc_" + label) for label in ("old2", "current2")]
    for user in (old, current):
        grant(db, user, *ALL_PERMS)
    customer = make_customer(db, old, "保留沟通事实")
    responsibility = create_initial_responsibility(db, customer.id, current.id)
    _record(db, old, customer, "older-communication")
    db.commit()
    data = {"customer_id": customer.id, "request_id": "old-user-supplement", "raw_text": "补录原沟通",
            "result_code": "有效沟通",
            "followup_date": (beijing_today() - timedelta(days=1)).isoformat(), "historical_only": True}
    with followup_client(db, old) as client:
        path = "/api/domestic-followup/followups"
        denied = client.post(path, json={**data, "development_stage": "quoted"})
        assert denied.status_code == 400, denied.text
        stored = client.post(path, json=data)
        assert stored.status_code == 200, stored.text
    assert responsibility.owner_user_id == current.id and responsibility.stage == "new"
    assert db.query(DomesticFollowupTask).count() == 0


def test_collaborator_plan_belongs_to_current_responsibility_and_needs_version(db):
    from app.domestic_followup.collaboration_models import FollowupCollaborator

    seed_dicts(db)
    finance, current, collaborator = [make_user(db, "fuc_" + label) for label in ("finance2", "owner2", "partner2")]
    for user in (finance, current, collaborator):
        grant(db, user, *ALL_PERMS)
    customer = make_customer(db, finance, "协作人制定下一步")
    responsibility = create_initial_responsibility(db, customer.id, current.id)
    db.add_all([
        FollowupScope(user_id=collaborator.id, customer_id=customer.id, scope_key=f"c:{customer.id}",
                      added_by_user_id=current.id),
        FollowupCollaborator(user_id=collaborator.id, customer_id=customer.id, added_by_user_id=current.id),
    ])
    db.commit()
    next_date = beijing_today() + timedelta(days=5)
    body = {"request_id": "partner-plans", "customer_id": customer.id, "raw_text": "客户确认复核型号",
            "next_date": next_date.isoformat(), "plan_purpose": "development", "development_stage": "quoted",
            "responsibility_version": responsibility.version, "result_code": "有效沟通", "effective_progress": True}
    with followup_client(db, collaborator) as client:
        path = "/api/domestic-followup/followups"
        assert client.post(path, json={**body, "result_code": "未接通"}).status_code == 400
        assert client.post(path, json={**body, "responsibility_version": 999}).status_code == 409
        saved = client.post(path, json=body)
        assert saved.status_code == 200, saved.text
    task = db.query(DomesticFollowupTask).one()
    assert (task.assignee_user_id, task.purpose, task.due_date) == (current.id, "development", next_date)
    assert responsibility.stage == "quoted" and responsibility.next_plan_date == next_date
    assert responsibility.last_progress_at.date() == beijing_today()
    assert customer.owner_user_id == finance.id

    extra = {**body, "request_id": "partner-assignee", "responsibility_version": responsibility.version}
    with followup_client(db, current) as client:
        path = "/api/domestic-followup/followups"
        assert client.post(path, json={**extra, "plan_assignee_user_id": finance.id}).status_code == 400
        delegated = client.post(path, json={**extra, "plan_assignee_user_id": collaborator.id})
        assert delegated.status_code == 200, delegated.text
    assert db.query(DomesticFollowupTask).filter_by(assignee_user_id=collaborator.id, purpose="development").count() == 1
