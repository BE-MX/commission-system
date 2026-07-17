"""培训速递 — API 路由

权限：training:read（看）/ training:write（发布编辑，仅本人内容）/ training:admin（管理全部）。
统一信封 ok()；用户 ID 一律 int(current_user["sub"])（cerebrum 2026-07-13）。
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.response import ok
from app.training import draft_service, file_service, push_service, service
from app.training.models import TrainingDigest, TrainingDigestFile
from app.training.schemas import DigestCreate, DigestUpdate, DraftRequest

logger = logging.getLogger("commission")

router = APIRouter()

_READ_PERMS = ("training:read", "training:write", "training:admin")


def _get_digest_or_404(db: Session, digest_id: int) -> TrainingDigest:
    digest = db.query(TrainingDigest).filter(TrainingDigest.id == digest_id).first()
    if not digest:
        raise HTTPException(status_code=404, detail="培训速递不存在")
    return digest


def _require_manage(digest: TrainingDigest, user: dict) -> None:
    if not service.can_manage(user, digest):
        raise HTTPException(status_code=403, detail="只有发布人本人或管理员可以操作这条速递")


@router.get("", summary="培训速递列表")
def list_digests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    tag: str = Query(""),
    status: str = Query("", pattern="^(draft|published)?$"),
    mine: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    data = service.list_digests(
        db,
        page=page,
        page_size=page_size,
        user_id=int(current_user["sub"]),
        keyword=keyword,
        tag=tag,
        status=status,
        mine=mine,
    )
    return ok(data)


@router.post("", summary="创建培训速递（草稿）")
def create_digest(
    payload: DigestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = service.create_digest(db, payload, int(current_user["sub"]))
    return ok({"id": digest.id}, message="草稿已创建")


@router.get("/{digest_id}", summary="培训速递详情")
def get_digest(
    digest_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    digest = _get_digest_or_404(db, digest_id)
    if digest.status != "published" and not service.can_manage(current_user, digest):
        raise HTTPException(status_code=404, detail="培训速递不存在")
    return ok(service.get_detail(db, digest, current_user))


@router.put("/{digest_id}", summary="编辑培训速递")
def update_digest(
    digest_id: int,
    payload: DigestUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    service.update_digest(db, digest, payload)
    return ok(service.get_detail(db, digest, current_user, count_view=False), message="已保存")


@router.delete("/{digest_id}", summary="删除培训速递")
def delete_digest(
    digest_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    if digest.status == "published" and "training:admin" not in current_user.get("permissions", []) \
            and "super_admin" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="已发布的速递只有管理员可以删除，可先联系管理员下架")
    service.delete_digest(db, digest)
    return ok(message="已删除")


@router.post("/{digest_id}/files", summary="上传原始资料附件")
async def upload_file(
    digest_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    content = await file.read()
    try:
        file_service.validate_upload(file.filename or "", file.content_type or "", len(content))
    except file_service.FileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    rel_path = file_service.store_bytes(file.filename or "file", content)
    item = service.add_file(
        db,
        digest,
        file_name=file.filename or "file",
        storage_path=rel_path,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        uploaded_by=int(current_user["sub"]),
    )
    return ok(
        {"id": item.id, "file_name": item.file_name, "file_size": item.file_size, "mime_type": item.mime_type},
        message="资料已上传",
    )


@router.delete("/files/{file_id}", summary="删除附件")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    item = db.query(TrainingDigestFile).filter(TrainingDigestFile.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="附件不存在")
    digest = _get_digest_or_404(db, item.digest_id)
    _require_manage(digest, current_user)
    service.remove_file(db, item)
    return ok(message="附件已删除")


@router.get("/files/{file_id}/download", summary="鉴权下载附件")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    item = db.query(TrainingDigestFile).filter(TrainingDigestFile.id == file_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="附件不存在")
    digest = _get_digest_or_404(db, item.digest_id)
    if digest.status != "published" and not service.can_manage(current_user, digest):
        raise HTTPException(status_code=404, detail="附件不存在")
    try:
        path = file_service.resolve_private_path(item.storage_path)
    except file_service.FileValidationError:
        raise HTTPException(status_code=404, detail="附件文件缺失")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件缺失，请联系发布人重新上传")
    return FileResponse(path, media_type=item.mime_type or "application/octet-stream", filename=item.file_name)


@router.post("/{digest_id}/draft", summary="AI 提炼生成草稿")
def generate_draft(
    digest_id: int,
    payload: DraftRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    try:
        draft = draft_service.generate_draft(db, digest, payload.text_materials)
    except draft_service.DraftMaterialError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        msg = f"[training] draft generate failed digest={digest_id}: {type(e).__name__}: {e}"
        logger.warning(msg)
        print(msg, flush=True)
        raise HTTPException(status_code=502, detail="AI 提炼暂时不可用，可稍后重试，或直接手动填写各分区")
    return ok(draft, message="AI 草稿已生成，请逐区校对")


@router.post("/{digest_id}/publish", summary="发布并推送钉钉群")
def publish_digest(
    digest_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    problems = service.validate_for_publish(digest)
    if problems:
        raise HTTPException(status_code=400, detail="发布校验未通过：" + "；".join(problems))
    service.publish_digest(db, digest)
    creator = db.query(ArkUser.real_name, ArkUser.username).filter(ArkUser.id == digest.created_by).first()
    creator_name = (creator[0] or creator[1]) if creator else "同事"
    pushed = push_service.push_published(digest, creator_name)
    message = "已发布并推送钉钉群" if pushed else "已发布（钉钉推送未成功，可在详情页重推）"
    return ok({"id": digest.id, "pushed": pushed}, message=message)


@router.post("/{digest_id}/push", summary="手动重推钉钉群")
def push_digest(
    digest_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_permission("training:write")),
):
    digest = _get_digest_or_404(db, digest_id)
    _require_manage(digest, current_user)
    if digest.status != "published":
        raise HTTPException(status_code=400, detail="草稿不能推送，请先发布")
    creator = db.query(ArkUser.real_name, ArkUser.username).filter(ArkUser.id == digest.created_by).first()
    creator_name = (creator[0] or creator[1]) if creator else "同事"
    pushed = push_service.push_published(digest, creator_name)
    if not pushed:
        raise HTTPException(status_code=502, detail="钉钉推送失败，请检查群机器人配置后重试")
    return ok({"pushed": True}, message="已推送钉钉群")


@router.post("/{digest_id}/useful", summary="标记/取消「有用」")
def toggle_useful(
    digest_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*_READ_PERMS)),
):
    digest = _get_digest_or_404(db, digest_id)
    if digest.status != "published":
        raise HTTPException(status_code=400, detail="草稿不能标记有用")
    return ok(service.toggle_useful(db, digest, int(current_user["sub"])))
