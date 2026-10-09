from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.portal.models import (Account, AuditEvent, CustomerAccess, Membership,
    OrderRequest, PortalSession, Quote, Revision, Site)


@pytest.fixture
def graph(portal_db, portal_metadata):
    db = portal_db
    for name in ("ark_users", "ark_customer_accounts", "ark_customer_external_identities", "ark_customer_assignments"):
        db.execute(portal_metadata.tables[name].insert(), [{"id": 1}, {"id": 2}])
    result = []
    for number in (1, 2):
        site = Site(code=f"site-{number}", name="LeShine", allowed_origin=f"https://site-{number}.example")
        account = Account(email_normalized=f"buyer{number}@example.com", email_display=f"buyer{number}@example.com", contact_name="Buyer")
        db.add_all([site, account])
        db.flush()
        access = CustomerAccess(site_id=site.id, customer_id=number, okki_namespace="okki:test",
            okki_company_id=str(number), external_identity_id=number, binding_fingerprint="a"*64,
            assignment_id=number, sales_user_id=number)
        db.add(access)
        db.flush()
        member = Membership(site_id=site.id, account_id=account.id, access_id=access.id)
        db.add(member)
        db.flush()
        quote = Quote(access_id=access.id, account_id=account.id, membership_id=member.id,
            expires_at=datetime(2026, 10, 2), authority_versions_json={}, input_hash="a"*64,
            result_hash="b"*64, currency="USD", product_amount="10.00", lines_json=[],
            delivery_json={}, payment_terms_snapshot={})
        db.add(quote)
        db.flush()
        request = OrderRequest(access_id=access.id, account_id=account.id, customer_id_snapshot=number,
            okki_company_id_snapshot=str(number), sales_user_id_snapshot=number, servicing_user_id=number,
            public_no=f"POR-{number}", idempotency_key=str(uuid4()), client_payload_hash="c"*64,
            quote_id=quote.id, submitted_at=datetime(2026, 10, 1))
        db.add(request)
        db.flush()
        revision = Revision(request_id=request.id, revision_no=1, kind="submitted", currency="USD",
            product_amount="10.00", fees_status="pending", delivery_json={}, payment_terms_snapshot={},
            expires_at=datetime(2026, 10, 2), authority_versions_json={}, mapping_version=0,
            pricing_fingerprint="d"*64, content_hash="e"*64)
        db.add(revision)
        db.flush()
        request.active_revision_id = revision.id
        db.flush()
        result.append(dict(site=site, account=account, access=access, member=member,
                           quote=quote, request=request, revision=revision))
    db.commit()
    return result


def test_membership_cannot_cross_site(portal_db, graph):
    a, b = graph
    fresh = Account(email_normalized="third@example.com", email_display="third@example.com", contact_name="Third")
    portal_db.add(fresh)
    portal_db.flush()
    portal_db.add(Membership(site_id=a["site"].id, access_id=b["access"].id, account_id=fresh.id))
    with pytest.raises(IntegrityError):
        portal_db.flush()


def test_session_cannot_use_another_accounts_membership(portal_db, graph):
    a, b = graph
    portal_db.add(PortalSession(account_id=a["account"].id, membership_id=b["member"].id,
        account_version=1, access_version=1, membership_version=1, token_hash="f"*64,
        csrf_nonce="a"*64, csrf_key_version="v1", expires_at=datetime(2026, 10, 2),
        idle_expires_at=datetime(2026, 10, 1, 1)))
    with pytest.raises(IntegrityError):
        portal_db.flush()


def test_request_cannot_point_to_another_requests_revision(portal_db, graph):
    a, b = graph
    a["request"].active_revision_id = b["revision"].id
    with pytest.raises(IntegrityError):
        portal_db.flush()


def test_quote_cannot_cross_membership_scope(portal_db, graph):
    a, b = graph
    # Use Core to bypass ORM immutability deliberately: the DB must still reject it.
    with pytest.raises(IntegrityError):
        portal_db.execute(Quote.__table__.update().where(Quote.id == a["quote"].id).values(membership_id=b["member"].id))


def test_accepted_snapshot_cannot_be_repriced(portal_db, graph):
    revision = graph[0]["revision"]
    assert revision.product_amount == 10
    revision.product_amount = "999.00"
    with pytest.raises(ValueError, match="immutable"):
        portal_db.flush()


def test_customer_acceptance_is_write_once(portal_db, graph):
    revision = graph[0]["revision"]
    assert revision.customer_accepted_by is None
    revision.customer_accepted_by = graph[0]["account"].id
    revision.customer_accepted_at = datetime(2026, 10, 1)
    portal_db.commit()
    assert revision.customer_accepted_by == graph[0]["account"].id
    revision.customer_accepted_at = datetime(2026, 10, 1, 1)
    with pytest.raises(ValueError, match="immutable"):
        portal_db.flush()


def test_audit_cannot_be_rewritten_or_deleted(portal_db):
    row = AuditEvent(actor_type="system", object_type="site", object_public_id=str(uuid4()),
                     action="enabled", trace_id="trace-test", safe_diff_json={})
    portal_db.add(row)
    portal_db.commit()
    assert row.action == "enabled"
    row.action = "disabled"
    with pytest.raises(ValueError, match="immutable"):
        portal_db.flush()
    portal_db.rollback()
    portal_db.delete(row)
    with pytest.raises(ValueError, match="retained"):
        portal_db.flush()
