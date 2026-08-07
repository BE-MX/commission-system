"""Internal services for customer-scoped portal access."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUserExternalBinding
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot
from app.customer_image.models import (
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
)
from app.customer_image.schemas import CustomerImageProductOptionUpsert, CustomerImageProductUpsert


OKKI_BINDING_REQUIRED_MESSAGE = "请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号"


class CustomerScopeConflictError(Exception):
    status_code = 409


def _product_or_error(db: Session, product_id: int) -> CustomerImageProduct:
    product = db.get(CustomerImageProduct, product_id)
    if product is None:
        raise ValueError("product not found")
    return product


def _add_options(
    db: Session,
    product_id: int,
    options: list[CustomerImageProductOptionUpsert],
) -> None:
    for option_payload in options:
        values = option_payload.values
        option_data = option_payload.model_dump(exclude={"values"})
        option = CustomerImageProductOption(product_id=product_id, **option_data)
        db.add(option)
        db.flush()
        db.add_all(
            CustomerImageOptionValue(option_id=option.id, **value.model_dump())
            for value in values
        )


def create_product(
    db: Session, *, admin_id: int, payload: CustomerImageProductUpsert
) -> CustomerImageProduct:
    product_data = payload.model_dump(exclude={"options"})
    product = CustomerImageProduct(created_by=admin_id, **product_data)
    try:
        db.add(product)
        db.flush()
        _add_options(db, product.id, payload.options)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(product)
    return product


def replace_product_options(
    db: Session,
    product_id: int,
    options: list[CustomerImageProductOptionUpsert],
    *,
    increment_version: bool = True,
) -> list[CustomerImageProductOption]:
    product = _product_or_error(db, product_id)
    try:
        current = db.scalars(
            select(CustomerImageProductOption).where(
                CustomerImageProductOption.product_id == product_id
            )
        ).all()
        for option in current:
            db.query(CustomerImageOptionValue).filter(
                CustomerImageOptionValue.option_id == option.id
            ).delete(synchronize_session=False)
            db.delete(option)
        db.flush()
        _add_options(db, product_id, options)
        if increment_version:
            product.config_version += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return list_product_options(db, product_id)


def list_product_options(
    db: Session, product_id: int
) -> list[CustomerImageProductOption]:
    options = db.scalars(
        select(CustomerImageProductOption)
        .where(CustomerImageProductOption.product_id == product_id)
        .options(selectinload(
            CustomerImageProductOption.values.and_(
                CustomerImageOptionValue.is_active.is_(True)
            )
        ))
        .order_by(CustomerImageProductOption.sort, CustomerImageProductOption.id)
    ).all()
    return options


def update_product(
    db: Session, product_id: int, payload: CustomerImageProductUpsert
) -> CustomerImageProduct:
    product = _product_or_error(db, product_id)
    for field, value in payload.model_dump(exclude={"options"}).items():
        setattr(product, field, value)
    replace_product_options(db, product_id, payload.options)
    db.refresh(product)
    return product


def publish_product(db: Session, product_id: int) -> CustomerImageProduct:
    product = _product_or_error(db, product_id)
    roles = set(db.scalars(
        select(CustomerImageProductAsset.role).where(
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.retired_at.is_(None),
        )
    ).all())
    if not {"cover", "reference"}.issubset(roles):
        raise ValueError("published products require a cover and reference asset")
    product.is_published = True
    db.commit()
    db.refresh(product)
    return product


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
