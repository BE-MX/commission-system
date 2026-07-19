"""PM Hub router。全部端点（除 entry 与签名文件服务）走 require_pm_member。

文件下载/预览端点 `/files/{version_id}` 刻意无 Depends——浏览器 <a>/<img>/iframe
不带 Authorization header，用短时效签名 URL（素材模块同款模式），端点内
_verify_pm_signature 校验签名 + 软删状态 + nosniff + HTML 强制 attachment。
"""

import logging
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.pm import activity_service, comment_service, material_service, task_service
from app.pm.auth import (
    PmIdentity,
    check_entry_rate,
    client_ip,
    entry_fail,
    entry_rate_exceeded,
    issue_pm_token,
    require_pm_member,
)
from app.pm.diff_service import run_diff_in_background
from app.pm.models import PmMember
from app.pm.schemas import CommentCreate, EntryRequest, MaterialCreate, MaterialUpdate, TaskCreate, TaskUpdate, VersionTextCreate
from app.pm.service import (
    audit,
    build_signed_file_url,
    get_default_project,
    verify_file_sign,
)

logger = logging.getLogger("commission")

router = APIRouter()


# ── 进入与身份 ───────────────────────────────────────────────────────

@router.post("/entry")
def entry(payload: EntryRequest, request: Request, db: Session = Depends(get_db)):
    """门牌：白名单用户名换 token。失败提示统一，不区分原因（防枚举）。

    限速只计失败尝试（设计稿 §3.1），双维度：用户名 + 真实 IP（client_ip 取头）。
    先只读预检，验证失败才计数，避免合法用户被自己的成功进入误伤。"""
    username = payload.username.strip()
    ip = client_ip(request)
    if entry_rate_exceeded(username, ip):
        logger.warning("[PM] entry rate limited: %s (ip=%s)", username, ip)
        print(f"[PM] entry rate limited: {username} (ip={ip})", flush=True)
        raise HTTPException(status_code=429, detail="无法验证，请联系亮哥")
    member = (
        db.query(PmMember)
        .filter(PmMember.username == username, PmMember.is_active == 1)
        .first()
    )
    if not member:
        check_entry_rate(username, ip)  # 双维度各记一次失败；达到阈值后后续预检拦截
        raise entry_fail()
    token = issue_pm_token(member.username)
    try:
        project = get_default_project(db)
        audit(db, project.id, member.username, "entry", "member", member.id, member.display_name)
        db.commit()
    except ValueError as exc:  # 项目未 seed 时不阻塞进入（seed 脚本执行前的窗口期）
        logger.warning("[PM] entry audit skipped (project missing): %s", exc)
        print(f"[PM] entry audit skipped (project missing): {exc}", flush=True)
    return ok({"token": token, "username": member.username, "display_name": member.display_name})


@router.get("/me")
def me(identity: PmIdentity = Depends(require_pm_member)):
    return ok({"username": identity.username, "display_name": identity.display_name})


@router.get("/members")
def list_members(db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    members = (
        db.query(PmMember)
        .filter(PmMember.is_active == 1)
        .order_by(PmMember.id)
        .all()
    )
    return ok([{"username": m.username, "display_name": m.display_name} for m in members])


# ── 仪表盘 ───────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    return ok(activity_service.dashboard(db, project.id))


# ── 资料库 ───────────────────────────────────────────────────────────

@router.get("/materials")
def list_materials(db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    return ok(material_service.list_materials(db, project.id))


@router.post("/materials")
def create_material(payload: MaterialCreate, db: Session = Depends(get_db),
                    identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    material = material_service.create_material(db, project.id, identity.username, payload.model_dump())
    return ok(material_service.material_to_dict(material), message="已新增资料条目")


@router.get("/materials/{material_id}")
def material_detail(material_id: int, db: Session = Depends(get_db),
                    identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    versions = material_service.list_versions(db, material_id)
    current = material_service.current_version(db, material_id)
    comment_count = comment_service.comment_counts(db, [material_id]).get(material_id, 0)
    data = material_service.material_to_dict(
        material, current, len([v for v in versions if not v["is_deleted"]]), comment_count,
    )
    data["versions"] = versions
    return ok(data)


@router.put("/materials/{material_id}")
def update_material(material_id: int, payload: MaterialUpdate, db: Session = Depends(get_db),
                    identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    data = payload.model_dump(exclude_unset=True)
    material = material_service.update_material(db, material, identity.username, data)
    return ok(material_service.material_to_dict(material), message="已保存")


@router.delete("/materials/{material_id}")
def delete_material(material_id: int, db: Session = Depends(get_db),
                    identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    material_service.delete_material(db, material, identity.username)
    return ok(message="已删除（软删除，留痕可恢复）")


# ── 版本 ─────────────────────────────────────────────────────────────

@router.post("/materials/{material_id}/versions")
async def upload_version(material_id: int, background_tasks: BackgroundTasks,
                         file: UploadFile = File(...), change_note: str = Form("", max_length=512),
                         db: Session = Depends(get_db),
                         identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    # 先按声明的 Content-Length 挡超限，避免大文件全量读进内存再拒绝
    max_bytes = get_settings().PM_MAX_UPLOAD_MB * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=400, detail=f"单文件上限 {get_settings().PM_MAX_UPLOAD_MB}MB——超限请改用「外部链接」类型备注网盘地址")
    content = await file.read()
    version = material_service.upload_version(
        db, material, identity.username,
        file.filename or "unnamed", content, file.content_type, change_note,
    )
    if version.diff_status == "pending":
        background_tasks.add_task(run_diff_in_background, version.id)
    return ok(material_service.version_to_dict(version, material), message=f"已上传 v{version.version_no}")


@router.post("/materials/{material_id}/versions/text")
def save_text_version(material_id: int, payload: VersionTextCreate, background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    """在线编辑保存为新版本（Phase 2 §6.1）。

    基线冲突（编辑期间别人先存了新版）由前端提示、用户自行决定——后端不拒绝，
    版本号唯一约束保证并发保存也各得其号。"""
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    if payload.base_version_no is not None:
        base = material_service.get_version_by_no(db, material_id, payload.base_version_no)
    else:
        base = material_service.current_version(db, material_id)
    if not base or base.deleted_at is not None:
        raise HTTPException(status_code=404, detail="基准版本不存在或已删除")
    version = material_service.save_text_version(
        db, material, identity.username, base, payload.content, payload.change_note,
    )
    if version.diff_status == "pending":
        background_tasks.add_task(run_diff_in_background, version.id)
    return ok(material_service.version_to_dict(version, material), message=f"已保存 v{version.version_no}")


@router.delete("/versions/{version_id}")
def delete_version(version_id: int, db: Session = Depends(get_db),
                   identity: PmIdentity = Depends(require_pm_member)):
    version = material_service.get_version(db, version_id)
    if not version or version.deleted_at is not None:
        raise HTTPException(status_code=404, detail="版本不存在")
    material_service.delete_version(db, version, identity.username)
    return ok(message="已删除该版本")


@router.get("/versions/{version_id}/file-link")
def file_link(version_id: int, disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
              db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    """签发短时效下载/预览 URL（浏览器直链不带 Authorization，故走签名）。"""
    version = material_service.get_version(db, version_id)
    if not version or version.deleted_at is not None:
        raise HTTPException(status_code=404, detail="版本不存在或已删除")
    material = material_service.get_material(db, version.material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在或已删除")
    if disposition == "inline" and not material_service.inline_disposition_allowed(version):
        disposition = "attachment"
    return ok({
        "url": build_signed_file_url(version.id, disposition),
        "download_name": material_service.download_name(material.name, version),
    })


@router.post("/versions/{version_id}/retry-diff")
def retry_diff(version_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
               identity: PmIdentity = Depends(require_pm_member)):
    version = material_service.get_version(db, version_id)
    if not version or version.deleted_at is not None:
        raise HTTPException(status_code=404, detail="版本不存在")
    # 仅 failed 可重试：pending 说明在途或待看门狗回收，重入会并发重复调 AI
    if version.diff_status != "failed":
        raise HTTPException(status_code=400, detail="当前状态无需重试（生成中请稍候，超时由看门狗回收）")
    material_service.mark_diff_running(db, version.id)
    project = get_default_project(db)
    audit(db, project.id, identity.username, "retry_diff", "version", version.id, f"v{version.version_no}")
    db.commit()
    background_tasks.add_task(run_diff_in_background, version.id)
    return ok(message="已重新加入差异概要队列")


# ── 签名文件服务（无 Depends：签名即鉴权，见文件头注释）──────────────────

def _verify_pm_signature(version_id: int, token: str, expires: int) -> None:
    if not verify_file_sign(version_id, token, expires):
        raise HTTPException(status_code=403, detail="链接已过期或无效")


@router.get("/files/{version_id}")
def serve_file(version_id: int, token: str = Query(""), expires: int = Query(0),
               disposition: str = Query("attachment"), db: Session = Depends(get_db)):
    _verify_pm_signature(version_id, token, expires)
    version = material_service.get_version(db, version_id)
    if not version or version.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文件不存在或已删除")
    material = material_service.get_material(db, version.material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在或已删除")
    abs_path = material_service.to_abs(version.file_path)
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="文件已丢失，请联系管理员")
    ext = Path(version.original_name).suffix.lower()
    inline = disposition == "inline" and material_service.inline_disposition_allowed(version)
    media_type = mimetypes.guess_type(f"a{ext}")[0] or "application/octet-stream"
    if inline and ext in (".md", ".markdown", ".txt", ".log", ".csv", ".json"):
        media_type = "text/plain; charset=utf-8"  # MD 由前端 sanitize 后渲染，不内联 HTML
    return FileResponse(
        str(abs_path),
        filename=material_service.download_name(material.name, version),
        media_type=media_type,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


# ── 资料级评论（文件级；划线锚点评论属 Phase 2 另一条线）─────────────────

@router.get("/materials/{material_id}/comments")
def list_comments(material_id: int, db: Session = Depends(get_db),
                  identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    return ok(comment_service.list_comments(db, material_id))


@router.post("/materials/{material_id}/comments")
def create_comment(material_id: int, payload: CommentCreate, db: Session = Depends(get_db),
                   identity: PmIdentity = Depends(require_pm_member)):
    material = material_service.get_material(db, material_id)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    comment = comment_service.create_comment(db, material, identity.username, payload.body, payload.parent_id)
    return ok(comment_service.comment_to_dict(db, comment), message="已发布评论")


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db),
                   identity: PmIdentity = Depends(require_pm_member)):
    comment = comment_service.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在或已删除")
    if comment.author != identity.username:
        raise HTTPException(status_code=403, detail="只能删除自己发布的评论")
    material = material_service.get_material(db, comment.material_id, include_deleted=True)
    if not material:
        raise HTTPException(status_code=404, detail="资料不存在")
    comment_service.delete_comment(db, comment, material, identity.username)
    return ok(message="已删除评论")


# ── 任务看板 ─────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(assignee: Optional[str] = None, phase: Optional[int] = None,
               db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    return ok(task_service.list_tasks(db, project.id, assignee, phase))


@router.post("/tasks")
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    task = task_service.create_task(db, project.id, identity.username, payload.model_dump())
    return ok(task_service.task_to_dict(task), message="已创建任务")


@router.put("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db),
                identity: PmIdentity = Depends(require_pm_member)):
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    data = payload.model_dump(exclude_unset=True)
    task = task_service.update_task(db, task, identity.username, data)
    return ok(task_service.task_to_dict(task), message="已保存")


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db),
                identity: PmIdentity = Depends(require_pm_member)):
    task = task_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task_service.delete_task(db, task, identity.username)
    return ok(message="已删除任务")


# ── 全站动态 ─────────────────────────────────────────────────────────

@router.get("/activity")
def list_activity(username: Optional[str] = None, object_type: Optional[str] = None,
                  limit: int = Query(50, le=200), offset: int = 0,
                  db: Session = Depends(get_db), identity: PmIdentity = Depends(require_pm_member)):
    project = get_default_project(db)
    return ok(activity_service.list_activity(db, project.id, username, object_type, limit, offset))
