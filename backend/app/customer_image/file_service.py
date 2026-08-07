"""Customer image storage operations built on the shared private-image boundary."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_image.models import CustomerImageProduct, CustomerImageProductAsset
from app.design_image import file_service as shared_files
from app.design_image.models import DesignImageLibraryAsset


ImageStorageError = shared_files.ImageStorageError
normalize_upload = shared_files.normalize_upload
resolve_private_path = shared_files.resolve_private_path
save_private_image = shared_files.save_private_image
delete_private_file = shared_files.delete_private_file
NormalizedImage = shared_files.NormalizedImage
logger = logging.getLogger("commission")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _delete_stored_files(relative_path: str, thumbnail_relative_path: str) -> None:
    for path in (relative_path, thumbnail_relative_path):
        try:
            delete_private_file(path)
        except Exception as exc:
            message = f"[customer-image] product asset rollback cleanup failed: {exc}"
            logger.warning(message)
            print(message, flush=True)


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
    stored = save_private_image(normalized, owner_user_id=product.id, kind="customer-product")
    try:
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
        product.config_version += 1
        db.commit()
    except Exception:
        db.rollback()
        _delete_stored_files(stored.relative_path, stored.thumbnail_relative_path)
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
    source = db.get(DesignImageLibraryAsset, library_asset_id)
    if source is None or source.deleted_at is not None:
        raise FileNotFoundError("library asset not found")
    if source.scope == "private" and source.owner_user_id != admin_id:
        raise FileNotFoundError("library asset not found")
    try:
        content = resolve_private_path(source.storage_path).read_bytes()
    except (OSError, ImageStorageError):
        raise FileNotFoundError("library asset not found") from None
    normalized = normalize_upload(content, source.mime_type)
    return _replace_with_normalized(db, product, role, position, normalized)


def open_product_asset(
    db: Session,
    product_id: int,
    asset_id: int,
    *,
    allow_retired: bool = False,
) -> io.BytesIO:
    statement = select(CustomerImageProductAsset).where(
            CustomerImageProductAsset.id == asset_id,
            CustomerImageProductAsset.product_id == product_id,
        )
    if not allow_retired:
        statement = statement.where(CustomerImageProductAsset.retired_at.is_(None))
    asset = db.scalar(statement)
    if asset is None:
        raise FileNotFoundError("product asset not found")
    try:
        return io.BytesIO(resolve_private_path(asset.storage_path).read_bytes())
    except (OSError, ImageStorageError):
        raise FileNotFoundError("product asset not found") from None
