from pathlib import PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.cross_border import export_service, import_service, review_service
from app.cross_border.parser import MAX_BYTES, WorkbookError
from app.cross_border.schemas import ExportRequest, ListFilters, ReviewRequest

router = APIRouter()
Database = Annotated[Session, Depends(get_db)]
READ = "cross_border:read"
WRITE = "cross_border:write"


@router.post("/imports")
def upload(db: Database, files: list[UploadFile] = File(...), user=Depends(require_permission(WRITE))):
    if not 1 <= len(files) <= 2:
        raise HTTPException(422, "请选择一至两个 DHL 导出文件")
    results = []
    for upload_file in files:
        name = PureWindowsPath(upload_file.filename or "未命名").name
        try:
            results.append(import_service.import_file(db, name, upload_file.file.read(MAX_BYTES + 1), int(user["sub"])))
        except WorkbookError as exc:
            results.append({"file_name": name, "status": "error", "message": str(exc)})
    return ok({"items": results})


@router.get("/imports")
def imports(db: Database, user=Depends(require_permission(READ))):
    return ok({"items": import_service.list_batches(db)})


@router.get("/declarations")
def declarations(db: Database, filters: Annotated[ListFilters, Depends()], user=Depends(require_permission(READ))):
    return ok(review_service.list_declarations(db, filters))


@router.get("/declarations/{content_hash}")
def detail(content_hash: str, db: Database, user=Depends(require_permission(READ))):
    return ok(review_service.detail(db, content_hash))


@router.post("/declarations/{content_hash}/reviews")
def review(content_hash: str, body: ReviewRequest, db: Database, user=Depends(require_permission(WRITE))):
    return ok(review_service.review(db, content_hash, body, int(user["sub"])))


@router.post("/exports")
def export(body: ExportRequest, db: Database, user=Depends(require_permission(WRITE))):
    return ok(export_service.create_export(db, body, int(user["sub"])))


@router.get("/exports/{export_id}/files/{kind}")
def download(export_id: int, kind: Literal["order", "receipt"], db: Database, user=Depends(require_permission(READ))):
    name = ("报关订单" if kind == "order" else "报关收款单") + f"-{export_id}.xlsx"
    return Response(export_service.get_file(db, export_id, kind),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
                             "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
