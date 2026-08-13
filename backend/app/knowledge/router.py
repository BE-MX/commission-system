"""Authorized HTTP endpoints for the native knowledge base."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.knowledge import asset_service, service
from app.knowledge import image_service
from app.knowledge.schemas import DocumentCreate, DocumentSave, LibraryCreate, MembersReplace, ReviewInput
from app.knowledge.ai_schemas import AiJobCreate, AiProfileInput, AiProfileTestInput
from app.knowledge import ai_job_service, ai_profile_service


router = APIRouter()
UPLOAD_CHUNK_BYTES = 1024 * 1024
READ = ("knowledge:read", "knowledge:write", "knowledge:review", "knowledge:admin")
WRITE = ("knowledge:write", "knowledge:admin")
REVIEW = ("knowledge:review", "knowledge:admin")
AI_WRITE = ("knowledge_ai:write", "knowledge_ai:admin")


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


async def _read_image(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    limit = image_service.max_upload_bytes()
    try:
        while True:
            chunk = await upload.read(min(UPLOAD_CHUNK_BYTES, limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"图片不能超过 {limit // image_service.MEBIBYTE}MiB",
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        await upload.close()


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


@router.post("/libraries/{library_id}/assets")
async def upload_image(
    library_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*WRITE)),
):
    content = await _read_image(file)
    try:
        row = _call(
            asset_service.create_image_asset,
            db,
            user,
            library_id,
            original_name=file.filename or "image",
            mime_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except (image_service.ImageValidationError, image_service.ImageStorageError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return ok({
        "id": row.id,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "alt": "",
        "caption": "",
    })


@router.get("/assets/{asset_id}/content")
def read_image(
    asset_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*READ)),
):
    row = _call(asset_service.get_image_asset, db, user, asset_id)
    path = image_service.resolve_private_path(row.storage_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge image not found")
    return FileResponse(
        path,
        media_type=row.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/assets/{asset_id}")
def delete_image(
    asset_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*WRITE)),
):
    return ok(_call(asset_service.delete_temporary_image, db, user, asset_id))


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
    return ok(_approval(_call(
        service.approve_request,
        db,
        user,
        approval_id,
        remark=payload.remark,
        confirm_cross_library_sources=payload.confirm_cross_library_sources,
    )))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, payload: ReviewInput, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*REVIEW))):
    return ok(_approval(_call(service.reject_request, db, user, approval_id, remark=payload.remark or "")))


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=128), limit: int = Query(default=20, ge=1, le=20), db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(service.search_published, db, user, q, limit=limit))


@router.get("/ai-profiles")
def list_ai_profiles(
    target_library_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    return ok(_call(
        ai_profile_service.list_profiles,
        db,
        user,
        target_library_id=target_library_id,
    ))


@router.get("/ai-profiles/preset-candidates")
def ai_preset_candidates(
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.list_preset_candidates, db, user))


@router.get("/ai-profiles/library-candidates")
def ai_library_candidates(
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.list_library_candidates, db, user))


@router.post("/ai-profiles")
def create_ai_profile(
    payload: AiProfileInput,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.create_profile, db, user, payload.model_dump()))


@router.put("/ai-profiles/{profile_id}")
def update_ai_profile(
    profile_id: int,
    payload: AiProfileInput,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.update_profile, db, user, profile_id, payload.model_dump()))


@router.delete("/ai-profiles/{profile_id}")
def delete_ai_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.delete_profile, db, user, profile_id))


@router.get("/ai-profiles/{profile_id}/logs")
def ai_profile_logs(
    profile_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(ai_profile_service.list_profile_logs, db, user, profile_id))


@router.post("/ai-profiles/{profile_id}/retrieval-preview")
def ai_retrieval_preview(
    profile_id: int,
    payload: AiProfileTestInput,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(
        ai_job_service.preview_retrieval,
        db,
        user,
        profile_id,
        payload.target_library_id,
        payload.sample_text,
    ))


@router.post("/ai-profiles/{profile_id}/test")
def ai_profile_test(
    profile_id: int,
    payload: AiProfileTestInput,
    db: Session = Depends(get_db),
    user: dict = Depends(require_permission("knowledge_ai:admin")),
):
    return ok(_call(
        ai_profile_service.test_profile_connection,
        db,
        user,
        profile_id,
        payload.target_library_id,
        payload.sample_text,
    ))


@router.post("/documents/{document_id}/ai-jobs")
def create_ai_job(
    document_id: int,
    payload: AiJobCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    row = _call(
        ai_job_service.create_job,
        db,
        user,
        document_id,
        **payload.model_dump(),
    )
    return ok(ai_job_service.serialize_job(db, row))


@router.get("/documents/{document_id}/ai-jobs")
def list_ai_jobs(
    document_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    return ok(_call(ai_job_service.list_document_jobs, db, user, document_id))


@router.get("/ai-jobs/{job_id}")
def get_ai_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    return ok(_call(ai_job_service.get_job, db, user, job_id))


@router.post("/ai-jobs/{job_id}/cancel")
def cancel_ai_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    return ok(_call(ai_job_service.cancel_job, db, user, job_id))


@router.post("/ai-jobs/{job_id}/apply")
def apply_ai_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*AI_WRITE)),
):
    return ok(_call(ai_job_service.apply_job, db, user, job_id))
