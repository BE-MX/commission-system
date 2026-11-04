from datetime import date

from app.domestic_followup import followup_service, task_service
from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem, DomesticFollowupTask
from tests.domestic_followup_helpers import followup_client, make_customer, make_user


def test_potential_filter_uses_current_customer_status_across_all_views(db):
    owner, outsider = make_user(db, "potential_owner"), make_user(db, "potential_other")
    prospects = [make_customer(db, user, f"潜在店{i}") for i, user in enumerate([owner, outsider])]
    established = make_customer(db, owner, "已成交店")
    established.lifecycle_status = "已成交"
    unknown = make_customer(db, owner, "未标状态店")
    unknown.lifecycle_status = None
    for customer in prospects:
        customer.lifecycle_status = "潜在"
    records = []
    for index, customer in enumerate([*prospects, established, unknown]):
        author = owner if index != 1 else outsider
        row = DomesticFollowup(author_user_id=author.id, customer_id=customer.id, status="confirmed",
                               followup_date=date(2026, 11, 1), request_id=f"potential-{index}")
        db.add(row)
        db.flush()
        records.append(row)
        db.add(DomesticFollowupTask(task_type="plan", customer_id=customer.id, assignee_user_id=author.id,
                                    source_key=f"potential-{index}", title=customer.shop_name, due_date=date(2026, 11, 1)))
        db.add(DomesticFollowupItem(followup_id=row.id, customer_id=customer.id, seq=1, kind="issue", text="测试",
                                   status="open", handler_user_id=author.id))
    db.flush()
    for index, customer in enumerate([prospects[0], established, None]):
        db.add(DomesticFollowup(author_user_id=owner.id, customer_id=customer.id if customer else None,
                               status="draft", ai_status="none", followup_date=date(2026, 11, 1),
                               request_id=f"potential-draft-{index}"))
    db.flush()
    with followup_client(db, owner) as client:
        for path, params, key in (
            ("followups", {"mine": True}, "customer_id"), ("tasks", {"due": "all"}, "customer_id"),
            ("items", {}, "customer_id"),
        ):
            all_data = client.get(f"/api/domestic-followup/{path}", params=params).json()["data"]
            assert all_data["total"] == 3
            filtered = client.get(f"/api/domestic-followup/{path}", params={**params, "potential_only": True}).json()["data"]
            assert filtered["total"] == 1 and filtered["items"][0][key] == prospects[0].id
        summary = client.get("/api/domestic-followup/tasks/summary", params={"potential_only": True}).json()["data"]
        assert summary["plan"] == 1
        authors = client.get("/api/domestic-followup/followups/authors", params={"potential_only": True}).json()["data"]
        assert [author["id"] for author in authors] == [owner.id]
        drafts = client.get("/api/domestic-followup/drafts", params={"potential_only": True}).json()["data"]
        assert len(drafts) == 1 and drafts[0]["customer_id"] == prospects[0].id
        # Change a customer's current lifecycle; historical records immediately follow it.
        prospects[0].lifecycle_status = "已成交"
        db.flush()
        assert client.get("/api/domestic-followup/followups", params={"potential_only": True}).json()["data"]["total"] == 0
    with followup_client(db, owner, roles=["super_admin"]) as client:
        result = client.get("/api/domestic-followup/followups", params={"potential_only": True}).json()["data"]
        assert [row["id"] for row in result["items"]] == [records[1].id]
