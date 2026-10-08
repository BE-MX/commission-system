from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from test_auth_service import auth_context
from test_admin_service import managed, portal_metadata
from app.core.time import beijing_now
from app.customer import identity_service as identity
from app.customer.models import CustomerExternalIdentity
from app.portal import authority, access_policy
from app.portal.access_policy import validate_binding as real_validate_binding


@pytest.fixture
def identity_context(managed, portal_metadata, monkeypatch):
    ctx = managed
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=True))
    monkeypatch.setattr(access_policy, "validate_binding", real_validate_binding)
    customers = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(customers.update().values(profile_input_seq=0))
    identities = portal_metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(identities.update().values(confidence=Decimal("0.8"), last_seen_at=beijing_now(),
        first_seen_at=beijing_now(), raw_value="1", auto_match_ceiling="verified"))
    ctx.db.commit()
    return ctx


def test_identity_evidence_refresh_keeps_current_portal_binding(identity_context):
    ctx = identity_context
    before = ctx.access.auth_version
    ctx.db.commit()
    row = identity.attach_identity_candidate(ctx.db, customer_id=1, source_system="okki",
        source_account_key="okki:test", identifier_type="company_id", raw_value="1",
        verification_status="verified", confidence=Decimal("0.95"))
    ctx.db.commit()
    assert row.id == 1 and row.confidence == Decimal("0.95")
    assert ctx.access.status == "enabled" and ctx.access.auth_version == before


def test_confirmation_conflict_pauses_access_in_same_transaction(identity_context, portal_metadata, monkeypatch):
    ctx = identity_context
    customers = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(customers.insert(), {"id": 2, "record_status": "active", "identity_status": "verified", "profile_input_seq": 0})
    table = portal_metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(table.insert(), {"id": 2, "customer_id": 2, "source_system": "okki",
        "source_account_key": "okki:test", "identifier_type": "company_id", "normalized_value": "1",
        "identity_strength": "strong", "cardinality": "one_to_one", "verification_status": "verified",
        "status": "active", "confidence": Decimal("0.9")})
    ctx.db.commit()
    # Arbitration storage is outside this test; conflict selection and mutations are real SQL.
    monkeypatch.setattr(identity, "_claim_identity_confirmation", lambda *a, **k:
        (SimpleNamespace(customer_id=1), False))
    result = identity.confirm_identity(ctx.db, 1, verified_by=1)
    assert result.identity.status == "disputed"
    assert ctx.access.status == "review_required"
    ctx.db.rollback()
    assert ctx.access.status == "enabled"
    assert ctx.db.get(CustomerExternalIdentity, 1).status == "active"


@pytest.mark.parametrize("field,value", [("normalized_value", "other"), ("status", "disputed"),
                                          ("verification_status", "candidate")])
def test_changed_authority_requires_review(identity_context, field, value):
    ctx = identity_context
    authority.lock_authority(ctx.db)
    setattr(ctx.db.get(CustomerExternalIdentity, 1), field, value)
    authority.review_customer_bindings(ctx.db, {1})
    ctx.db.commit()
    assert ctx.access.status == "review_required"


def test_binding_review_refuses_late_lock(identity_context):
    with pytest.raises(RuntimeError, match="did not acquire"):
        authority.review_customer_bindings(identity_context.db, {1})


def test_agent_identity_write_locks_before_token_resolution(monkeypatch):
    from app.sales_automation import dependencies
    calls = []
    monkeypatch.setattr(authority, "lock_authority", lambda db: calls.append("barrier"))
    def resolve(db, token, *, commit_usage):
        assert commit_usage is False
        return calls.append("token") or {"sub": "1", "permissions": ["sales_automation:invoke"]}
    monkeypatch.setattr(dependencies, "resolve_token", resolve)
    assert dependencies.require_sales_agent_for_identity_write(SimpleNamespace(credentials="test"), object())["sub"] == "1"
    assert calls == ["barrier", "token"]


def test_identity_storage_customer_change_rechecks_logical_owner(identity_context, portal_metadata):
    from app.customer.models import CustomerAssignment
    ctx = identity_context
    customers = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(customers.insert(), {"id": 2, "record_status": "active", "identity_status": "verified", "profile_input_seq": 0})
    assignments = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(assignments.insert(), {"id": 2, "customer_id": 2, "user_id": 1,
        "assignment_role": "primary", "assignment_status": "active", "effective_from": beijing_now()})
    overlay = portal_metadata.tables["ark_customer_object_ownerships"]
    ctx.db.execute(overlay.insert(), {"object_type": "external_identity", "object_id": 1,
        "storage_customer_id": 1, "current_customer_id": 2, "ownership_version": 1})
    ctx.access.customer_id = 2
    ctx.access.assignment_id = 2
    ctx.access.binding_fingerprint = access_policy.binding_fingerprint(2,
        ctx.db.get(CustomerExternalIdentity, 1), ctx.db.get(CustomerAssignment, 2))
    ctx.db.commit()
    real_validate_binding(ctx.db, ctx.access)
    ctx.db.commit()
    authority.lock_authority(ctx.db)
    ctx.db.get(CustomerExternalIdentity, 1).status = "disputed"
    authority.review_customer_bindings(ctx.db, {1})
    ctx.db.commit()
    assert ctx.access.customer_id == 2 and ctx.access.status == "review_required"
