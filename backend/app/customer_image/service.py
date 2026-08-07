"""Internal services for customer-scoped portal access."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot


OKKI_BINDING_REQUIRED_MESSAGE = "请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号"


class CustomerScopeConflictError(Exception):
    status_code = 409


def validate_public_requirement(requirement: str, settings) -> str:
    value = requirement.strip()
    limit = settings.CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS
    if len(value) > limit:
        raise ValueError(f"需求说明不能超过 {limit} 字")
    return value


def _okki_account_id(db: Session, ark_user_id: int) -> str:
    external_ids = db.scalars(
        select(ArkUserExternalBinding.external_account_id).where(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        ).order_by(
            ArkUserExternalBinding.is_primary.desc(),
            ArkUserExternalBinding.id,
        )
    ).all()
    for external_id in external_ids:
        normalized = external_id.strip() if external_id else ""
        if normalized.isdigit():
            return normalized
    raise CustomerScopeConflictError(OKKI_BINDING_REQUIRED_MESSAGE)


def list_available_customers(
    db: Session,
    ark_user_id: int,
    is_admin: bool,
    search: str,
) -> list[dict]:
    statement = select(
        CustomerInfo.company_id,
        CustomerInfo.company_name,
        CustomerInfo.country_name,
        CustomerInfo.origin_name,
    )
    if not is_admin:
        okki_user_id = _okki_account_id(db, ark_user_id)
        statement = statement.join(
            CustomerCommissionSnapshot,
            CustomerCommissionSnapshot.customer_id == CustomerInfo.company_id,
        ).where(
            CustomerCommissionSnapshot.is_current.is_(True),
            CustomerCommissionSnapshot.salesperson_id == okki_user_id,
        ).distinct()

    term = search.strip()
    if term:
        pattern = f"%{term}%"
        statement = statement.where(or_(
            CustomerInfo.company_id.ilike(pattern),
            CustomerInfo.company_name.ilike(pattern),
        ))
    statement = statement.order_by(CustomerInfo.company_name, CustomerInfo.company_id)

    return [
        {
            "id": row.company_id,
            "name": row.company_name,
            "country": row.country_name,
            "origin": row.origin_name,
        }
        for row in db.execute(statement).all()
    ]
