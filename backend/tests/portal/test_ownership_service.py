from app.portal.binding_review_service import context as binding_review_context
"""Customer handoff preserves evidence and resets only selected pending workflows."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from test_admin_service import managed, portal_metadata, new_identity
from test_auth_service import auth_context
from app.core.time import beijing_now
from app.portal import admin_service as admin
from app.portal.models import HistoryGrant, OrderRequest, Quote, Revision
from app.portal.schemas import TransferInput, RebindInput
from app.portal.ownership_service import transfer_customer
from app.portal.errors import PortalError


@pytest.fixture
def handoff(managed, portal_metadata, monkeypatch):
    ctx = managed
    user = portal_metadata.tables["ark_users"]
    ctx.db.execute(user.insert(), {"id": 2, "is_active": True})
    assignment = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(assignment.update().where(assignment.c.id == 1).values(
        assignment_status="inactive", effective_to=beijing_now()))
    ctx.db.execute(assignment.insert(), {"id": 2, "customer_id": 1, "user_id": 2,
        "assignment_role": "primary", "assignment_status": "active", "effective_from": beijing_now()})
    ctx.access.status = "review_required"
    ctx.db.commit()
    monkeypatch.setattr(admin, "employee_principal", lambda db, actor_id, permission:
        {"id": actor_id, "roles": ["super_admin"], "permissions": []})
    return ctx


def request_record(ctx, number, status):
    quote = Quote(access_id=ctx.access.id, account_id=ctx.account.id, membership_id=ctx.member.id,
        expires_at=beijing_now() + timedelta(minutes=5), authority_versions_json={}, input_hash="a"*64,
        result_hash="b"*64, currency="USD", product_amount="10.00", lines_json=[],
        delivery_json={}, payment_terms_snapshot={}, status="consumed")
    ctx.db.add(quote)
    ctx.db.flush()
    row = OrderRequest(access_id=ctx.access.id, account_id=ctx.account.id, customer_id_snapshot=1,
        okki_company_id_snapshot="1", sales_user_id_snapshot=1, servicing_user_id=1,
        public_no=f"POR-HANDOFF-{number}", idempotency_key=str(uuid4()), client_payload_hash="c"*64,
        quote_id=quote.id, submitted_at=beijing_now(), status=status)
    ctx.db.add(row)
    ctx.db.flush()
    return row


def test_transfer_requires_new_acceptance_and_grants_only_existing_history(handoff):
    ctx = handoff
    pending = request_record(ctx, 1, "ready_for_review")
    historical = request_record(ctx, 2, "cancelled")
    revision = Revision(request_id=pending.id, revision_no=1, kind="proposal", currency="USD",
        product_amount="10.00", fees_status="confirmed", delivery_json={}, payment_terms_snapshot={},
        expires_at=beijing_now() + timedelta(hours=24), authority_versions_json={}, mapping_version=0,
        pricing_fingerprint="d"*64, content_hash="e"*64,
        customer_accepted_by=ctx.account.id, customer_accepted_at=beijing_now())
    ctx.db.add(revision)
    ctx.db.flush()
    pending.active_revision_id = pending.accepted_revision_id = revision.id
    ctx.db.commit()
    accepted_at = revision.customer_accepted_at
    result = transfer_customer(ctx.db, 1, ctx.access.public_id, 1,
        TransferInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], assignment_id="2", pending_request_ids=[pending.public_id],
            history_policy="explicit_grant", history_days=30, reason="approved handoff"))
    ctx.db.commit()
    assert result["status"] == "suspended" and result["requires_enable"]
    assert ctx.access.sales_user_id == 2 and ctx.access.assignment_id == 2
    assert pending.servicing_user_id == 2 and pending.status == "submitted" and pending.accepted_revision_id is None
    assert pending.sales_user_id_snapshot == 1 and pending.okki_company_id_snapshot == "1"
    assert revision.customer_accepted_at == accepted_at and revision.customer_accepted_by == ctx.account.id
    assert historical.servicing_user_id == 1 and historical.status == "cancelled"
    grant = ctx.db.scalar(select(HistoryGrant))
    assert grant.grantee_user_id == 2 and grant.order_request_id == historical.id and grant.scope == "order"
    assert result["history_grants"] == 1
    later = request_record(ctx, 3, "submitted")
    ctx.db.commit()
    assert ctx.db.scalar(select(func.count()).select_from(HistoryGrant)) == 1
    assert grant.order_request_id != later.id


def test_transfer_rejects_terminal_or_unknown_selected_requests(handoff):
    ctx = handoff
    terminal = request_record(ctx, 1, "cancelled")
    ctx.db.commit()
    for identifier in (terminal.public_id, str(uuid4())):
        with pytest.raises(PortalError) as error:
            transfer_customer(ctx.db, 1, ctx.access.public_id, 1,
                TransferInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], assignment_id="2", pending_request_ids=[identifier], history_policy="remove", reason="handoff"))
        assert error.value.code == "INVALID_TRANSFER_REQUESTS"
        assert ctx.access.sales_user_id == 1 and ctx.access.row_version == 1


def test_identity_and_owner_can_be_reviewed_in_sequence_without_reopening(handoff, portal_metadata):
    ctx = handoff
    table = portal_metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(table.update().where(table.c.id == 1).values(verification_status="disputed"))
    ctx.db.commit()
    result = transfer_customer(ctx.db, 1, ctx.access.public_id, 1,
        TransferInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], assignment_id="2", pending_request_ids=[], history_policy="remove", reason="owner reviewed"))
    ctx.db.commit()
    assert result["requires_identity_review"] and ctx.access.status == "review_required"
    new_identity(ctx, portal_metadata)
    result = admin.rebind_identity(ctx.db, 1, ctx.access.public_id, 2,
                                   RebindInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], identity_id="2", reason="identity reviewed"))
    ctx.db.commit()
    assert ctx.access.sales_user_id == 2 and ctx.access.okki_company_id == "501"
    assert result["requires_enable"] and ctx.access.status == "suspended"


def test_transfer_does_not_silently_assign_omitted_pending_requests(handoff):
    ctx = handoff
    pending = request_record(ctx, 1, "submitted")
    ctx.db.commit()
    result = transfer_customer(ctx.db, 1, ctx.access.public_id, 1,
        TransferInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], assignment_id="2", pending_request_ids=[], history_policy="remove", reason="handoff"))
    ctx.db.commit()
    assert result["unassigned_pending_request_ids"] == [pending.public_id]
    assert pending.servicing_user_id == 1 and pending.row_version == 1
    assert ctx.db.scalar(select(func.count()).select_from(HistoryGrant)) == 0
