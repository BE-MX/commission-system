"""Knowledge use cases. HTTP and MCP adapters must both call this module."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.knowledge import access
from app.knowledge.content import ContentValidationError, extract_text, validate_content
from app.knowledge.models import (
    KnowledgeApprovalRequest,
    KnowledgeAuditLog,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
    bj_now,
)


class KnowledgeError(Exception):
    status_code = 400


class ValidationError(KnowledgeError):
    status_code = 422


class ForbiddenError(KnowledgeError):
    status_code = 403


class NotFoundError(KnowledgeError):
    status_code = 404


class ConflictError(KnowledgeError):
    status_code = 409


def _require_platform(identity: dict, permission: str) -> None:
    if not access.has_platform(identity, permission):
        raise ForbiddenError(f"missing permission: {permission}")


def _library(db, identity: dict, library_id: int, capability: str = "read") -> KnowledgeLibrary:
    row = db.query(KnowledgeLibrary).filter(
        KnowledgeLibrary.id == library_id,
        KnowledgeLibrary.deleted_at.is_(None),
        KnowledgeLibrary.status == "active",
    ).first()
    if not row or not access.can(db, identity, library_id, capability):
        raise NotFoundError("knowledge library not found")
    return row


def _document(db, identity: dict, document_id: int, capability: str = "read") -> KnowledgeDocument:
    row = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.deleted_at.is_(None),
    ).first()
    if not row:
        raise NotFoundError("knowledge document not found")
    _library(db, identity, row.library_id, capability)
    return row


def _audit(db, identity: dict, library_id: int, action: str, object_type: str, object_id=None, revision_id=None, detail=None) -> None:
    db.add(KnowledgeAuditLog(
        library_id=library_id,
        actor_user_id=access.user_id(identity),
        action=action,
        object_type=object_type,
        object_id=object_id,
        revision_id=revision_id,
        detail=detail,
    ))


def _clean_title(title: str) -> str:
    value = title.strip()
    if not value:
        raise ValidationError("title is required")
    return value


def create_library(db, identity: dict, *, name: str, description: str | None = None) -> KnowledgeLibrary:
    _require_platform(identity, "knowledge:admin")
    clean_name = name.strip()
    if not clean_name:
        raise ValidationError("library name is required")
    row = KnowledgeLibrary(name=clean_name, description=description, created_by=access.user_id(identity))
    db.add(row)
    db.flush()
    db.add(KnowledgeLibraryMember(
        library_id=row.id, user_id=access.user_id(identity), role="admin", created_by=access.user_id(identity)
    ))
    _audit(db, identity, row.id, "create_library", "library", row.id)
    db.commit()
    db.refresh(row)
    return row


def list_libraries(db, identity: dict) -> list[dict]:
    _require_platform(identity, "knowledge:read")
    query = db.query(KnowledgeLibrary).filter(
        KnowledgeLibrary.deleted_at.is_(None), KnowledgeLibrary.status == "active"
    )
    if access.is_super_admin(identity):
        rows = [(library, "admin") for library in query.order_by(KnowledgeLibrary.name).all()]
    else:
        rows = query.join(KnowledgeLibraryMember).filter(
            KnowledgeLibraryMember.user_id == access.user_id(identity)
        ).with_entities(KnowledgeLibrary, KnowledgeLibraryMember.role).order_by(KnowledgeLibrary.name).all()
    return [{"id": library.id, "name": library.name, "description": library.description, "role": role} for library, role in rows]


def get_library(db, identity: dict, library_id: int) -> dict:
    _require_platform(identity, "knowledge:read")
    row = _library(db, identity, library_id)
    return {"id": row.id, "name": row.name, "description": row.description, "role": access.member_role(db, identity, row.id)}


def replace_members(db, identity: dict, library_id: int, members: list[dict]) -> list[dict]:
    _require_platform(identity, "knowledge:admin")
    _library(db, identity, library_id, "admin")
    normalized: dict[int, str] = {}
    for item in members:
        role = item["role"]
        if role not in access.ROLES:
            raise ValidationError("invalid knowledge role")
        normalized[int(item["user_id"])] = role
    actor_id = access.user_id(identity)
    if not access.is_super_admin(identity):
        normalized[actor_id] = "admin"
    db.query(KnowledgeLibraryMember).filter(KnowledgeLibraryMember.library_id == library_id).delete(synchronize_session=False)
    for member_user_id, role in normalized.items():
        db.add(KnowledgeLibraryMember(
            library_id=library_id, user_id=member_user_id, role=role, created_by=actor_id
        ))
    _audit(db, identity, library_id, "replace_members", "library", library_id, detail={"member_count": len(normalized)})
    db.commit()
    return [{"user_id": uid, "role": role} for uid, role in sorted(normalized.items())]


def list_members(db, identity: dict, library_id: int) -> list[dict]:
    _require_platform(identity, "knowledge:admin")
    _library(db, identity, library_id, "admin")
    rows = db.query(KnowledgeLibraryMember).filter(
        KnowledgeLibraryMember.library_id == library_id
    ).order_by(KnowledgeLibraryMember.user_id).all()
    return [{"user_id": row.user_id, "role": row.role} for row in rows]


def _create_revision(db, identity: dict, document: KnowledgeDocument, title: str, content: dict) -> KnowledgeRevision:
    try:
        validate_content(content)
    except ContentValidationError as exc:
        raise ValidationError(str(exc)) from exc
    last_version = db.query(KnowledgeRevision.version_no).filter(
        KnowledgeRevision.document_id == document.id
    ).order_by(KnowledgeRevision.version_no.desc()).first()
    version_no = (last_version[0] if last_version else 0) + 1
    revision = KnowledgeRevision(
        document_id=document.id,
        version_no=version_no,
        title=_clean_title(title),
        content_json=content,
        content_text=extract_text(content),
        created_by=access.user_id(identity),
    )
    db.add(revision)
    db.flush()
    document.title = revision.title
    document.draft_revision_id = revision.id
    return revision


def create_document(db, identity: dict, library_id: int, *, title: str, content: dict, parent_id: int | None = None) -> KnowledgeDocument:
    _require_platform(identity, "knowledge:write")
    _library(db, identity, library_id, "write")
    if parent_id:
        parent = _document(db, identity, parent_id, "write")
        if parent.library_id != library_id or parent.node_type != "folder":
            raise ValidationError("parent must be a folder in the same library")
    document = KnowledgeDocument(
        library_id=library_id, parent_id=parent_id, node_type="document", title=_clean_title(title), created_by=access.user_id(identity)
    )
    db.add(document)
    db.flush()
    revision = _create_revision(db, identity, document, title, content)
    _audit(db, identity, library_id, "create_document", "document", document.id, revision.id)
    db.commit()
    db.refresh(document)
    return document


def create_folder(db, identity: dict, library_id: int, *, title: str, parent_id: int | None = None) -> KnowledgeDocument:
    _require_platform(identity, "knowledge:write")
    _library(db, identity, library_id, "write")
    if parent_id:
        parent = _document(db, identity, parent_id, "write")
        if parent.library_id != library_id or parent.node_type != "folder":
            raise ValidationError("parent must be a folder in the same library")
    folder = KnowledgeDocument(
        library_id=library_id, parent_id=parent_id, node_type="folder", title=_clean_title(title), created_by=access.user_id(identity)
    )
    db.add(folder)
    db.flush()
    _audit(db, identity, library_id, "create_folder", "document", folder.id)
    db.commit()
    db.refresh(folder)
    return folder


def save_document(db, identity: dict, document_id: int, *, title: str, content: dict) -> KnowledgeRevision:
    _require_platform(identity, "knowledge:write")
    document = _document(db, identity, document_id, "write")
    if document.node_type != "document":
        raise ValidationError("folders have no content")
    revision = _create_revision(db, identity, document, title, content)
    _audit(db, identity, document.library_id, "save_revision", "document", document.id, revision.id)
    db.commit()
    db.refresh(revision)
    return revision


def submit_document(db, identity: dict, document_id: int) -> KnowledgeApprovalRequest:
    _require_platform(identity, "knowledge:write")
    document = _document(db, identity, document_id, "write")
    if not document.draft_revision_id:
        raise ConflictError("document has no draft")
    if document.pending_approval_id:
        raise ConflictError("document already has a pending approval")
    approval = KnowledgeApprovalRequest(
        document_id=document.id,
        revision_id=document.draft_revision_id,
        submitted_by=access.user_id(identity),
    )
    try:
        db.add(approval)
        db.flush()
        document.pending_approval_id = approval.id
        document.status = "pending"
        _audit(db, identity, document.library_id, "submit", "approval", approval.id, approval.revision_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("document already has a pending approval") from exc
    db.refresh(approval)
    return approval


def _approval(db, identity: dict, approval_id: int) -> tuple[KnowledgeApprovalRequest, KnowledgeDocument]:
    approval = db.query(KnowledgeApprovalRequest).filter(KnowledgeApprovalRequest.id == approval_id).first()
    if not approval:
        raise NotFoundError("approval not found")
    document = _document(db, identity, approval.document_id, "review")
    return approval, document


def approve_request(db, identity: dict, approval_id: int, *, remark: str | None = None) -> KnowledgeApprovalRequest:
    _require_platform(identity, "knowledge:review")
    approval, document = _approval(db, identity, approval_id)
    if approval.status != "pending" or document.pending_approval_id != approval.id:
        raise ConflictError("approval is not pending")
    approval.status = "approved"
    approval.pending_slot = None
    approval.reviewed_by = access.user_id(identity)
    approval.remark = remark
    approval.reviewed_at = bj_now()
    document.published_revision_id = approval.revision_id
    document.pending_approval_id = None
    document.status = "published"
    _audit(db, identity, document.library_id, "approve", "approval", approval.id, approval.revision_id)
    db.commit()
    db.refresh(approval)
    return approval


def reject_request(db, identity: dict, approval_id: int, *, remark: str) -> KnowledgeApprovalRequest:
    _require_platform(identity, "knowledge:review")
    if not remark.strip():
        raise ValidationError("rejection reason is required")
    approval, document = _approval(db, identity, approval_id)
    if approval.status != "pending" or document.pending_approval_id != approval.id:
        raise ConflictError("approval is not pending")
    approval.status = "rejected"
    approval.pending_slot = None
    approval.reviewed_by = access.user_id(identity)
    approval.remark = remark.strip()
    approval.reviewed_at = bj_now()
    document.pending_approval_id = None
    document.status = "draft" if not document.published_revision_id else "published"
    _audit(db, identity, document.library_id, "reject", "approval", approval.id, approval.revision_id)
    db.commit()
    db.refresh(approval)
    return approval


def get_published_document(db, identity: dict, document_id: int, *, audit_action: str | None = None) -> dict:
    _require_platform(identity, "knowledge:read")
    document = _document(db, identity, document_id, "read")
    if not document.published_revision_id:
        raise NotFoundError("published document not found")
    revision = db.query(KnowledgeRevision).filter(KnowledgeRevision.id == document.published_revision_id).first()
    if not revision:
        raise NotFoundError("published document not found")
    if audit_action:
        _audit(db, identity, document.library_id, audit_action, "document", document.id, revision.id)
        db.commit()
    return {
        "document_id": document.id,
        "library_id": document.library_id,
        "title": revision.title,
        "content_json": revision.content_json,
        "content_text": revision.content_text,
        "version_no": revision.version_no,
    }


def get_document(db, identity: dict, document_id: int) -> dict:
    _require_platform(identity, "knowledge:read")
    document = _document(db, identity, document_id, "read")
    role = access.member_role(db, identity, document.library_id)
    can_edit = role in access.CAPABILITIES["write"] and access.has_platform(identity, "knowledge:write")
    revision_id = document.draft_revision_id if can_edit else document.published_revision_id
    if document.node_type == "document" and not revision_id:
        raise NotFoundError("document not found")
    revision = db.query(KnowledgeRevision).filter(KnowledgeRevision.id == revision_id).first() if revision_id else None
    return {
        "id": document.id,
        "library_id": document.library_id,
        "parent_id": document.parent_id,
        "node_type": document.node_type,
        "title": revision.title if revision else document.title,
        "status": document.status,
        "content_json": revision.content_json if revision else None,
        "version_no": revision.version_no if revision else None,
        "can_edit": can_edit,
        "pending_approval_id": document.pending_approval_id,
    }


def get_tree(db, identity: dict, library_id: int) -> list[dict]:
    _require_platform(identity, "knowledge:read")
    _library(db, identity, library_id)
    rows = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.library_id == library_id, KnowledgeDocument.deleted_at.is_(None)
    ).order_by(KnowledgeDocument.sort_order, KnowledgeDocument.id).all()
    role = access.member_role(db, identity, library_id)
    can_edit = role in access.CAPABILITIES["write"] and access.has_platform(identity, "knowledge:write")
    if can_edit:
        visible_ids = {row.id for row in rows}
    else:
        by_id = {row.id: row for row in rows}
        visible_ids = {row.id for row in rows if row.node_type == "document" and row.published_revision_id}
        for row_id in tuple(visible_ids):
            parent_id = by_id[row_id].parent_id
            while parent_id and parent_id in by_id:
                visible_ids.add(parent_id)
                parent_id = by_id[parent_id].parent_id
    return [
        {"id": row.id, "parent_id": row.parent_id, "node_type": row.node_type, "title": row.title, "status": row.status}
        for row in rows if row.id in visible_ids
    ]


def list_approvals(db, identity: dict) -> list[dict]:
    _require_platform(identity, "knowledge:review")
    query = db.query(KnowledgeApprovalRequest, KnowledgeDocument).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeApprovalRequest.document_id
    ).filter(KnowledgeApprovalRequest.status == "pending")
    rows = query.order_by(KnowledgeApprovalRequest.created_at).all()
    return [
        {"id": approval.id, "document_id": document.id, "library_id": document.library_id, "title": document.title, "revision_id": approval.revision_id, "submitted_by": approval.submitted_by}
        for approval, document in rows if access.can(db, identity, document.library_id, "review")
    ]


def get_approval_detail(db, identity: dict, approval_id: int) -> dict:
    _require_platform(identity, "knowledge:review")
    approval, document = _approval(db, identity, approval_id)
    revision = db.query(KnowledgeRevision).filter(
        KnowledgeRevision.id == approval.revision_id
    ).first()
    if not revision:
        raise NotFoundError("approval revision not found")
    return {
        "id": approval.id,
        "document_id": document.id,
        "library_id": document.library_id,
        "title": revision.title,
        "content_json": revision.content_json,
        "content_text": revision.content_text,
        "version_no": revision.version_no,
        "submitted_by": approval.submitted_by,
        "status": approval.status,
    }


def search_published(db, identity: dict, query: str, *, limit: int = 20, audit_action: str | None = None) -> list[dict]:
    _require_platform(identity, "knowledge:read")
    clean_query = query.strip()
    if not clean_query:
        return []
    limit = max(1, min(int(limit), 20))
    rows_query = db.query(KnowledgeDocument, KnowledgeRevision).join(
        KnowledgeRevision, KnowledgeRevision.id == KnowledgeDocument.published_revision_id
    ).filter(
        KnowledgeDocument.deleted_at.is_(None),
        or_(KnowledgeRevision.title.contains(clean_query), KnowledgeRevision.content_text.contains(clean_query)),
    )
    if not access.is_super_admin(identity):
        rows_query = rows_query.join(
            KnowledgeLibraryMember,
            KnowledgeLibraryMember.library_id == KnowledgeDocument.library_id,
        ).filter(KnowledgeLibraryMember.user_id == access.user_id(identity))
    rows = rows_query.order_by(KnowledgeDocument.id).limit(limit).all()
    results = [
        {
            "document_id": document.id,
            "library_id": document.library_id,
            "title": revision.title,
            "summary": revision.content_text[:240],
            "version_no": revision.version_no,
        }
        for document, revision in rows
    ]
    if audit_action:
        for item in results:
            _audit(db, identity, item["library_id"], audit_action, "document", item["document_id"], detail={"query": clean_query})
        db.commit()
    return results
