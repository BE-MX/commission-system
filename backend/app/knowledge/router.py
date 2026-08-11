"""Authorized HTTP endpoints for the native knowledge base."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.knowledge import service
from app.knowledge.schemas import DocumentCreate, DocumentSave, LibraryCreate, MembersReplace, ReviewInput


router = APIRouter()
READ = ("knowledge:read", "knowledge:write", "knowledge:review", "knowledge:admin")
WRITE = ("knowledge:write", "knowledge:admin")
REVIEW = ("knowledge:review", "knowledge:admin")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.InvalidMembersError as exc:
        raise HTTPException(exc.status_code, {
            "message": str(exc),
            "invalid_user_ids": exc.invalid_user_ids,
        }) from exc
    except service.KnowledgeError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


def _library(row):
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "status": row.status,
    }


def _document(row):
    return {"id": row.id, "library_id": row.library_id, "parent_id": row.parent_id, "node_type": row.node_type, "title": row.title, "status": row.status}


def _approval(row):
    return {"id": row.id, "document_id": row.document_id, "revision_id": row.revision_id, "status": row.status, "remark": row.remark}


@router.get("/libraries")
def list_libraries(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.list_libraries, db, user))


@router.post("/libraries")
def create_library(payload: LibraryCreate, db: Session = Depends(get_db), user: dict = Depends(require_permission("knowledge:admin"))):
    return ok(_library(_call(
        service.create_library,
        db,
        user,
        name=payload.name,
        category=payload.category,
        description=payload.description,
    )))


@router.get("/libraries/{library_id}")
def get_library(library_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.get_library, db, user, library_id))


@router.delete("/libraries/{library_id}")
def delete_library(library_id: int, db: Session = Depends(get_db), user: dict = Depends(require_permission("knowledge:admin"))):
    return ok(_call(service.delete_library, db, user, library_id))


@router.put("/libraries/{library_id}/members")
def replace_members(library_id: int, payload: MembersReplace, db: Session = Depends(get_db), user: dict = Depends(require_permission("knowledge:admin"))):
    return ok(_call(service.replace_members, db, user, library_id, [item.model_dump() for item in payload.members]))


@router.get("/libraries/{library_id}/members")
def list_members(library_id: int, db: Session = Depends(get_db), user: dict = Depends(require_permission("knowledge:admin"))):
    return ok(_call(service.list_members, db, user, library_id))


@router.get("/libraries/{library_id}/member-candidates")
def search_member_candidates(
    library_id: int,
    q: str = Query(default="", max_length=50),
    limit: int = Query(default=20, ge=1, le=20),
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge:admin")),
):
    return ok(_call(service.search_member_candidates, db, user, library_id, q, limit=limit))


@router.get("/libraries/{library_id}/tree")
def get_tree(library_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.get_tree, db, user, library_id))


@router.post("/libraries/{library_id}/documents")
def create_document(library_id: int, payload: DocumentCreate, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    if payload.node_type == "folder":
        row = _call(service.create_folder, db, user, library_id, title=payload.title, parent_id=payload.parent_id)
    else:
        if payload.content is None:
            raise HTTPException(422, "document content is required")
        row = _call(service.create_document, db, user, library_id, title=payload.title, content=payload.content, parent_id=payload.parent_id)
    return ok(_document(row))


@router.get("/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.get_document, db, user, document_id))


@router.put("/documents/{document_id}")
def save_document(document_id: int, payload: DocumentSave, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    row = _call(service.save_document, db, user, document_id, title=payload.title, content=payload.content)
    return ok({"id": row.id, "document_id": row.document_id, "version_no": row.version_no})


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    return ok(_call(service.delete_node, db, user, document_id))


@router.post("/documents/{document_id}/submit")
def submit_document(document_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    return ok(_approval(_call(service.submit_document, db, user, document_id)))


@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*REVIEW))):
    return ok(_call(service.list_approvals, db, user))


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*REVIEW))):
    return ok(_call(service.get_approval_detail, db, user, approval_id))


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, payload: ReviewInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*REVIEW))):
    return ok(_approval(_call(service.approve_request, db, user, approval_id, remark=payload.remark)))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, payload: ReviewInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*REVIEW))):
    return ok(_approval(_call(service.reject_request, db, user, approval_id, remark=payload.remark or "")))


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=128), limit: int = Query(default=20, ge=1, le=20), db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.search_published, db, user, q, limit=limit))
