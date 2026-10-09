"""Fresh server-side principals and explicit customer ownership boundaries."""

from dataclasses import dataclass

from sqlalchemy import select

from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.portal.domain import content_hash, require_capability
from app.portal.errors import reject
from app.portal.models import Account, CustomerAccess, Membership, Site


@dataclass(frozen=True)
class CustomerPrincipal:
    account: Account
    membership: Membership
    access: CustomerAccess
    site: Site
    company_display_name: str

    def require(self, action):
        require_capability(action, can_order=self.access.can_order,
                           can_view_price=self.access.can_view_price)


def current(db, model, identifier):
    return db.scalar(select(model).where(model.id == identifier).execution_options(populate_existing=True))


def binding_fingerprint(customer_id, identity, assignment):
    return content_hash({"customer_id": str(customer_id), "identity_id": str(identity.id),
        "source": identity.source_system, "namespace": identity.source_account_key,
        "type": identity.identifier_type, "value": identity.normalized_value,
        "verification": identity.verification_status, "status": identity.status,
        "assignment_id": str(assignment.id), "sales_user_id": str(assignment.user_id)})


def validate_company_identity(db, access):
    customer = current(db, CustomerAccount, access.customer_id)
    if customer is None or customer.record_status != "active" or customer.identity_status == "disputed":
        reject("IDENTITY_REVIEW_REQUIRED", "Your company access needs review.")
    identity = db.scalar(select(CustomerExternalIdentity).where(
        CustomerExternalIdentity.id == access.external_identity_id,
        logical_root_predicate(CustomerExternalIdentity, "external_identity", access.customer_id),
        CustomerExternalIdentity.contact_id.is_(None),
    ).execution_options(populate_existing=True))
    if identity is None or identity.source_system != "okki" or identity.identifier_type != "company_id" or (
        identity.status != "active" or identity.verification_status != "verified"
        or identity.cardinality != "one_to_one" or identity.identity_strength != "strong"
        or identity.source_account_key != access.okki_namespace or identity.normalized_value != access.okki_company_id
    ):
        reject("IDENTITY_REVIEW_REQUIRED", "Your company access needs review.")
    return customer, identity


def validate_assignment(db, access):
    assignment = current(db, CustomerAssignment, access.assignment_id)
    if assignment is None or assignment.customer_id != access.customer_id or assignment.user_id != access.sales_user_id or (
        assignment.assignment_role != "primary" or assignment.assignment_status != "active"
        or assignment.effective_to is not None or assignment.effective_from > beijing_now()
    ):
        reject("ASSIGNMENT_CHANGED", "Your account representative needs to review this request.")
    salesperson = db.scalar(select(ArkUser.id).where(ArkUser.id == access.sales_user_id,
                          ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)))
    if salesperson is None:
        reject("ASSIGNMENT_CHANGED", "Your account representative needs to review this request.")
    return assignment


def validate_binding(db, access):
    customer, identity = validate_company_identity(db, access)
    assignment = validate_assignment(db, access)
    if binding_fingerprint(access.customer_id, identity, assignment) != access.binding_fingerprint:
        reject("IDENTITY_REVIEW_REQUIRED", "Your company access needs review.")
    return customer


def customer_principal(db, account_id, membership_id, *, activating=False):
    account = current(db, Account, account_id)
    member = current(db, Membership, membership_id)
    allowed = {"invited", "active"} if activating else {"active"}
    if account is None or member is None or member.account_id != account.id or account.status not in allowed or member.status not in allowed:
        reject("AUTH_REQUIRED", "Please sign in again.", 401)
    access = current(db, CustomerAccess, member.access_id)
    site = current(db, Site, member.site_id)
    if access is None or site is None or access.site_id != site.id or access.status != "enabled" or site.status != "enabled":
        reject("AUTH_REQUIRED", "Please sign in again.", 401)
    customer = validate_binding(db, access)
    return CustomerPrincipal(account, member, access, site, customer.display_name)


def employee_principal(db, user_id, *permissions):
    # Rebuild roles from DB; no JWT role survives this boundary.
    roles, live_permissions = get_live_user_authorization(db, int(user_id))
    if not roles or "super_admin" not in roles and any(p not in live_permissions for p in permissions):
        reject("ACTION_FORBIDDEN", "You do not have permission to perform this action.", 403)
    return {"id": int(user_id), "roles": roles, "permissions": live_permissions}
