"""Customer Hub scope is decided before customer rows are loaded."""

from datetime import datetime

import pytest

from app.auth.models import ArkUser
from app.customer.access_service import CustomerAccessDenied, apply_customer_scope, require_customer_access
from app.customer.models import CustomerAccount, CustomerAgentRunScope, CustomerAssignment, CustomerEvent


NOW = datetime(2026, 8, 30, 9, 0)


def _user(db, user_id: int, *, department_id: int | None = None) -> ArkUser:
    row = ArkUser(
        id=user_id,
        username=f"hub-{user_id}",
        password_hash="test",
        real_name=f"Hub {user_id}",
        is_active=True,
        okki_department_id=department_id,
    )
    db.add(row)
    db.flush()
    return row


def _customer(db, code: str) -> CustomerAccount:
    row = CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name=f"{code} LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="qualified",
        relationship_stage_changed_at=NOW,
        relationship_stage_reason="test",
        record_status="active",
        identity_confidence=1,
        profile_completeness=80,
        profile_input_seq=0,
    )
    db.add(row)
    db.flush()
    return row


def _assign(db, customer_id: int, user_id: int, role: str = "primary") -> None:
    db.add(CustomerAssignment(
        customer_id=customer_id,
        user_id=user_id,
        assignment_role=role,
        assignment_status="active",
        assignment_source="manual",
        effective_from=NOW,
    ))
    db.flush()


def _payload(user_id: int, *permissions: str, roles=()) -> dict:
    return {
        "sub": str(user_id),
        "permissions": list(permissions),
        "roles": list(roles),
    }


def test_owner_and_collaborator_get_full_customer_team_scope(db):
    owner = _user(db, 1)
    collaborator = _user(db, 2)
    customer = _customer(db, "C-TEAM")
    _assign(db, customer.id, owner.id)
    _assign(db, customer.id, collaborator.id, "collaborator")

    for user_id in (owner.id, collaborator.id):
        access = require_customer_access(
            db,
            customer_id=customer.id,
            user=_payload(user_id, "customer:read"),
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
            allow_public_pool=True,
        )
        assert access.scope_kind == "customer_team"
        assert access.max_data_classification == "restricted_internal"
        assert access.max_visibility_scope == "customer_team"


def test_public_pool_read_is_summary_only_and_requires_no_active_primary(db):
    reader = _user(db, 1)
    public_customer = _customer(db, "C-PUBLIC")
    owned_customer = _customer(db, "C-OWNED")
    owner = _user(db, 2)
    _assign(db, owned_customer.id, owner.id)

    access = require_customer_access(
        db,
        customer_id=public_customer.id,
        user=_payload(reader.id, "customer:read"),
        action_permissions={"customer:read"},
        manage_permissions={"customer:admin"},
        allow_public_pool=True,
    )
    assert access.scope_kind == "public_pool"
    assert access.max_data_classification == "internal_business"
    assert access.max_visibility_scope == "all_authorized"

    with pytest.raises(CustomerAccessDenied, match="CUSTOMER_NOT_FOUND_OR_FORBIDDEN"):
        require_customer_access(
            db,
            customer_id=owned_customer.id,
            user=_payload(reader.id, "customer:read"),
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
            allow_public_pool=True,
        )


def test_customer_admin_expands_only_to_current_assignment_department(db):
    admin = _user(db, 1, department_id=10)
    same_department_owner = _user(db, 2, department_id=10)
    other_owner = _user(db, 3, department_id=20)
    same = _customer(db, "C-SAME-DEPT")
    other = _customer(db, "C-OTHER-DEPT")
    _assign(db, same.id, same_department_owner.id)
    _assign(db, other.id, other_owner.id)

    access = require_customer_access(
        db,
        customer_id=same.id,
        user=_payload(admin.id, "customer:read", "customer:admin"),
        action_permissions={"customer:read"},
        manage_permissions={"customer:admin"},
        allow_public_pool=True,
    )
    assert access.scope_kind == "department"
    assert access.can_manage is True

    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db,
            customer_id=other.id,
            user=_payload(admin.id, "customer:read", "customer:admin"),
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
            allow_public_pool=True,
        )


def test_customer_admin_without_department_is_not_global_data_permission(db):
    admin = _user(db, 1)
    owner = _user(db, 2, department_id=10)
    customer = _customer(db, "C-NOT-GLOBAL")
    _assign(db, customer.id, owner.id)

    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db,
            customer_id=customer.id,
            user=_payload(admin.id, "customer:read", "customer:admin"),
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
            allow_public_pool=True,
        )


@pytest.mark.parametrize(
    "payload",
    [
        _payload(1, "customer:read", "customer:read_all"),
        _payload(1, roles=("super_admin",)),
    ],
)
def test_read_all_and_super_admin_are_global(payload, db):
    _user(db, 1)
    owner = _user(db, 2)
    customer = _customer(db, "C-GLOBAL")
    _assign(db, customer.id, owner.id)

    access = require_customer_access(
        db,
        customer_id=customer.id,
        user=payload,
        action_permissions={"customer:read"},
        manage_permissions={"customer:admin"},
        allow_public_pool=True,
    )
    assert access.scope_kind == "global"
    assert access.max_data_classification == "restricted_internal"
    assert access.max_visibility_scope == "management"


def test_run_scope_intersects_live_and_frozen_permissions_and_membership(db):
    owner = _user(db, 1)
    customer = _customer(db, "C-RUN")
    _assign(db, customer.id, owner.id)
    db.add(CustomerAgentRunScope(
        run_id=90,
        customer_id=customer.id,
        scope_type="single",
        scope_snapshot_hash="a" * 64,
        membership_fingerprint="b" * 64,
    ))
    db.flush()

    payload = _payload(owner.id, "customer:read")
    payload["_agent_run"] = {
        "run_id": 90,
        "customer_id": customer.id,
        "permissions_at_start": ["customer:read"],
        "max_data_classification": "personal_contact",
        "max_visibility_scope": "all_authorized",
    }
    access = require_customer_access(
        db,
        customer_id=customer.id,
        user=payload,
        action_permissions={"customer:read"},
        manage_permissions={"customer:admin"},
    )
    assert access.max_data_classification == "personal_contact"
    assert access.max_visibility_scope == "all_authorized"

    payload["_agent_run"]["permissions_at_start"] = []
    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db,
            customer_id=customer.id,
            user=payload,
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
        )


def _event(db, customer_id: int, event_id: int, classification: str, visibility: str):
    row = CustomerEvent(
        id=event_id,
        customer_id=customer_id,
        event_type="annotation.changed",
        event_source="manual",
        event_title=f"{classification}-{visibility}",
        event_summary="test",
        event_payload={},
        importance="normal",
        data_classification=classification,
        visibility_scope=visibility,
        classification_reason="test",
        evidence_fact_ids=[],
        occurred_at=NOW,
        event_fingerprint=f"{event_id:064x}",
    )
    db.add(row)
    db.flush()
    return row


def test_timeline_enforces_all_four_data_classes_for_team_department_global_and_public(db):
    from app.customer.query_service import list_timeline

    owner = _user(db, 1, department_id=10)
    department_admin = _user(db, 2, department_id=10)
    global_admin = _user(db, 3)
    public_reader = _user(db, 4)
    owned = _customer(db, "C-CLASS-OWNED")
    public = _customer(db, "C-CLASS-PUBLIC")
    _assign(db, owned.id, owner.id)
    variants = (
        ("public_business", "all_authorized"),
        ("internal_business", "all_authorized"),
        ("personal_contact", "customer_team"),
        ("restricted_internal", "customer_team"),
        ("restricted_internal", "management"),
    )
    for offset, (classification, visibility) in enumerate(variants, start=1):
        _event(db, owned.id, offset, classification, visibility)
        _event(db, public.id, offset + 10, classification, visibility)

    owner_rows, _ = list_timeline(
        db, _payload(owner.id, "customer:read"), owned.id, page=1, page_size=20,
    )
    assert {row["title"] for row in owner_rows} == {
        "public_business-all_authorized", "internal_business-all_authorized",
        "personal_contact-customer_team", "restricted_internal-customer_team",
    }
    department_rows, _ = list_timeline(
        db, _payload(department_admin.id, "customer:read", "customer:admin"),
        owned.id, page=1, page_size=20,
    )
    assert {row["title"] for row in department_rows} == {row["title"] for row in owner_rows}
    global_rows, _ = list_timeline(
        db, _payload(global_admin.id, "customer:read", "customer:read_all"),
        owned.id, page=1, page_size=20,
    )
    assert len(global_rows) == 5
    public_rows, _ = list_timeline(
        db, _payload(public_reader.id, "customer:read"), public.id, page=1, page_size=20,
    )
    assert {row["title"] for row in public_rows} == {
        "public_business-all_authorized", "internal_business-all_authorized",
    }


def test_customer_detail_never_loads_annotations_from_another_customer(db):
    from app.customer.models import CustomerAnnotation
    from app.customer.query_service import get_customer

    owner = _user(db, 21)
    first = _customer(db, "C-NOTE-FIRST")
    second = _customer(db, "C-NOTE-SECOND")
    _assign(db, first.id, owner.id)
    _assign(db, second.id, owner.id)
    db.add_all([
        CustomerAnnotation(
            customer_id=first.id, annotation_type="note",
            content_schema_version="v1", content_json={"text": "first-only"},
            visibility="customer_team", data_classification="internal_business",
            status="active", authored_by=owner.id,
        ),
        CustomerAnnotation(
            customer_id=second.id, annotation_type="note",
            content_schema_version="v1", content_json={"text": "second-secret"},
            visibility="customer_team", data_classification="internal_business",
            status="active", authored_by=owner.id,
        ),
    ])
    db.flush()

    detail = get_customer(db, _payload(owner.id, "customer:read"), first.id)
    assert [item["content"]["text"] for item in detail["annotations"]] == ["first-only"]


def test_read_all_permission_is_sufficient_for_detail_access(db):
    from app.customer.query_service import get_customer

    reader = _user(db, 31)
    owner = _user(db, 32)
    customer = _customer(db, "C-READ-ALL-ONLY")
    _assign(db, customer.id, owner.id)

    detail = get_customer(db, _payload(reader.id, "customer:read_all"), customer.id)
    assert detail["access_scope"] == "global"


def test_scoped_list_rejects_missing_or_frozen_away_read_permission(db):
    reader = _user(db, 41)
    customer = _customer(db, "C-SCOPE-READ")
    _assign(db, customer.id, reader.id)

    with pytest.raises(CustomerAccessDenied):
        apply_customer_scope(
            db.query(CustomerAccount), user=_payload(reader.id, "customer_radar:read"),
            read_permissions={"customer:read", "customer:read_all"},
        ).all()

    frozen = _payload(reader.id, "customer:read")
    frozen["_agent_run"] = {
        "run_id": 901,
        "permissions_at_start": [],
    }
    with pytest.raises(CustomerAccessDenied):
        apply_customer_scope(
            db.query(CustomerAccount), user=frozen,
            read_permissions={"customer:read", "customer:read_all"},
        ).all()


def test_run_frozen_empty_permissions_fail_closed_even_for_super_admin(db):
    actor = _user(db, 51)
    customer = _customer(db, "C-SUPER-FROZEN")
    _assign(db, customer.id, actor.id)
    db.add(CustomerAgentRunScope(
        run_id=902, customer_id=customer.id, scope_type="single",
        scope_snapshot_hash="c" * 64, membership_fingerprint="d" * 64,
    ))
    db.flush()
    payload = _payload(actor.id, "customer:read", roles=("super_admin",))
    payload["_agent_run"] = {
        "run_id": 902,
        "customer_id": customer.id,
        "permissions_at_start": [],
    }

    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db, customer_id=customer.id, user=payload,
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
        )
    with pytest.raises(CustomerAccessDenied):
        apply_customer_scope(
            db.query(CustomerAccount), user=payload,
            read_permissions={"customer:read", "customer:read_all"},
        ).all()


def test_run_without_frozen_field_never_uses_super_admin_role_as_permission(db):
    actor = _user(db, 61)
    owner = _user(db, 62)
    customer = _customer(db, "C-PRODUCTION-RUN-SHAPE")
    _assign(db, customer.id, owner.id)
    db.add(CustomerAgentRunScope(
        run_id=903, customer_id=customer.id, scope_type="single",
        scope_snapshot_hash="e" * 64, membership_fingerprint="f" * 64,
    ))
    db.flush()
    run_user = _payload(
        actor.id, "agent_runtime:invoke", roles=("super_admin",),
    )
    run_user["_agent_run"] = {
        "run_id": 903,
        "customer_id": customer.id,
        "max_data_classification": "restricted_internal",
        "max_visibility_scope": "management",
    }

    with pytest.raises(CustomerAccessDenied):
        require_customer_access(
            db, customer_id=customer.id, user=run_user,
            action_permissions={"customer:read"},
            manage_permissions={"customer:admin"},
        )
    with pytest.raises(CustomerAccessDenied):
        apply_customer_scope(
            db.query(CustomerAccount), user=run_user,
            read_permissions={"customer:read", "customer:read_all"},
        ).all()

    normal_super = _payload(
        actor.id, "agent_runtime:invoke", roles=("super_admin",),
    )
    detail_access = require_customer_access(
        db, customer_id=customer.id, user=normal_super,
        action_permissions={"customer:read"},
        manage_permissions={"customer:admin"},
    )
    assert detail_access.scope_kind == "global"
    assert apply_customer_scope(
        db.query(CustomerAccount), user=normal_super,
        read_permissions={"customer:read", "customer:read_all"},
    ).count() == 1
