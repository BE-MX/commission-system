"""Single real-time customer scope and governed data projection boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.customer.models import (
    CustomerAccount,
    CustomerAgentRunScope,
    CustomerAssignment,
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
) -> CustomerAccess:
    """Intersect action permission, live customer scope, visibility and Run scope."""
    try:
        actor_user_id = int(user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN") from exc
    permissions = set(user.get("permissions") or [])
    roles = set(user.get("roles") or [])
    is_super_admin = "super_admin" in roles
    action_codes = set(action_permissions)
    manage_codes = set(manage_permissions)
    can_manage = is_super_admin or bool(permissions & manage_codes)
    if not (is_super_admin or permissions & action_codes):
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    account_exists = db.query(CustomerAccount.id).filter(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    ).first()
    if account_exists is None:
        raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    run_scope = user.get("_agent_run") or None
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

    if not can_manage:
        assigned = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == customer_id,
            CustomerAssignment.user_id == actor_user_id,
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ).first()
        if assigned is None:
            raise CustomerAccessDenied("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")

    classification = (
        "restricted_internal" if can_manage else "internal_business"
    )
    visibility = "management" if can_manage else "customer_team"
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
    )


def apply_record_access(
    query: Query,
    model,
    access: CustomerAccess,
    *,
    visibility_field: str = "visibility_scope",
    classification_field: str = "data_classification",
    author_field: str | None = None,
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
    return query.filter(
        model.customer_id == access.customer_id,
        visibility_predicate,
        classification.in_(access.allowed_classifications()),
    )


__all__ = [
    "CustomerAccess",
    "CustomerAccessDenied",
    "apply_record_access",
    "require_customer_access",
]
