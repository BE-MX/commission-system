"""Set-based current customer scope without rewriting historical attribution."""
from sqlalchemy import select, or_, func, literal
from sqlalchemy.orm import aliased
from app.customer.access_service import apply_customer_scope
from app.customer.models import CustomerAccount, CustomerOrder, CustomerObjectOwnership
from app.invoice.models import Invoice


def customer_scope_predicate(db, user, customer_id_column, *, read_permissions=("invoice:read", "invoice:write")):
    prefixes = {permission.split(":", 1)[0] for permission in read_permissions}
    if "super_admin" in user.get("roles", []) or any(f"{domain}:read_all" in user.get("permissions", []) for domain in prefixes):
        return literal(True)
    visible = apply_customer_scope(db.query(CustomerAccount.id), user=user,
        read_permissions=read_permissions, include_public_pool=False)
    # Start with visible ACTIVE roots and walk backwards through immutable
    # merged aliases. Alias cycles have no active root and cannot enter this CTE.
    roots = select(CustomerAccount.id.label("id")).where(CustomerAccount.id.in_(visible.statement)).cte(recursive=True)
    alias = aliased(CustomerAccount)
    roots = roots.union_all(select(alias.id).join(roots, alias.merged_into_customer_id == roots.c.id)
                            .where(alias.record_status == "merged"))
    return customer_id_column.in_(select(roots.c.id))


def local_invoice_scope(db, user, *, read_permissions=("invoice:read", "invoice:write")):
    """SQL predicate for main/native lists AND detail checks, before count/page.

Current reviewed logical order ownership takes precedence; attribution fields
on Invoice remain untouched. More than one logical projection is not guessed.
"""
    ownership = select(CustomerObjectOwnership.current_customer_id).join(CustomerOrder,
        (CustomerObjectOwnership.object_type == "order") & (CustomerObjectOwnership.object_id == CustomerOrder.id))
    ownership = ownership.where(CustomerOrder.local_invoice_id == Invoice.id).correlate(Invoice).scalar_subquery()
    stored = select(CustomerOrder.customer_id).where(CustomerOrder.local_invoice_id == Invoice.id).correlate(Invoice).scalar_subquery()
    count = select(func.count()).select_from(CustomerOrder).where(CustomerOrder.local_invoice_id == Invoice.id).correlate(Invoice).scalar_subquery()
    effective = func.coalesce(ownership, stored, Invoice.local_customer_id)
    current_scope = customer_scope_predicate(db, user, effective, read_permissions=read_permissions)
    return or_(Invoice.transaction_mode != "local", (count <= 1) & current_scope)
