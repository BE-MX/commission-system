"""Customer image storage operations built on the shared private-image boundary."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageProduct,
    CustomerImageProductAsset,
)
from app.design_image import file_service as shared_files
from app.design_image.models import DesignImageLibraryAsset
from app.design_image.service import _thumbnail_path


ImageStorageError = shared_files.ImageStorageError
normalize_upload = shared_files.normalize_upload
effective_max_upload_bytes = shared_files.effective_max_upload_bytes
resolve_private_path = shared_files.resolve_private_path
save_private_image = shared_files.save_private_image
delete_private_file = shared_files.delete_private_file
NormalizedImage = shared_files.NormalizedImage
logger = logging.getLogger("commission")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _delete_stored_files(
    relative_path: str, thumbnail_relative_path: str, context: str
) -> None:
    for path in (relative_path, thumbnail_relative_path):
        try:
            delete_private_file(path)
        except Exception as exc:
            message = f"[customer-image] {context} cleanup failed: {exc}"
            logger.warning(message)
            print(message, flush=True)


def _product_for_update_statement(product_id: int):
    return (
        select(CustomerImageProduct)
        .where(CustomerImageProduct.id == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _replace_with_normalized(
    db: Session,
    product: CustomerImageProduct,
    role: str,
    position: int,
    normalized: NormalizedImage,
) -> CustomerImageProductAsset:
    if role not in {"cover", "reference"}:
        raise ValueError("product asset role must be cover or reference")
    if position < 0:
        raise ValueError("product asset position must be nonnegative")
    if role == "cover" and position != 0:
        raise ValueError("product cover position must be zero")
    stored = save_private_image(normalized, owner_user_id=product.id, kind="customer-product")
    try:
        locked_product = db.scalar(_product_for_update_statement(product.id))
        if locked_product is None:
            raise FileNotFoundError("product not found")
        current = db.scalars(
            select(CustomerImageProductAsset).where(
                CustomerImageProductAsset.product_id == product.id,
                CustomerImageProductAsset.role == role,
                CustomerImageProductAsset.position == position,
                CustomerImageProductAsset.retired_at.is_(None),
            )
        ).all()
        retired_at = utcnow()
        for old_asset in current:
            old_asset.retired_at = retired_at
        asset = CustomerImageProductAsset(
            product_id=product.id,
            role=role,
            position=position,
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
        )
        db.add(asset)
        locked_product.config_version += 1
        db.commit()
    except Exception:
        db.rollback()
        _delete_stored_files(
            stored.relative_path, stored.thumbnail_relative_path, "product asset"
        )
        raise
    db.refresh(asset)
    return asset


def replace_product_asset_from_upload(
    db: Session,
    product: CustomerImageProduct,
    role: str,
    position: int,
    content: bytes,
    declared_mime: str,
) -> CustomerImageProductAsset:
    return _replace_with_normalized(
        db, product, role, position, normalize_upload(content, declared_mime)
    )


def replace_product_asset_from_library(
    db: Session,
    product: CustomerImageProduct,
    role: str,
    position: int,
    library_asset_id: int,
    *,
    admin_id: int,
) -> CustomerImageProductAsset:
    normalized = _normalized_library_asset(db, library_asset_id, admin_id=admin_id)
    return _replace_with_normalized(db, product, role, position, normalized)


def _normalized_library_asset(
    db: Session, library_asset_id: int, *, admin_id: int
) -> NormalizedImage:
    source = db.get(DesignImageLibraryAsset, library_asset_id)
    if source is None or source.deleted_at is not None:
        raise FileNotFoundError("library asset not found")
    if source.scope == "private" and source.owner_user_id != admin_id:
        raise FileNotFoundError("library asset not found")
    try:
        content = resolve_private_path(source.storage_path).read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError("library asset not found") from None
    return normalize_upload(content, source.mime_type)


def _append_reference_with_normalized(
    db: Session,
    product: CustomerImageProduct,
    normalized: NormalizedImage,
) -> CustomerImageProductAsset:
    stored = save_private_image(normalized, owner_user_id=product.id, kind="customer-product")
    try:
        locked_product = db.scalar(_product_for_update_statement(product.id))
        if locked_product is None:
            raise FileNotFoundError("product not found")
        last_position = db.scalar(
            _last_reference_position_for_update_statement(product.id)
        )
        asset = CustomerImageProductAsset(
            product_id=product.id,
            role="reference",
            position=(last_position + 1) if last_position is not None else 0,
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
        )
        db.add(asset)
        locked_product.config_version += 1
        db.commit()
    except Exception:
        db.rollback()
        _delete_stored_files(
            stored.relative_path, stored.thumbnail_relative_path, "product reference"
        )
        raise
    db.refresh(asset)
    return asset


def append_product_reference_from_upload(
    db: Session,
    product: CustomerImageProduct,
    content: bytes,
    declared_mime: str,
) -> CustomerImageProductAsset:
    return _append_reference_with_normalized(
        db, product, normalize_upload(content, declared_mime)
    )


def _last_reference_position_for_update_statement(product_id: int):
    return (
        select(CustomerImageProductAsset.position)
        .where(
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.role == "reference",
            CustomerImageProductAsset.retired_at.is_(None),
        )
        .order_by(
            CustomerImageProductAsset.position.desc(),
            CustomerImageProductAsset.id.desc(),
        )
        .limit(1)
        .with_for_update()
    )


def append_product_reference_from_library(
    db: Session,
    product: CustomerImageProduct,
    library_asset_id: int,
    *,
    admin_id: int,
) -> CustomerImageProductAsset:
    return _append_reference_with_normalized(
        db,
        product,
        _normalized_library_asset(db, library_asset_id, admin_id=admin_id),
    )


def _open_relative_content(relative_path: str, not_found_message: str) -> io.BytesIO:
    try:
        return io.BytesIO(resolve_private_path(relative_path).read_bytes())
    except FileNotFoundError:
        raise FileNotFoundError(not_found_message) from None


def open_product_asset_content(
    db: Session,
    product_id: int,
    asset_id: int,
) -> io.BytesIO:
    asset = db.scalar(
        select(CustomerImageProductAsset).where(
            CustomerImageProductAsset.id == asset_id,
            CustomerImageProductAsset.product_id == product_id,
            CustomerImageProductAsset.retired_at.is_(None),
        )
    )
    if asset is None:
        raise FileNotFoundError("product asset not found")
    return _open_relative_content(asset.storage_path, "product asset not found")


def open_generation_reference_content(
    db: Session, invite_id: int, generation_id: int, asset_id: int
) -> io.BytesIO:
    generation = db.scalar(
        select(CustomerImageGeneration).where(
            CustomerImageGeneration.id == generation_id,
            CustomerImageGeneration.invite_id == invite_id,
        )
    )
    if generation is None or asset_id not in generation.reference_asset_ids:
        raise FileNotFoundError("product asset not found") from None
    asset = db.scalar(
        select(CustomerImageProductAsset).where(
            CustomerImageProductAsset.id == asset_id,
            CustomerImageProductAsset.product_id == generation.product_id,
        )
    )
    if asset is None:
        raise FileNotFoundError("product asset not found")
    return _open_relative_content(asset.storage_path, "product asset not found")


def save_invite_image(
    db: Session,
    invite_id: int,
    normalized: NormalizedImage,
    asset_type: str,
) -> CustomerImageAsset:
    if asset_type not in {"logo", "generated"}:
        raise ValueError("invite asset type must be logo or generated")
    if db.get(CustomerImageInvite, invite_id) is None:
        raise FileNotFoundError("invite not found")
    kind = "customer-logo" if asset_type == "logo" else "customer-output"
    stored = save_private_image(normalized, owner_user_id=invite_id, kind=kind)
    try:
        asset = CustomerImageAsset(
            invite_id=invite_id,
            asset_type=asset_type,
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
        )
        db.add(asset)
        db.commit()
    except Exception:
        db.rollback()
        _delete_stored_files(
            stored.relative_path, stored.thumbnail_relative_path, "invite asset"
        )
        raise
    db.refresh(asset)
    return asset


def replace_current_logo(
    db: Session, invite_id: int, normalized: NormalizedImage
) -> CustomerImageAsset:
    stored = save_private_image(normalized, owner_user_id=invite_id, kind="customer-logo")
    try:
        invite = db.scalar(
            select(CustomerImageInvite)
            .where(CustomerImageInvite.id == invite_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if invite is None:
            raise FileNotFoundError("invite not found")
        asset = CustomerImageAsset(
            invite_id=invite_id,
            asset_type="logo",
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
        )
        db.add(asset)
        db.flush()
        invite.current_logo_asset_id = asset.id
        db.commit()
    except Exception:
        db.rollback()
        _delete_stored_files(stored.relative_path, stored.thumbnail_relative_path, "current logo")
        raise
    db.refresh(asset)
    return asset


def open_invite_asset_content(
    db: Session,
    invite_id: int,
    asset_id: int,
    *,
    thumbnail: bool = False,
) -> io.BytesIO:
    asset = db.scalar(
        select(CustomerImageAsset).where(
            CustomerImageAsset.id == asset_id,
            CustomerImageAsset.invite_id == invite_id,
            CustomerImageAsset.deleted_at.is_(None),
        )
    )
    if asset is None:
        raise FileNotFoundError("invite asset not found")
    relative_path = _thumbnail_path(asset.storage_path) if thumbnail else asset.storage_path
    return _open_relative_content(relative_path, "invite asset not found")
