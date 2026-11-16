from datetime import date, datetime

from sqlalchemy import text

from app.auth.models import ArkUser
from app.invoice.customer_picker_service import search_options
from app.invoice.models import Invoice, InvoiceCustomerOverlay
from tests.test_invoice_customer_filters import _client, bound_user, seed_customers, OKKI_UID


def test_browse_all_126_customers(db):
    db.execute(text("""INSERT INTO lsordertest.customer_info
        (company_id, company_name, owner_user_ids) VALUES (:id, :name, :owner)"""), [
        {"id": str(10000 + i), "name": f"Customer {i:03}", "owner": f"[{OKKI_UID}]"}
        for i in range(126)
    ])
    pages = [search_options(db, owner_okki_id=OKKI_UID, offset=offset) for offset in (0, 50, 100)]
    assert [len(page["items"]) for page in pages] == [50, 50, 26]
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert all(page["total"] == 126 for page in pages)
    assert len({row["option_key"] for page in pages for row in page["items"]}) == 126
    assert search_options(db, keyword="10125", owner_okki_id=OKKI_UID)["total"] == 1


def test_keyword_matches_customer_and_contact_without_cross_owner_leak(db, seed_customers):
    result = search_options(db, keyword="a", owner_okki_id=OKKI_UID)
    assert {row["kind"] for row in result["items"]} == {"customer", "contact"}
    assert {row["company_id"] for row in result["items"]} == {"9001"}
    contact = search_options(db, keyword="Alice", owner_okki_id=OKKI_UID)["items"][0]
    assert contact["email"] == "alice@x.com"
    assert contact["tel"] == "111"
    assert contact["company_name"] == "Alpha Hair Studio"
    assert len(search_options(db, keyword="Alice")["items"]) == 2
    assert search_options(db, keyword="%", owner_okki_id=OKKI_UID)["total"] == 0


def test_contacts_follow_effective_overlay_owner_and_name(db, seed_customers):
    db.add(InvoiceCustomerOverlay(
        company_id="9001", company_name="Renamed Company", owner_user_ids=["99999999"],
        source_update_time="2026-09-17 12:00:00",
    ))
    db.flush()
    assert search_options(db, keyword="Alice", owner_okki_id=OKKI_UID)["total"] == 0
    result = search_options(db, keyword="Alice", owner_okki_id=99999999)
    assert result["total"] == 1
    assert result["items"][0]["company_name"] == "Renamed Company"
    assert search_options(db, keyword="Alpha", owner_okki_id=99999999)["total"] == 0


def test_newer_mirror_wins_and_overlay_only_customers_are_paginated(db, seed_customers):
    db.execute(text("ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT"))
    db.execute(text("UPDATE lsordertest.customer_info SET update_time='2026-09-17 12:00:00'"))
    db.add(InvoiceCustomerOverlay(
        company_id="9001", company_name="Stale Name", owner_user_ids=["99999999"],
        source_update_time="2026-09-16 12:00:00",
    ))
    for i in range(60):
        db.add(InvoiceCustomerOverlay(
            company_id=str(20000 + i), company_name=f"Overlay {i:03}",
            owner_user_ids=[str(OKKI_UID)], source_update_time="2026-09-17 12:00:00",
        ))
    db.flush()
    first = search_options(db, owner_okki_id=OKKI_UID)
    second = search_options(db, owner_okki_id=OKKI_UID, offset=50)
    assert first["total"] == second["total"] == 61
    assert len(first["items"]) == 50
    assert len(second["items"]) == 11
    assert len({row["option_key"] for row in first["items"] + second["items"]}) == 61
    assert search_options(db, keyword="Alice", owner_okki_id=OKKI_UID)["total"] == 1
    assert search_options(db, keyword="Stale")["total"] == 0


def test_picker_route_binding_and_paging(db, seed_customers, bound_user):
    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        response = client.get("/api/invoice/customers/options", params={"keyword": "Alice", "limit": 1})
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["okki_bound"] is True
        assert payload["items"][0]["kind"] == "contact"
        assert payload["total"] == 1
        assert client.get("/api/invoice/customers/options", params={"offset": -1}).status_code == 422
    db.add(ArkUser(id=77, username="unbound-picker", password_hash="x", real_name="Unbound"))
    db.flush()
    with _client(db, sub="77", permissions=["invoice:write"]) as client:
        payload = client.get("/api/invoice/customers/options").json()["data"]
        assert payload == {"items": [], "total": 0, "has_more": False, "okki_bound": False}
    with _client(db, sub="5", permissions=["invoice:read"]) as client:
        assert client.get("/api/invoice/customers/options").status_code == 403


def test_picker_contact_phone_uses_latest_matching_invoice_only(db, seed_customers, bound_user):
    db.execute(text("""
        UPDATE lsordertest.customer_contacts SET email='aaron@example.test' WHERE id=2
    """))
    records = [
        ("9001", "Aaron Lee", "aaron@example.test", "100", "synced", 1),
        ("9001", "Aaron Lee", "aaron@example.test", "200", "synced", 2),
        ("9001", " Aaron LEE ", " Aaron@example.test ", "201", "synced", 2),
        ("9001", "Aaron Lee", "aaron@example.test", "\t\n\u00a0", "synced", 3),
        ("9001", "Aaron Lee", "other@example.test", "300", "synced", 4),
        ("9001", "Alice Wang", "alice@x.com", "400", "synced", 5),
        ("9002", "Aaron Lee", "aaron@example.test", "500", "synced", 6),
        ("9001", "Aaron Lee", "aaron@example.test", "600", "deleted", 7),
    ]
    for index, (cid, name, email, phone, status, day) in enumerate(records):
        db.add(Invoice(
            customer_id=cid, customer_name="Salon", invoice_no=f"PHONE-{index}",
            invoice_date=date(2026, 11, day), created_at=datetime(2026, 11, day),
            contact_name=name, contact_email=email, contact_phone=phone, status=status,
        ))
    db.flush()

    with _client(db, sub="5", permissions=["invoice:write"]) as client:
        def phone_for(keyword):
            response = client.get("/api/invoice/customers/options", params={"keyword": keyword})
            assert response.status_code == 200
            return response.json()["data"]["items"][0]["tel"]

        assert phone_for("Aaron Lee") == "201"
        assert phone_for("Alice Wang") == "111"


def test_picker_contact_phone_skips_ambiguous_names(db, seed_customers):
    db.execute(text("""
        UPDATE lsordertest.customer_contacts SET email='aaron@example.test', tel=:blank WHERE id=2
    """), {"blank": " \t\n\u00a0"})
    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts (id, company_id, name, email)
        VALUES (5, '9001', 'Aaron Lee', 'other@example.test'),
               (6, '9001', 'Aaron Lee', NULL)
    """))
    for index, email in enumerate(["aaron@example.test", None]):
        db.add(Invoice(
            customer_id="9001", customer_name="Salon", invoice_no=f"SAME-NAME-{index}",
            invoice_date=date(2026, 11, 1 + index), created_at=datetime(2026, 11, 1 + index),
            contact_name="Aaron Lee", contact_email=email, contact_phone=f"20{index}",
        ))
    db.flush()

    def phones():
        return {row["contact_id"]: row["tel"] for row in search_options(db, keyword="Aaron Lee")["items"]}

    assert phones() == {2: "200", 5: None, 6: None}
    db.execute(text("UPDATE lsordertest.customer_contacts SET email='aaron@example.test' WHERE id=5"))
    assert phones() == {2: None, 5: None, 6: None}


def test_picker_contact_phone_accepts_unique_name_without_email(db, seed_customers):
    db.add(Invoice(
        customer_id="9001", customer_name="Salon", invoice_no="UNIQUE-NAME",
        invoice_date=date(2026, 11, 1), contact_name="Aaron Lee", contact_phone="200",
    ))
    db.flush()

    contact = search_options(db, keyword="Aaron Lee")["items"][0]
    assert contact["tel"] == "200"
