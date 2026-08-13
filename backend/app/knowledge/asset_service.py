"""Private image assets and immutable revision references."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import get_settings
from app.knowledge import access, image_service, service
from app.knowledge.content import extract_asset_ids
from app.knowledge.models import (
    KnowledgeApprovalRequest, KnowledgeAsset, KnowledgeDocument, KnowledgeLibrary,
    KnowledgeRevision, KnowledgeRevisionAsset, bj_now,
)


def attach_revision_assets(db, identity: dict, document: KnowledgeDocument,
                           revision: KnowledgeRevision, content: dict) -> None:
    asset_ids = extract_asset_ids(content)
    if not asset_ids:
        return
    rows = db.query(KnowledgeAsset).filter(
        KnowledgeAsset.id.in_(asset_ids),
        KnowledgeAsset.library_id == document.library_id,
        KnowledgeAsset.deleted_at.is_(None),
    ).with_for_update().all()
    rows_by_id = {row.id: row for row in rows}
    if set(asset_ids) != set(rows_by_id):
        raise service.ValidationError("knowledge image is missing or belongs to another library")
    actor_id = access.user_id(identity)
    for position, asset_id in enumerate(asset_ids):
        row = rows_by_id[asset_id]
        if row.status == "temporary" and row.created_by != actor_id and not access.is_super_admin(identity):
            raise service.ValidationError("temporary knowledge image belongs to another user")
        row.status = "attached"
        row.expires_at = None
        db.add(KnowledgeRevisionAsset(revision_id=revision.id, asset_id=asset_id, position=position))


def create_image_asset(db, identity: dict, library_id: int, *, original_name: str,
                       mime_type: str, content: bytes) -> KnowledgeAsset:
    service._require_platform(identity, "knowledge:write")
    service._library(db, identity, library_id, "write")
    stored = image_service.store_upload(library_id, content, mime_type)
    try:
        service._library(db, identity, library_id, "write", for_update=True)
        row = KnowledgeAsset(
            library_id=library_id, storage_path=stored.storage_path,
            original_name=(original_name or "image")[:255], mime_type=stored.mime_type,
            file_size=stored.file_size, width=stored.width, height=stored.height,
            sha256=stored.sha256, status="temporary", created_by=access.user_id(identity),
            expires_at=bj_now() + timedelta(hours=get_settings().KNOWLEDGE_IMAGE_DRAFT_TTL_HOURS),
        )
        db.add(row)
        db.flush()
        service._audit(db, identity, library_id, "upload_image", "asset", row.id, detail={
            "mime_type": row.mime_type, "file_size": row.file_size,
            "width": row.width, "height": row.height,
        })
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        image_service.remove_quietly(stored.storage_path)
        raise


def _asset_is_visible(db, identity: dict, asset: KnowledgeAsset) -> bool:
    if asset.status == "temporary":
        return asset.created_by == access.user_id(identity) or access.is_super_admin(identity)
    role = access.member_role(db, identity, asset.library_id)
    if role in access.CAPABILITIES["write"] and access.has_platform(identity, "knowledge:write"):
        return True
    revision_ids = db.query(KnowledgeRevisionAsset.revision_id).filter(
        KnowledgeRevisionAsset.asset_id == asset.id
    )
    if role in access.CAPABILITIES["review"] and access.has_platform(identity, "knowledge:review"):
        if db.query(KnowledgeApprovalRequest.id).filter(
            KnowledgeApprovalRequest.revision_id.in_(revision_ids),
            KnowledgeApprovalRequest.status == "pending",
        ).first():
            return True
    return db.query(KnowledgeDocument.id).filter(
        KnowledgeDocument.library_id == asset.library_id,
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeDocument.published_revision_id.in_(revision_ids),
    ).first() is not None


def get_image_asset(db, identity: dict, asset_id: int) -> KnowledgeAsset:
    service._require_platform(identity, "knowledge:read")
    row = db.query(KnowledgeAsset).filter(
        KnowledgeAsset.id == asset_id, KnowledgeAsset.deleted_at.is_(None)
    ).first()
    if not row:
        raise service.NotFoundError("knowledge image not found")
    service._library(db, identity, row.library_id, "read")
    if not _asset_is_visible(db, identity, row):
        raise service.NotFoundError("knowledge image not found")
    return row


def delete_temporary_image(db, identity: dict, asset_id: int) -> dict:
    service._require_platform(identity, "knowledge:write")
    row = db.query(KnowledgeAsset).filter(
        KnowledgeAsset.id == asset_id, KnowledgeAsset.deleted_at.is_(None)
    ).first()
    if not row:
        raise service.NotFoundError("knowledge image not found")
    service._library(db, identity, row.library_id, "write", for_update=True)
    row = db.query(KnowledgeAsset).populate_existing().filter(
        KnowledgeAsset.id == asset_id, KnowledgeAsset.deleted_at.is_(None)
    ).with_for_update().first()
    if not row:
        raise service.NotFoundError("knowledge image not found")
    referenced = db.query(KnowledgeRevisionAsset.id).filter(
        KnowledgeRevisionAsset.asset_id == row.id
    ).first()
    if row.status != "temporary" or referenced:
        raise service.ConflictError("attached knowledge image cannot be deleted directly")
    if row.created_by != access.user_id(identity) and not access.is_super_admin(identity):
        raise service.NotFoundError("knowledge image not found")
    row.deleted_at = bj_now()
    service._audit(db, identity, row.library_id, "delete_image", "asset", row.id)
    db.commit()
    image_service.remove_quietly(row.storage_path)
    return {"id": row.id}


def cleanup_expired_images(db) -> int:
    now = bj_now()
    candidates = db.query(KnowledgeAsset).filter(
        KnowledgeAsset.storage_path != "",
        (
            (KnowledgeAsset.status == "temporary")
            & (KnowledgeAsset.expires_at <= now)
        ) | KnowledgeAsset.deleted_at.is_not(None),
    ).all()
    removable: list[KnowledgeAsset] = []
    for candidate in candidates:
        if candidate.deleted_at is not None:
            removable.append(candidate)
            continue
        db.query(KnowledgeLibrary.id).filter(
            KnowledgeLibrary.id == candidate.library_id
        ).with_for_update().first()
        row = db.query(KnowledgeAsset).populate_existing().filter(
            KnowledgeAsset.id == candidate.id, KnowledgeAsset.status == "temporary",
            KnowledgeAsset.expires_at <= now, KnowledgeAsset.deleted_at.is_(None),
        ).with_for_update().first()
        if row and not db.query(KnowledgeRevisionAsset.id).filter(
            KnowledgeRevisionAsset.asset_id == row.id
        ).first():
            row.deleted_at = now
            removable.append(row)
    db.commit()
    for row in removable:
        storage_path = row.storage_path
        if image_service.remove_quietly(storage_path):
            db.query(KnowledgeAsset).filter(
                KnowledgeAsset.id == row.id,
                KnowledgeAsset.storage_path == storage_path,
            ).update({KnowledgeAsset.storage_path: "", KnowledgeAsset.file_size: 0})
    db.commit()
    return len(removable)


def retire_library_assets(db, library_id: int) -> list[str]:
    """Soft-delete all assets while the caller holds the library lock."""
    rows = db.query(KnowledgeAsset).filter(
        KnowledgeAsset.library_id == library_id,
        KnowledgeAsset.deleted_at.is_(None),
    ).with_for_update().all()
    now = bj_now()
    for row in rows:
        row.deleted_at = now
    return [row.storage_path for row in rows]
