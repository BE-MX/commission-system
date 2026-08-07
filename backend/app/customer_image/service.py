"""Internal services for customer-scoped portal access."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkUserExternalBinding
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot
from app.customer_image.models import (
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageInviteProduct,
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
)
from app.customer_image.schemas import (
    CustomerImageInviteCreate,
    CustomerImageProductOptionUpsert,
    CustomerImageProductUpsert,
)
from app.customer_image.token_service import issue_invite_token


OKKI_BINDING_REQUIRED_MESSAGE = "请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号"


class CustomerScopeConflictError(Exception):
    status_code = 409


class CustomerImageNotFoundError(Exception):
    """Raised when a resource is absent or outside the caller's scope."""


class CustomerImageConflictError(Exception):
    """Raised when a referenced resource cannot be changed or deleted."""


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


def _product_load_options(include_inactive: bool):
    relationship = CustomerImageProductOption.values
    if not include_inactive:
        relationship = relationship.and_(CustomerImageOptionValue.is_active.is_(True))
    return selectinload(CustomerImageProduct.options).selectinload(relationship)


def list_products(
    db: Session, *, include_inactive: bool
) -> list[CustomerImageProduct]:
    return list(db.scalars(
        select(CustomerImageProduct)
        .options(_product_load_options(include_inactive))
        .execution_options(populate_existing=True)
        .order_by(
            CustomerImageProduct.sort,
            CustomerImageProduct.id,
        )
    ).all())


def get_product(
    db: Session, product_id: int, *, include_inactive: bool = False
) -> CustomerImageProduct:
    product = db.scalar(
        select(CustomerImageProduct)
        .where(CustomerImageProduct.id == product_id)
        .options(_product_load_options(include_inactive))
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise CustomerImageNotFoundError("product not found")
    return product


def list_current_product_assets(
    db: Session, product_id: int
) -> list[CustomerImageProductAsset]:
    get_product(db, product_id)
    return list(db.scalars(
        select(CustomerImageProductAsset)
        .where(
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.retired_at.is_(None),
        )
        .order_by(
            CustomerImageProductAsset.role,
            CustomerImageProductAsset.position,
            CustomerImageProductAsset.id,
        )
    ).all())


def get_current_product_asset(
    db: Session, product_id: int, asset_id: int
) -> CustomerImageProductAsset:
    asset = db.scalar(
        select(CustomerImageProductAsset).where(
            CustomerImageProductAsset.id == asset_id,
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.retired_at.is_(None),
        )
    )
    if asset is None:
        raise CustomerImageNotFoundError("product asset not found")
    return asset


def delete_product(db: Session, product_id: int) -> None:
    product = db.get(CustomerImageProduct, product_id)
    if product is None:
        raise CustomerImageNotFoundError("product not found")
    referenced = db.scalar(
        select(CustomerImageInviteProduct.id).where(
            CustomerImageInviteProduct.product_id == product_id
        ).limit(1)
    ) or db.scalar(
        select(CustomerImageGeneration.id).where(
            CustomerImageGeneration.product_id == product_id
        ).limit(1)
    )
    if referenced is not None:
        raise CustomerImageConflictError("product is in use and cannot be deleted")
    asset_paths = list(db.scalars(
        select(CustomerImageProductAsset.storage_path).where(
            CustomerImageProductAsset.product_id == product_id
        )
    ).all())
    try:
        db.delete(product)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CustomerImageConflictError("product is in use and cannot be deleted") from None
    except Exception:
        db.rollback()
        raise

    from app.customer_image import file_service
    from app.design_image.service import _thumbnail_path

    for relative_path in asset_paths:
        file_service._delete_stored_files(
            relative_path,
            _thumbnail_path(relative_path),
            "deleted product asset",
        )


def replace_product_options(
    db: Session,
    product_id: int,
    options: list[CustomerImageProductOptionUpsert],
    *,
    increment_version: bool = True,
) -> list[CustomerImageProductOption]:
    product = _product_or_error(db, product_id)
    try:
        option_ids = list(db.scalars(
            select(CustomerImageProductOption.id).where(
                CustomerImageProductOption.product_id == product_id
            )
        ).all())
        if option_ids:
            db.query(CustomerImageOptionValue).filter(
                CustomerImageOptionValue.option_id.in_(option_ids)
            ).delete(synchronize_session="fetch")
            db.query(CustomerImageProductOption).filter(
                CustomerImageProductOption.product_id == product_id
            ).delete(synchronize_session="fetch")
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


def unpublish_product(db: Session, product_id: int) -> CustomerImageProduct:
    product = get_product(db, product_id)
    if product.is_published:
        product.is_published = False
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
    limit: int = 20,
) -> list[dict]:
    term = search.strip()
    if not term:
        return []
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

    pattern = f"%{term}%"
    statement = statement.where(or_(
        CustomerInfo.company_id.ilike(pattern),
        CustomerInfo.company_name.ilike(pattern),
    ))
    statement = statement.order_by(
        CustomerInfo.company_name, CustomerInfo.company_id
    ).limit(min(max(limit, 1), 20))

    return [
        {
            "id": row.company_id,
            "name": row.company_name,
            "country": row.country_name,
            "origin": row.origin_name,
        }
        for row in db.execute(statement).all()
    ]


def _customer_for_invite(
    db: Session,
    customer_id: str,
    ark_user_id: int,
    is_admin: bool,
) -> tuple[str, str]:
    statement = select(CustomerInfo.company_name).where(
        CustomerInfo.company_id == customer_id
    )
    if not is_admin:
        salesperson_id = _okki_account_id(db, ark_user_id)
        statement = statement.join(
            CustomerCommissionSnapshot,
            CustomerCommissionSnapshot.customer_id == CustomerInfo.company_id,
        ).where(
            CustomerCommissionSnapshot.is_current.is_(True),
            CustomerCommissionSnapshot.salesperson_id == salesperson_id,
        )
    customer_name = db.scalar(statement.distinct())
    if customer_name is None:
        raise CustomerImageNotFoundError("customer not found")
    if is_admin:
        salesperson_id = db.scalar(
            select(CustomerCommissionSnapshot.salesperson_id)
            .where(
                CustomerCommissionSnapshot.customer_id == customer_id,
                CustomerCommissionSnapshot.is_current.is_(True),
            )
            .order_by(CustomerCommissionSnapshot.id.desc())
        )
        if not salesperson_id:
            raise CustomerImageNotFoundError("customer owner not found")
    return customer_name, salesperson_id


def create_invite(
    db: Session,
    *,
    creator_id: int,
    is_admin: bool,
    payload: CustomerImageInviteCreate,
) -> tuple[CustomerImageInvite, str]:
    customer_name, salesperson_id = _customer_for_invite(
        db, payload.customer_id, creator_id, is_admin
    )
    products = list(db.scalars(
        select(CustomerImageProduct).where(
            CustomerImageProduct.id.in_(payload.product_ids),
            CustomerImageProduct.is_published.is_(True),
        )
    ).all())
    if {row.id for row in products} != set(payload.product_ids):
        raise CustomerImageNotFoundError("published product not found")

    invite = CustomerImageInvite(
        customer_id=payload.customer_id,
        customer_name_snapshot=customer_name,
        created_by=creator_id,
        okki_salesperson_id_snapshot=salesperson_id,
        token_hash="",
        token_suffix="",
        starts_at=datetime.utcnow(),
        expires_at=payload.expires_at,
        quota_total=payload.quota_total,
    )
    try:
        plaintext, invite = issue_invite_token(db, invite)
        db.add_all(
            CustomerImageInviteProduct(invite_id=invite.id, product_id=product_id)
            for product_id in payload.product_ids
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(invite)
    return invite, plaintext


def list_invites(
    db: Session,
    creator_id: int,
    is_admin: bool,
    page: int,
    page_size: int,
) -> tuple[list[CustomerImageInvite], int]:
    statement = select(CustomerImageInvite)
    if not is_admin:
        statement = statement.where(CustomerImageInvite.created_by == creator_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(db.scalars(
        statement.order_by(CustomerImageInvite.created_at.desc(), CustomerImageInvite.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all())
    return rows, total


def revoke_invite(
    db: Session,
    invite_id: int,
    creator_id: int,
    is_admin: bool,
) -> CustomerImageInvite:
    statement = select(CustomerImageInvite).where(CustomerImageInvite.id == invite_id)
    if not is_admin:
        statement = statement.where(CustomerImageInvite.created_by == creator_id)
    invite = db.scalar(statement)
    if invite is None:
        raise CustomerImageNotFoundError("invite not found")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(invite)
    return invite


def list_generations(
    db: Session,
    creator_id: int,
    is_admin: bool,
    page: int,
    page_size: int,
) -> tuple[list[CustomerImageGeneration], int]:
    statement = select(CustomerImageGeneration).join(
        CustomerImageInvite,
        CustomerImageInvite.id == CustomerImageGeneration.invite_id,
    )
    if not is_admin:
        statement = statement.where(CustomerImageInvite.created_by == creator_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(db.scalars(
        statement.order_by(
            CustomerImageGeneration.created_at.desc(),
            CustomerImageGeneration.id.desc(),
        ).offset((page - 1) * page_size).limit(page_size)
    ).all())
    return rows, total
