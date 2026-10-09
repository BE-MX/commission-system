"""Explicitly approved outward profiles, scoped to the current assigned employee."""
from sqlalchemy import select

from app.auth.models import ArkUser
from app.portal.schemas import SitePolicy
from app.portal.errors import reject


def validate_contacts(db, contacts):
    ids = [int(contact.user_id) for contact in contacts if contact.approved]
    if not ids:
        return
    active = set(db.scalars(select(ArkUser.id).where(ArkUser.id.in_(ids),
        ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None))).all())
    if active != set(ids):
        reject('CONTACT_EMPLOYEE_UNAVAILABLE', '只能批准当前启用员工的对外联系方式。', 422)


def employee_options(db):
    # Site administrators choose a stable employee; private account channels stay private.
    rows = db.execute(select(ArkUser.id, ArkUser.real_name).where(ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None)).order_by(ArkUser.real_name, ArkUser.id)).all()
    return [{'id': str(row.id), 'name': row.real_name or str(row.id)} for row in rows]


def contact_view(principal):
    # Only call after customer_principal has checked current binding and active owner.
    policy = SitePolicy.model_validate(principal.site.policy_json)
    contact = next((row for row in policy.sales_contacts
                    if row.user_id == str(principal.access.sales_user_id) and row.approved), None)
    if contact is None:
        return None
    return {'display_name': contact.display_name, 'email': contact.email, 'whatsapp': contact.whatsapp}
