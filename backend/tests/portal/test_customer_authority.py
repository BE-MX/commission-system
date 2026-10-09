"""Upstream assignment SQL with portal revocation; event delivery is stubbed."""
from types import SimpleNamespace
from uuid import uuid4
from datetime import timedelta

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, event, select

from test_auth_service import auth_context, send_code, verify
from test_admin_service import managed, portal_metadata, invitation_body
from app.customer import workflow_service as workflow
from app.customer.models import CustomerAction, CustomerAssignment, CustomerOpportunity
from app.auth.models import ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.portal import authority, admin_service as admin
from app.core.time import beijing_now
from app.portal.models import AuthorityBarrier, Invitation, PortalSession, Quote


@pytest.fixture
def customer_context(managed, portal_metadata, monkeypatch):
    ctx = managed
    metadata = MetaData()
    for model in (CustomerAction, CustomerOpportunity, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission):
        Table(model.__tablename__, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
              primary_key=c.primary_key, nullable=not c.primary_key) for c in model.__table__.columns))
    metadata.create_all(ctx.db.get_bind())
    users = portal_metadata.tables["ark_users"]
    ctx.db.execute(users.insert(), {"id": 2, "is_active": True})
    ctx.db.commit()
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=True))
    monkeypatch.setattr(workflow, "append_customer_event", lambda *a, **k: None)
    return ctx


def transfer(ctx):
    return workflow.transfer_primary_owner(ctx.db, customer_id=1, new_user_id=2,
        operated_by=1, change_reason="Customer handoff")


def test_transfer_revokes_session_invitation_and_keeps_old_binding(customer_context):
    ctx = customer_context
    challenge, code = send_code(ctx)
    _, session, _ = verify(ctx, challenge, code)
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    before = ctx.access.auth_version
    ctx.db.commit()
    statements = []
    def capture(connection, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(ctx.db.get_bind(), "before_cursor_execute", capture)
    try:
        row = transfer(ctx)
        assert AuthorityBarrier.__tablename__ in statements[0]
        ctx.db.commit()
    finally:
        event.remove(ctx.db.get_bind(), "before_cursor_execute", capture)
    assert row.user_id == 2
    assert ctx.access.status == "review_required" and ctx.access.auth_version == before + 1
    assert ctx.access.sales_user_id == 1 and ctx.access.assignment_id == 1
    assert ctx.db.get(PortalSession, session.id).revoked_at is not None
    assert ctx.db.scalar(select(Invitation)).revoked_at is not None


def test_transfer_rollback_restores_assignment_and_portal(customer_context):
    ctx = customer_context
    before = ctx.access.auth_version
    ctx.db.commit()
    transfer(ctx)
    ctx.db.rollback()
    assert ctx.access.status == "enabled" and ctx.access.auth_version == before
    old = ctx.db.get(CustomerAssignment, 1)
    assert old.assignment_status == "active" and old.effective_to is None
    assert ctx.db.scalar(select(CustomerAssignment).where(CustomerAssignment.user_id == 2)) is None


@pytest.mark.parametrize("operation", ["same_owner", "existing_assignment", "collaborator"])
def test_nonownership_changes_do_not_revoke_access(customer_context, operation):
    ctx = customer_context
    before = ctx.access.auth_version
    if operation == "same_owner":
        workflow.transfer_primary_owner(ctx.db, customer_id=1, new_user_id=1,
            operated_by=1, change_reason="No change")
    else:
        workflow.assign_customer(ctx.db, customer_id=1, user_id=1 if operation == "existing_assignment" else 2,
            assignment_role="primary" if operation == "existing_assignment" else "collaborator",
            assignment_source="admin_assign", operated_by=1)
    ctx.db.commit()
    assert ctx.access.status == "enabled" and ctx.access.auth_version == before


def test_suspension_requires_barrier_before_upstream_mutation(customer_context):
    ctx = customer_context
    with pytest.raises(RuntimeError, match="did not acquire"):
        authority.suspend_customer_access(ctx.db, {1})


def test_suspension_expires_only_unconsumed_quotes_and_is_idempotent(customer_context):
    ctx = customer_context
    quotes = [Quote(access_id=ctx.access.id, account_id=ctx.account.id, membership_id=ctx.member.id,
        expires_at=beijing_now() + timedelta(minutes=5), authority_versions_json={}, input_hash="a"*64,
        result_hash="b"*64, currency="USD", product_amount="10.00", lines_json=[],
        delivery_json={}, payment_terms_snapshot={}, status=status) for status in ("valid", "consumed")]
    ctx.db.add_all(quotes)
    ctx.db.commit()
    before = ctx.access.auth_version
    ctx.db.commit()
    authority.lock_authority(ctx.db)
    authority.suspend_customer_access(ctx.db, {1})
    authority.suspend_customer_access(ctx.db, {1})
    ctx.db.commit()
    assert [row.status for row in quotes] == ["expired", "consumed"]
    assert ctx.access.auth_version == before + 1


@pytest.mark.parametrize("operation", ["proposal", "ownership_execution", "ownership_cas", "claim"])
def test_entrypoints_lock_authority_before_any_business_read(customer_context, monkeypatch, operation):
    from app.customer import proposal_service, ownership_execution_service, ownership_service
    ctx = customer_context
    class StopAfterLock(Exception):
        pass
    def stop(db):
        raise StopAfterLock()
    modules = {"proposal": proposal_service, "ownership_execution": ownership_execution_service,
               "ownership_cas": ownership_service, "claim": workflow}
    monkeypatch.setattr(modules[operation], "lock_authority", stop)
    calls = {
        "proposal": lambda: proposal_service.execute_proposal(ctx.db, proposal_id=999, actor_user_id=1, idempotency_key="x"),
        "ownership_execution": lambda: ownership_execution_service.execute_customer_ownership_change(ctx.db,
            proposal_id=999, actor_user_id=1, idempotency_key="x"),
        "ownership_cas": lambda: ownership_service.compare_and_set_effective_owner(ctx.db,
            object_type="external_identity", object_id=1, storage_customer_id=1, expected_current_customer_id=1,
            current_customer_id=2, expected_version=0, change_proposal_id=999, action_type="merge"),
        "claim": lambda: workflow.claim_public_pool_customer(ctx.db, customer_id=999, claimant_user_id=1,
            operated_by=1, scope_type="global", scope_ref_id=None, allowed_user_ids={1}, per_user_quota=1),
    }
    statements = []
    def capture(connection, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(ctx.db.get_bind(), "before_cursor_execute", capture)
    try:
        with pytest.raises(StopAfterLock):
            calls[operation]()
        assert not statements
    finally:
        event.remove(ctx.db.get_bind(), "before_cursor_execute", capture)
