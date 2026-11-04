"""Overview filters must preserve record visibility and historical authors."""
from datetime import date

import pytest

from app.domestic_followup.models import DomesticFollowup, DomesticFollowupItem
from tests.domestic_followup_helpers import followup_client, make_customer, make_user


@pytest.fixture
def records(db):
    owner, partner, outsider, boss = [make_user(db, f"overview_{n}") for n in ("owner", "partner", "other", "boss")]
    customer = make_customer(db, owner, "100%客户", commission_users=[partner])
    other = make_customer(db, outsider, "其他客户")
    rows = []
    for author, client, day, status in (
        (owner, customer, 1, "confirmed"), (partner, customer, 2, "confirmed"),
        (outsider, other, 3, "confirmed"), (outsider, other, 4, "draft"),
        (owner, customer, 5, "discarded"),
    ):
        row = DomesticFollowup(author_user_id=author.id, customer_id=client.id,
                               followup_date=date(2026, 11, day), status=status,
                               request_id=f"overview-{day}", summary=f"Summary {day}")
        db.add(row)
        rows.append(row)
    draft_only = make_user(db, "overview_draft_only")
    db.add(DomesticFollowup(author_user_id=draft_only.id, customer_id=other.id,
                           followup_date=date(2026, 11, 1), status="draft", request_id="overview-only-draft"))
    db.flush()
    db.add(DomesticFollowupItem(followup_id=rows[1].id, customer_id=customer.id,
                               seq=1, kind="content", text="独有要点"))
    db.flush()
    return owner, partner, outsider, boss, rows


def test_overview_filters_intersect_visibility(db, records):
    owner, partner, outsider, _, rows = records
    with followup_client(db, owner) as client:
        data = client.get("/api/domestic-followup/followups").json()["data"]
        assert {r["id"] for r in data["items"]} == {rows[0].id, rows[1].id}
        filtered = client.get("/api/domestic-followup/followups", params={"author_user_id": partner.id}).json()["data"]
        assert [r["id"] for r in filtered["items"]] == [rows[1].id]
        hidden = client.get("/api/domestic-followup/followups", params={"author_user_id": outsider.id}).json()["data"]
        assert hidden["total"] == 0
        assert client.get("/api/domestic-followup/followups", params={"keyword": "Summary 3"}).json()["data"]["total"] == 0
        mine = client.get("/api/domestic-followup/followups", params={"mine": True}).json()["data"]
        assert [r["id"] for r in mine["items"]] == [rows[0].id]


@pytest.mark.parametrize("roles,extra", [(["super_admin"], []), ([], ["domestic_followup:read_all"])])
def test_all_scope_filters_dates_authors_keyword_and_pagination(db, records, roles, extra):
    _, partner, _, boss, rows = records
    with followup_client(db, boss, roles=roles, permissions=["domestic_followup:read", *extra]) as client:
        data = client.get("/api/domestic-followup/followups", params={"page_size": 1}).json()["data"]
        assert data["total"] == 3 and data["items"][0]["id"] == rows[2].id
        second = client.get("/api/domestic-followup/followups", params={"page_size": 1, "page": 2}).json()["data"]
        assert second["items"][0]["id"] == rows[1].id
        for params in ({"author_user_id": partner.id}, {"date_from": "2026-11-02", "date_to": "2026-11-02"},
                       {"keyword": "独有要点"}, {"keyword": "Summary 2"}):
            data = client.get("/api/domestic-followup/followups", params=params).json()["data"]
            assert [r["id"] for r in data["items"]] == [rows[1].id]
        assert client.get("/api/domestic-followup/followups", params={"keyword": "%"}).json()["data"]["total"] == 2
        assert client.get("/api/domestic-followup/followups", params={"date_from": "2026-11-03", "date_to": "2026-11-01"}).status_code == 400
        assert client.get("/api/domestic-followup/followups", params={"date_from": "invalid"}).status_code == 422


def test_author_options_are_scoped_read_only_and_include_inactive_authors(db, records):
    owner, partner, outsider, boss, _ = records
    partner.is_active = False
    db.flush()
    with followup_client(db, owner, permissions=["domestic_followup:read"]) as client:
        response = client.get("/api/domestic-followup/followups/authors")
        assert response.status_code == 200
        assert {r["id"] for r in response.json()["data"]} == {owner.id, partner.id}
    with followup_client(db, boss, roles=["super_admin"]) as client:
        assert {r["id"] for r in client.get("/api/domestic-followup/followups/authors").json()["data"]} == {owner.id, partner.id, outsider.id}
    with followup_client(db, boss, permissions=["domestic_followup:read_all"]) as client:
        assert client.get("/api/domestic-followup/followups/authors").status_code == 403
        assert client.get("/api/domestic-followup/followups").status_code == 403
