"""Current identity/ownership choices and immutable review evidence for handoff."""
from sqlalchemy import select

from app.auth.models import ArkUser
from app.customer.models import CustomerAccount, CustomerAssignment
from app.core.time import beijing_now
from app.portal import admin_service as admin
from app.portal.domain import content_hash
from app.portal.errors import reject
from app.portal.models import OrderRequest
from app.portal.onboarding_service import identities

PENDING = {'submitted', 'awaiting_customer', 'ready_for_review'}


def snapshot(db, access):
    customer = admin.current(db, CustomerAccount, access.customer_id)
    assignments = db.execute(select(CustomerAssignment, ArkUser.real_name).join(ArkUser,
        ArkUser.id == CustomerAssignment.user_id).where(CustomerAssignment.customer_id == access.customer_id,
        CustomerAssignment.assignment_role == 'primary', CustomerAssignment.assignment_status == 'active',
        CustomerAssignment.effective_to.is_(None), CustomerAssignment.effective_from <= beijing_now(),
        ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).order_by(CustomerAssignment.id)
        .execution_options(populate_existing=True)).all()
    assignment_choices = [{'id': str(row.id), 'sales_user_id': str(row.user_id), 'sales_name': name}
                          for row, name in assignments]
    identity_rows = identities(db, [access.customer_id])[access.customer_id]
    identity_choices = sorted([{'id': str(row.id), 'company_id': row.normalized_value,
        'namespace': row.source_account_key} for row in identity_rows], key=lambda row: row['id'])
    orders = db.scalars(select(OrderRequest).where(OrderRequest.access_id == access.id)
        .order_by(OrderRequest.id).execution_options(populate_existing=True)).all()
    evidence = [{'id': row.public_id, 'version': row.row_version, 'status': row.status,
        'invoice_id': str(row.invoice_id) if row.invoice_id is not None else None,
        'servicing_user_id': str(row.servicing_user_id)} for row in orders]
    pending = [row for row in orders if row.status in PENDING and row.invoice_id is None]
    fingerprint = content_hash({'access_id': access.public_id, 'row_version': access.row_version,
        'customer_status': customer.record_status if customer else None,
        'identity_status': customer.identity_status if customer else None,
        'assignments': assignment_choices, 'identities': identity_choices, 'orders': evidence})
    return {'access_id': access.public_id, 'row_version': access.row_version,
        'company_display_name': customer.display_name if customer else '',
        'status': access.status, 'current_assignment_id': str(access.assignment_id),
        'current_sales_user_id': str(access.sales_user_id), 'current_identity_id': str(access.external_identity_id),
        'current_company_id': access.okki_company_id, 'assignments': assignment_choices,
        'identities': identity_choices, 'review_fingerprint': fingerprint,
        'pending_requests': [{'id': row.public_id, 'public_no': row.public_no, 'status': row.status,
            'row_version': row.row_version, 'servicing_user_id': str(row.servicing_user_id)} for row in pending[:1000]],
        'pending_total': len(pending), 'pending_truncated': len(pending) > 1000,
        'order_total': len(orders), 'invoice_order_total': sum(row.invoice_id is not None for row in orders),
        'requires_assignment_review': not any(str(row.id) == str(access.assignment_id) for row, _ in assignments),
        'customer_requires_review': customer is None or customer.record_status != 'active' or customer.identity_status == 'disputed'}


def context(db, actor_id, public_id):
    actor = admin.begin(db, actor_id)
    return snapshot(db, admin.scoped_access(db, public_id, actor))


def require_review(db, access, fingerprint):
    reviewed = snapshot(db, access)
    if reviewed['review_fingerprint'] != fingerprint:
        reject('REVIEW_CHANGED', '客户归属、身份或订单影响范围已变化，请重新读取并确认。')
    return reviewed
