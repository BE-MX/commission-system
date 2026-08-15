"""Internal services for customer-scoped portal access."""

from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import String, column, func, or_, select, table, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.service import build_image_config_version
from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkUserExternalBinding
from app.core.config import get_settings
from app.customer_image.datetime_utils import as_utc_naive
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot
from app.customer_image.prompt_service import validate_and_build_prompt
from app.customer_image.models import (
    CustomerImageAsset,
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
    CustomerImageGenerationCreate,
    CustomerImageProductOptionUpsert,
    CustomerImageProductUpsert,
)
from app.customer_image.token_service import issue_invite_token


_customer_contacts = table(
    "customer_contacts",
    column("company_id", String(64)),
    column("name", String(256)),
    schema=CustomerInfo.__table__.schema,
)


OKKI_BINDING_REQUIRED_MESSAGE = "请先在系统管理 -> 外部账号绑定中绑定 OKKI 账号"


class CustomerScopeConflictError(Exception):
    status_code = 409


class CustomerImageNotFoundError(Exception):
    """Raised when a resource is absent or outside the caller's scope."""


class CustomerImageConflictError(Exception):
    """Raised when a referenced resource cannot be changed or deleted."""


class CustomerImageQuotaError(CustomerImageConflictError):
    """Raised when an invitation has no generation quota remaining."""


class CustomerImageLogoRequiredError(CustomerImageConflictError):
    """Raised when generation is submitted before a current logo exists."""


class CustomerImageConfigurationError(Exception):
    """Raised when the frozen image preset cannot be created safely."""


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
    statement = select(CustomerImageProduct)
    if not include_inactive:
        statement = statement.where(CustomerImageProduct.is_published.is_(True))
    return list(db.scalars(
        statement
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
    statement = select(CustomerImageProduct).where(CustomerImageProduct.id == product_id)
    if not include_inactive:
        statement = statement.where(CustomerImageProduct.is_published.is_(True))
    product = db.scalar(
        statement
        .options(_product_load_options(include_inactive))
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise CustomerImageNotFoundError("product not found")
    return product


def list_current_product_assets(
    db: Session, product_id: int
) -> list[CustomerImageProductAsset]:
    get_product(db, product_id, include_inactive=True)
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


def _available_customer_statement(
    db: Session,
    ark_user_id: int,
    is_admin: bool,
):
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
    return statement


def _serialize_customer(row) -> dict:
    return {
        # customer_info.company_id 在不同 OKKI 库实例中可能由驱动返回
        # int 或 str；对外统一成字符串，避免大整数 ID 穿过 JSON/JS 后
        # 发生类型漂移或精度损失。
        "id": str(row.company_id),
        "name": row.company_name,
        "country": row.country_name,
        "origin": row.origin_name,
    }


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

    pattern = f"%{term}%"
    contact_customer_ids = select(_customer_contacts.c.company_id).where(
        _customer_contacts.c.name.ilike(pattern),
    )
    statement = _available_customer_statement(db, ark_user_id, is_admin)
    statement = statement.where(or_(
        CustomerInfo.company_name.ilike(pattern),
        CustomerInfo.company_id.in_(contact_customer_ids),
    ))
    statement = statement.order_by(
        CustomerInfo.company_name, CustomerInfo.company_id
    ).limit(min(max(limit, 1), 20))

    return [_serialize_customer(row) for row in db.execute(statement).all()]


def get_available_customer(
    db: Session,
    ark_user_id: int,
    is_admin: bool,
    customer_id: str,
) -> dict | None:
    statement = _available_customer_statement(db, ark_user_id, is_admin).where(
        CustomerInfo.company_id == customer_id,
    ).limit(1)
    row = db.execute(statement).first()
    return _serialize_customer(row) if row else None


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


def _locked_invite_statement(invite_id: int):
    return (
        select(CustomerImageInvite)
        .where(CustomerImageInvite.id == invite_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _quota_increment_statement(invite_id: int):
    return (
        update(CustomerImageInvite)
        .where(
            CustomerImageInvite.id == invite_id,
            CustomerImageInvite.quota_used < CustomerImageInvite.quota_total,
        )
        .values(quota_used=CustomerImageInvite.quota_used + 1)
    )


def _generation_preset_snapshot(db: Session) -> tuple[str, str, dict, dict | None]:
    settings = get_settings()
    row = db.execute(
        select(AiPreset, AiProvider)
        .join(AiProvider, AiProvider.id == AiPreset.provider_id)
        .where(
            AiPreset.preset_name == settings.CUSTOMER_IMAGE_PRESET_NAME,
            AiPreset.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
            AiProvider.deleted_at.is_(None),
            AiProvider.is_enabled.is_(True),
            AiProvider.provider_type == "direct",
        )
    ).first()
    if row is None or row[0].model != "gpt-image-2":
        raise CustomerImageConfigurationError("customer image preset is unavailable")
    preset, provider = row
    configured = preset.parameters or {}
    if not isinstance(configured, dict):
        raise CustomerImageConfigurationError("customer image preset parameters are invalid")
    rate_card = configured.get("rate_card")
    if rate_card is not None and not isinstance(rate_card, dict):
        raise CustomerImageConfigurationError("customer image rate card is invalid")
    configured_hosts = configured.get("download_hosts", [])
    if not isinstance(configured_hosts, list):
        raise CustomerImageConfigurationError("customer image download hosts are invalid")
    parameters = {
        "size": configured.get("size"),
        "quality": configured.get("quality"),
        "provider_id": provider.id,
        "config_version": {
            "provider_id": provider.id,
            "fingerprint": build_image_config_version(preset, provider),
        },
        "download_hosts": sorted({
            str(host).strip().lower()
            for host in configured_hosts
            if str(host).strip()
        }),
    }
    return preset.preset_name, preset.model, parameters, deepcopy(rate_card)


def _active_invite(invite: CustomerImageInvite, now: datetime) -> bool:
    return (
        invite.revoked_at is None
        and as_utc_naive(invite.starts_at) <= now < as_utc_naive(invite.expires_at)
    )


def _existing_generation(
    db: Session, invite_id: int, request_id: str
) -> CustomerImageGeneration | None:
    return db.scalar(select(CustomerImageGeneration).where(
        CustomerImageGeneration.invite_id == invite_id,
        CustomerImageGeneration.request_id == request_id,
    ))


def create_generation(
    db: Session,
    invite_id: int,
    payload: CustomerImageGenerationCreate,
) -> CustomerImageGeneration:
    now = datetime.utcnow()
    settings = get_settings()
    try:
        invite = db.scalar(_locked_invite_statement(invite_id))
        if invite is None or not _active_invite(invite, now):
            raise CustomerImageNotFoundError("invite not found")
        product = db.scalar(
            select(CustomerImageProduct)
            .join(
                CustomerImageInviteProduct,
                CustomerImageInviteProduct.product_id == CustomerImageProduct.id,
            )
            .where(
                CustomerImageInviteProduct.invite_id == invite.id,
                CustomerImageProduct.id == payload.product_id,
                CustomerImageProduct.is_published.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if product is None:
            raise CustomerImageNotFoundError("published product not found")

        existing = _existing_generation(db, invite.id, payload.request_id)
        if existing is not None:
            db.commit()
            return existing

        logo = db.scalar(select(CustomerImageAsset).where(
            CustomerImageAsset.id == invite.current_logo_asset_id,
            CustomerImageAsset.invite_id == invite.id,
            CustomerImageAsset.asset_type == "logo",
            CustomerImageAsset.deleted_at.is_(None),
        )) if invite.current_logo_asset_id is not None else None
        if logo is None:
            raise CustomerImageLogoRequiredError("current logo is required")

        assembly = validate_and_build_prompt(
            db,
            product_id=product.id,
            expected_config_version=payload.config_version,
            selections=payload.selections,
            requirement=payload.requirement,
            max_requirement_chars=settings.CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS,
        )
        references = list(db.scalars(
            select(CustomerImageProductAsset)
            .where(
                CustomerImageProductAsset.product_id == product.id,
                CustomerImageProductAsset.role == "reference",
                CustomerImageProductAsset.retired_at.is_(None),
            )
            .order_by(
                CustomerImageProductAsset.position,
                CustomerImageProductAsset.id,
            )
        ).all())
        if not references:
            raise CustomerImageConflictError("published product references are unavailable")
        preset_name, model, parameters, pricing_snapshot = _generation_preset_snapshot(db)
        reference_ids = [asset.id for asset in references]
        parameters["input_asset_ids"] = [logo.id, *reference_ids]
        generation = CustomerImageGeneration(
            invite_id=invite.id,
            product_id=product.id,
            logo_asset_id=logo.id,
            request_id=payload.request_id,
            product_name_snapshot=product.name,
            config_version_snapshot=product.config_version,
            option_snapshot=assembly.option_snapshot,
            requirement_snapshot=assembly.requirement or None,
            parameters_snapshot=parameters,
            prompt_snapshot=assembly.prompt,
            reference_asset_ids=reference_ids,
            status="queued",
            preset_name=preset_name,
            model=model,
            pricing_snapshot=pricing_snapshot,
            created_at=now,
        )
        try:
            with db.begin_nested():
                consumed = db.execute(_quota_increment_statement(invite.id))
                if consumed.rowcount != 1:
                    raise CustomerImageQuotaError("generation quota exhausted")
                db.add(generation)
                db.flush()
        except IntegrityError:
            db.expire_all()
            winner = _existing_generation(db, invite.id, payload.request_id)
            if winner is None:
                raise
            db.commit()
            return winner
        db.commit()
        db.refresh(generation)
        return generation
    except Exception:
        db.rollback()
        raise


def list_public_products(db: Session, invite_id: int) -> list[CustomerImageProduct]:
    return list(db.scalars(
        select(CustomerImageProduct)
        .join(CustomerImageInviteProduct, CustomerImageInviteProduct.product_id == CustomerImageProduct.id)
        .where(
            CustomerImageInviteProduct.invite_id == invite_id,
            CustomerImageProduct.is_published.is_(True),
        )
        .options(
            selectinload(CustomerImageProduct.assets.and_(CustomerImageProductAsset.retired_at.is_(None))),
            selectinload(CustomerImageProduct.options).selectinload(
                CustomerImageProductOption.values.and_(CustomerImageOptionValue.is_active.is_(True))
            ),
        )
        .order_by(CustomerImageProduct.sort, CustomerImageProduct.id)
    ).all())


def list_current_product_covers(
    db: Session, product_ids: list[int]
) -> dict[int, CustomerImageProductAsset]:
    if not product_ids:
        return {}
    rows = db.scalars(
        select(CustomerImageProductAsset)
        .where(
            CustomerImageProductAsset.product_id.in_(set(product_ids)),
            CustomerImageProductAsset.role == "cover",
            CustomerImageProductAsset.retired_at.is_(None),
        )
        .order_by(
            CustomerImageProductAsset.product_id,
            CustomerImageProductAsset.position,
            CustomerImageProductAsset.id,
        )
    ).all()
    covers: dict[int, CustomerImageProductAsset] = {}
    for row in rows:
        covers.setdefault(row.product_id, row)
    return covers


def get_current_product_cover(
    db: Session, product_id: int, *, include_inactive: bool = False
) -> CustomerImageProductAsset:
    get_product(db, product_id, include_inactive=include_inactive)
    cover = db.scalar(
        select(CustomerImageProductAsset)
        .where(
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.role == "cover",
            CustomerImageProductAsset.retired_at.is_(None),
        )
        .order_by(CustomerImageProductAsset.position, CustomerImageProductAsset.id)
        .limit(1)
    )
    if cover is None:
        raise CustomerImageNotFoundError("product cover not found")
    return cover


def _lock_product_for_asset_change(db: Session, product_id: int) -> CustomerImageProduct:
    product = db.scalar(
        select(CustomerImageProduct)
        .where(CustomerImageProduct.id == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if product is None:
        raise CustomerImageNotFoundError("product not found")
    return product


def _current_references_for_update(
    db: Session, product_id: int
) -> list[CustomerImageProductAsset]:
    return list(db.scalars(
        select(CustomerImageProductAsset)
        .where(
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.role == "reference",
            CustomerImageProductAsset.retired_at.is_(None),
        )
        .order_by(CustomerImageProductAsset.position, CustomerImageProductAsset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all())


def _set_reference_positions(
    db: Session, references: list[CustomerImageProductAsset]
) -> None:
    # Two phases also remain safe if a production schema adds a unique current-position index.
    offset = max((row.position for row in references), default=0) + len(references) + 1
    for index, row in enumerate(references):
        row.position = offset + index
    db.flush()
    for index, row in enumerate(references):
        row.position = index


def reorder_product_references(
    db: Session, product_id: int, asset_ids: list[int]
) -> list[CustomerImageProductAsset]:
    product = _lock_product_for_asset_change(db, product_id)
    current = _current_references_for_update(db, product_id)
    current_by_id = {row.id: row for row in current}
    if len(asset_ids) != len(current) or set(asset_ids) != set(current_by_id):
        db.rollback()
        raise CustomerImageConflictError("reference order must include every current reference")
    ordered = [current_by_id[asset_id] for asset_id in asset_ids]
    _set_reference_positions(db, ordered)
    product.config_version += 1
    db.commit()
    return _current_references_for_update(db, product_id)


def retire_product_reference(db: Session, product_id: int, asset_id: int) -> None:
    product = _lock_product_for_asset_change(db, product_id)
    current = _current_references_for_update(db, product_id)
    target = next((row for row in current if row.id == asset_id), None)
    if target is None:
        db.rollback()
        raise CustomerImageNotFoundError("product reference not found")
    if product.is_published and len(current) == 1:
        db.rollback()
        raise CustomerImageConflictError("published product requires a reference")
    target.retired_at = datetime.now(UTC).replace(tzinfo=None)
    remaining = [row for row in current if row.id != asset_id]
    _set_reference_positions(db, remaining)
    product.config_version += 1
    db.commit()


def list_public_generations(
    db: Session, invite_id: int
) -> list[CustomerImageGeneration]:
    return list(db.scalars(
        select(CustomerImageGeneration)
        .where(CustomerImageGeneration.invite_id == invite_id)
        .order_by(
            CustomerImageGeneration.created_at.desc(),
            CustomerImageGeneration.id.desc(),
        )
    ).all())


def get_public_generation(
    db: Session, invite_id: int, generation_id: int
) -> CustomerImageGeneration:
    generation = db.scalar(select(CustomerImageGeneration).where(
        CustomerImageGeneration.id == generation_id,
        CustomerImageGeneration.invite_id == invite_id,
    ))
    if generation is None:
        raise CustomerImageNotFoundError("generation not found")
    return generation


def get_public_product_asset(
    db: Session, invite_id: int, product_id: int, asset_id: int
) -> CustomerImageProductAsset:
    asset = db.scalar(
        select(CustomerImageProductAsset)
        .join(CustomerImageProduct, CustomerImageProduct.id == CustomerImageProductAsset.product_id)
        .join(CustomerImageInviteProduct, CustomerImageInviteProduct.product_id == CustomerImageProduct.id)
        .where(
            CustomerImageInviteProduct.invite_id == invite_id,
            CustomerImageProduct.id == product_id,
            CustomerImageProduct.is_published.is_(True),
            CustomerImageProductAsset.id == asset_id,
            CustomerImageProductAsset.retired_at.is_(None),
        )
    )
    if asset is None:
        raise CustomerImageNotFoundError("product asset not found")
    return asset


def get_public_invite_asset(db: Session, invite_id: int, asset_id: int) -> CustomerImageAsset:
    asset = db.scalar(select(CustomerImageAsset).where(
        CustomerImageAsset.id == asset_id,
        CustomerImageAsset.invite_id == invite_id,
        CustomerImageAsset.deleted_at.is_(None),
    ))
    if asset is None:
        raise CustomerImageNotFoundError("invite asset not found")
    return asset
