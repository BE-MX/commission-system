"""Single real-time customer scope and governed data projection boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Query, Session

from app.auth.models import ArkUser
from app.customer.models import (
    CustomerAccount,
    CustomerAgentRunScope,
    CustomerAssignment,
)
from app.customer.logical_customer_service import (
    logical_root_predicate,
    resolve_canonical_customer_id,
)


CLASSIFICATION_ORDER = (
    "public_business",
    "internal_business",
    "personal_contact",
    "restricted_internal",
)
VISIBILITY_ORDER = ("all_authorized", "customer_team", "management")


class CustomerAccessDenied(ValueError):
    """Stable non-disclosing access failure."""


@dataclass(frozen=True, slots=True)
class CustomerAccess:
    customer_id: int
    actor_user_id: int
    can_manage: bool
    max_data_classification: str
    max_visibility_scope: str
    run_id: int | None
    scope_kind: str = "customer_team"

    def allowed_classifications(self) -> tuple[str, ...]:
        limit = CLASSIFICATION_ORDER.index(self.max_data_classification)
        return CLASSIFICATION_ORDER[: limit + 1]

    def allows_classification(self, classification: str) -> bool:
        return classification in self.allowed_classifications()

    def allowed_visibility_scopes(self) -> tuple[str, ...]:
        limit = VISIBILITY_ORDER.index(self.max_visibility_scope)
        return VISIBILITY_ORDER[: limit + 1]

    def allows_visibility(self, visibility: str) -> bool:
        return visibility in self.allowed_visibility_scopes()


def _bounded_value(value: str | None, order: tuple[str, ...], default: str) -> str:
    return value if value in order else default


def _minimum(left: str, right: str, order: tuple[str, ...]) -> str:
    return order[min(order.index(left), order.index(right))]


def require_customer_access(
    db: Session,
    *,
    customer_id: int,
    user: dict,
    action_permissions: Iterable[str],
    manage_permissions: Iterable[str],
    allow_public_pool: bool = False,
) -> CustomerAccess:
    """Intersect action permission, live customer scope, visibility and Run scope."""
    canonical_customer_id = resolve_canonical_customer_id(db, customer_id)
    if canonical_customer_id is None:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    customer_id = canonical_customer_id
    try:
        actor_user_id = int(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN") from exc
    permissions = set(user.get("permissions") or [])
    roles = set(user.get("roles") or [])
    is_super_admin = "super_admin" in roles
    run_scope = user.get("_agent_run") or None
    has_frozen_permissions = (
        run_scope is not None and "permissions_at_start" in run_scope
    )
    if has_frozen_permissions:
        permissions &= set(run_scope.get("permissions_at_start") or [])
    role_bypass = is_super_admin and run_scope is None
    action_codes = set(action_permissions)
    manage_codes = set(manage_permissions)
    can_manage = role_bypass or bool(permissions & manage_codes)
    if not (role_bypass or permissions & action_codes):
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    account_query = db.query(CustomerAccount.id).filter(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    )
    run_id = None
    if run_scope is not None:
        if str(run_scope.get("customer_id") or "") != str(customer_id):
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
        try:
            run_id = int(run_scope["run_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN") from exc
        membership = db.query(CustomerAgentRunScope.id).filter(
            CustomerAgentRunScope.run_id == run_id,
            CustomerAgentRunScope.customer_id == customer_id,
        ).first()
        if membership is None:
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    is_global = role_bypass or "customer:read_all" in permissions
    assigned = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == customer_id,
            CustomerAssignment.user_id == actor_user_id,
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
    ).first()
    scope_kind: str | None = None
    if is_global:
        scope_kind = "global"
    elif assigned is not None:
        scope_kind = "customer_team"
    elif can_manage:
        actor = db.query(ArkUser.okki_department_id).filter(
            ArkUser.id == actor_user_id,
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        ).one_or_none()
        department_id = actor.okki_department_id if actor else None
        if department_id is not None:
            same_department = db.query(CustomerAssignment.id).join(
                ArkUser,
                ArkUser.id == CustomerAssignment.user_id,
            ).filter(
                CustomerAssignment.customer_id == customer_id,
                CustomerAssignment.assignment_status == "active",
                CustomerAssignment.effective_to.is_(None),
                ArkUser.okki_department_id == department_id,
                ArkUser.is_active.is_(True),
                ArkUser.deleted_at.is_(None),
            ).first()
            if same_department is not None:
                scope_kind = "department"
    if scope_kind is None and allow_public_pool:
        active_primary = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == customer_id,
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ).first()
        if active_primary is None:
            scope_kind = "public_pool"
    if scope_kind is None or account_query.first() is None:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    if scope_kind == "global":
        classification = "restricted_internal"
        visibility = "management"
    elif scope_kind in {"customer_team", "department"}:
        classification = "restricted_internal"
        visibility = "customer_team"
    else:
        classification = "internal_business"
        visibility = "all_authorized"
    if run_scope is not None:
        run_classification = _bounded_value(
            run_scope.get("max_data_classification"),
            CLASSIFICATION_ORDER,
            "internal_business",
        )
        run_visibility = _bounded_value(
            run_scope.get("max_visibility_scope"),
            VISIBILITY_ORDER,
            "customer_team",
        )
        classification = _minimum(
            classification,
            run_classification,
            CLASSIFICATION_ORDER,
        )
        visibility = _minimum(visibility, run_visibility, VISIBILITY_ORDER)
    return CustomerAccess(
        customer_id=customer_id,
        actor_user_id=actor_user_id,
        can_manage=can_manage,
        max_data_classification=classification,
        max_visibility_scope=visibility,
        run_id=run_id,
        scope_kind=scope_kind,
    )


def apply_customer_scope(
    query: Query,
    *,
    user: dict,
    read_permissions: Iterable[str],
    include_public_pool: bool = True,
) -> Query:
    """Apply the human customer's live scope in SQL before loading rows."""
    try:
        actor_user_id = int(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN") from exc
    permissions = set(user.get("permissions") or [])
    roles = set(user.get("roles") or [])
    run_scope = user.get("_agent_run") or None
    run_predicate = None
    has_frozen_permissions = (
        run_scope is not None and "permissions_at_start" in run_scope
    )
    if has_frozen_permissions:
        permissions &= set(run_scope.get("permissions_at_start") or [])
    role_bypass = "super_admin" in roles and run_scope is None
    if not (role_bypass or permissions & set(read_permissions)):
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    if run_scope is not None:
        try:
            run_id = int(run_scope["run_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN") from exc
        run_predicate = exists().where(and_(
            CustomerAgentRunScope.run_id == run_id,
            CustomerAgentRunScope.customer_id == CustomerAccount.id,
        ))
    if role_bypass or "customer:read_all" in permissions:
        scoped = query.filter(CustomerAccount.record_status == "active")
        return scoped.filter(run_predicate) if run_predicate is not None else scoped

    live_assignment = exists().where(and_(
        CustomerAssignment.customer_id == CustomerAccount.id,
        CustomerAssignment.user_id == actor_user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ))
    predicates = [live_assignment]
    if "customer:admin" in permissions:
        department_id = query.session.query(ArkUser.okki_department_id).filter(
            ArkUser.id == actor_user_id,
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        ).scalar()
        if department_id is not None:
            department_assignment = exists().where(and_(
                CustomerAssignment.customer_id == CustomerAccount.id,
                CustomerAssignment.assignment_status == "active",
                CustomerAssignment.effective_to.is_(None),
                CustomerAssignment.user_id.in_(
                    query.session.query(ArkUser.id).filter(
                        ArkUser.okki_department_id == department_id,
                        ArkUser.is_active.is_(True),
                        ArkUser.deleted_at.is_(None),
                    )
                ),
            ))
            predicates.append(department_assignment)
    if include_public_pool:
        active_primary = exists().where(and_(
            CustomerAssignment.customer_id == CustomerAccount.id,
            CustomerAssignment.assignment_role == "primary",
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ))
        predicates.append(~active_primary)
    scoped = query.filter(
        CustomerAccount.record_status == "active",
        or_(*predicates),
    )
    return scoped.filter(run_predicate) if run_predicate is not None else scoped


def apply_record_access(
    query: Query,
    model,
    access: CustomerAccess,
    *,
    visibility_field: str = "visibility_scope",
    classification_field: str = "data_classification",
    author_field: str | None = None,
    logical_object_type: str | None = None,
) -> Query:
    """Apply SQL-side visibility/classification limits to a customer record query."""
    visibility = getattr(model, visibility_field)
    classification = getattr(model, classification_field)
    visibility_predicate = visibility.in_(access.allowed_visibility_scopes())
    if author_field is not None:
        visibility_predicate = or_(
            visibility_predicate,
            (
                (visibility == "private")
                & (getattr(model, author_field) == access.actor_user_id)
            ),
        )
    customer_predicate = (
        logical_root_predicate(model, logical_object_type, access.customer_id)
        if logical_object_type is not None
        else model.customer_id == access.customer_id
    )
    return query.filter(
        customer_predicate,
        visibility_predicate,
        classification.in_(access.allowed_classifications()),
    )


__all__ = [
    "CustomerAccess",
    "CustomerAccessDenied",
    "apply_record_access",
    "apply_customer_scope",
    "require_customer_access",
]
