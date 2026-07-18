"""PM Hub 资料条目 + 版本管理（本站核心状态机，管钱管货同等标准）。

版本规则（设计稿 §5.4）：
- 版本号条目内自增、只增不复用：删除 v3 后下一次上传是 v4，其差异对比对象是 v2
- 当前版本 = 未删除的最大版本号；AI 差异的「上一版」同口径
- (material_id, version_no) 数据库唯一约束 + 冲突自动重试（并发上传不撞号）
- 凭据类（offline）禁止上传原文；外部链接类（link）只存 URL
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.pm.models import PmMaterial, PmMaterialVersion, bj_now
from app.pm.service import audit, ensure_storage_root, to_abs

logger = logging.getLogger("commission")

PREVIEWABLE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf", ".md", ".markdown", ".txt"}
FORCED_DOWNLOAD_EXTS = {".html", ".htm", ".svg", ".xml", ".js"}  # 强制 attachment，防存储型 XSS
EDITABLE_TEXT_EXTS = {".md", ".markdown", ".txt"}  # 在线编辑（§6.1）只开放文本类
UPLOAD_RETRY = 3


# ── 查询 ─────────────────────────────────────────────────────────────

def get_material(db: Session, material_id: int, include_deleted: bool = False) -> Optional[PmMaterial]:
    q = db.query(PmMaterial).filter(PmMaterial.id == material_id)
    if not include_deleted:
        q = q.filter(PmMaterial.deleted_at.is_(None))
    return q.first()


def current_version(db: Session, material_id: int) -> Optional[PmMaterialVersion]:
    """当前版本 = 未删除的最大版本号（全站统一口径，勿另写）。"""
    return (
        db.query(PmMaterialVersion)
        .filter(PmMaterialVersion.material_id == material_id, PmMaterialVersion.deleted_at.is_(None))
        .order_by(PmMaterialVersion.version_no.desc())
        .first()
    )


def previous_version(db: Session, version: PmMaterialVersion) -> Optional[PmMaterialVersion]:
    """AI 差异对比的「上一版」：同口径取比本版小的最大未删除版本。"""
    return (
        db.query(PmMaterialVersion)
        .filter(
            PmMaterialVersion.material_id == version.material_id,
            PmMaterialVersion.deleted_at.is_(None),
            PmMaterialVersion.version_no < version.version_no,
        )
        .order_by(PmMaterialVersion.version_no.desc())
        .first()
    )


def list_materials(db: Session, project_id: int) -> list[dict]:
    """清单视图：条目 + 当前版本号 + 最后更新（人+时间）。数据量小，一次取齐内存聚合。"""
    materials = (
        db.query(PmMaterial)
        .filter(PmMaterial.project_id == project_id, PmMaterial.deleted_at.is_(None))
        .order_by(PmMaterial.category, PmMaterial.sort_order, PmMaterial.list_no, PmMaterial.id)
        .all()
    )
    if not materials:
        return []
    ids = [m.id for m in materials]
    versions = (
        db.query(PmMaterialVersion)
        .filter(PmMaterialVersion.material_id.in_(ids), PmMaterialVersion.deleted_at.is_(None))
        .all()
    )
    latest: dict[int, PmMaterialVersion] = {}
    counts: dict[int, int] = {}
    for v in versions:
        counts[v.material_id] = counts.get(v.material_id, 0) + 1
        if v.material_id not in latest or v.version_no > latest[v.material_id].version_no:
            latest[v.material_id] = v
    return [material_to_dict(m, latest.get(m.id), counts.get(m.id, 0)) for m in materials]


def material_to_dict(m: PmMaterial, latest: Optional[PmMaterialVersion] = None, version_count: int = 0) -> dict:
    return {
        "id": m.id,
        "list_no": m.list_no,
        "name": m.name,
        "description": m.description,
        "category": m.category,
        "importance": m.importance,
        "phase": m.phase,
        "delivery_type": m.delivery_type,
        "external_url": m.external_url,
        "delivery_remark": m.delivery_remark,
        "status": m.status,
        "owner": m.owner,
        "current_version_no": latest.version_no if latest else None,
        "version_count": version_count,
        "last_uploaded_by": latest.uploaded_by if latest else None,
        "last_uploaded_at": latest.created_at.isoformat(sep=" ") if latest else None,
        "updated_at": m.updated_at.isoformat(sep=" ") if m.updated_at else None,
    }


def version_to_dict(v: PmMaterialVersion, material: Optional[PmMaterial] = None) -> dict:
    ext = Path(v.original_name).suffix.lower()
    return {
        "id": v.id,
        "material_id": v.material_id,
        "version_no": v.version_no,
        "original_name": v.original_name,
        "download_name": download_name(material.name if material else "", v) if material else None,
        "file_size": v.file_size,
        "ext": ext,
        "previewable": ext in PREVIEWABLE_EXTS,
        "change_note": v.change_note,
        "diff_status": v.diff_status,
        "diff_summary": v.diff_summary,
        "diff_error": v.diff_error,
        "uploaded_by": v.uploaded_by,
        "created_at": v.created_at.isoformat(sep=" ") if v.created_at else None,
        "is_deleted": v.deleted_at is not None,
    }


def list_versions(db: Session, material_id: int) -> list[dict]:
    """版本时间线（最新在上，含已删除标记——时间线要能看到「曾有 v3 被删」）。"""
    material = get_material(db, material_id)
    if not material:
        raise ValueError("资料不存在")
    versions = (
        db.query(PmMaterialVersion)
        .filter(PmMaterialVersion.material_id == material_id)
        .order_by(PmMaterialVersion.version_no.desc())
        .all()
    )
    cur = current_version(db, material_id)
    cur_no = cur.version_no if cur else None
    return [
        {**version_to_dict(v, material), "is_current": v.version_no == cur_no and v.deleted_at is None}
        for v in versions
    ]


# ── 条目写操作 ────────────────────────────────────────────────────────

def _assert_name_unique(db: Session, project_id: int, name: str, exclude_id: Optional[int] = None) -> None:
    q = db.query(PmMaterial).filter(
        PmMaterial.project_id == project_id,
        PmMaterial.name == name,
        PmMaterial.deleted_at.is_(None),
    )
    if exclude_id:
        q = q.filter(PmMaterial.id != exclude_id)
    if q.first():
        raise ValueError(f"已存在同名资料「{name}」——名称在项目内必须唯一")


def _validate_external_url(url: Optional[str]) -> Optional[str]:
    """外部链接只放行 http/https——javascript: 等 scheme 是存储型 XSS（本站 token 即身份）。"""
    if not url:
        return None
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("外部链接必须以 http:// 或 https:// 开头")
    return url[:512]


VALID_MATERIAL_STATUSES = ("not_started", "preparing", "submitted", "confirmed", "not_required")
VALID_DELIVERY_TYPES = ("file", "offline", "link")
VALID_IMPORTANCE = ("required", "important", "optional")


def create_material(db: Session, project_id: int, username: str, data: dict) -> PmMaterial:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("名称必填")
    delivery_type = data.get("delivery_type") or "file"
    if delivery_type not in VALID_DELIVERY_TYPES:
        raise ValueError("交付类型不合法")
    importance = data.get("importance") or "important"
    if importance not in VALID_IMPORTANCE:
        raise ValueError("重要级不合法")
    _assert_name_unique(db, project_id, name)
    external_url = _validate_external_url(data.get("external_url"))
    if delivery_type == "link" and not external_url:
        raise ValueError("外部链接类型必须填写链接地址")
    material = PmMaterial(
        project_id=project_id,
        name=name[:256],
        description=(data.get("description") or "").strip()[:1024] or None,
        category=(data.get("category") or "其他").strip()[:64],
        importance=importance,
        phase=data.get("phase") if data.get("phase") in (1, 2, 3, 4) else None,
        delivery_type=delivery_type,
        external_url=external_url,
        delivery_remark=(data.get("delivery_remark") or "").strip()[:512] or None,
        owner=(data.get("owner") or None) and str(data.get("owner"))[:64],
    )
    db.add(material)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError(f"已存在同名资料「{name}」——名称在项目内必须唯一")
    audit(db, project_id, username, "create_material", "material", material.id, material.name)
    db.commit()
    db.refresh(material)
    return material


def update_material(db: Session, material: PmMaterial, username: str, data: dict) -> PmMaterial:
    changes: dict = {}
    if "name" in data and data["name"] and data["name"].strip() != material.name:
        _assert_name_unique(db, material.project_id, data["name"].strip(), exclude_id=material.id)
        changes["name"] = {"from": material.name, "to": data["name"].strip()[:256]}
        material.name = data["name"].strip()[:256]
    if "status" in data and data["status"] and data["status"] != material.status:
        if data["status"] not in VALID_MATERIAL_STATUSES:
            raise ValueError("状态不合法")
        changes["status"] = {"from": material.status, "to": data["status"]}
        material.status = data["status"]
    _FIELD_CAPS = {"description": 1024, "category": 64, "delivery_remark": 512, "owner": 64}
    for field, cap in _FIELD_CAPS.items():
        if field in data:
            new_val = ((data[field] or "").strip() or None)
            if new_val:
                new_val = new_val[:cap]
            if new_val != getattr(material, field):
                changes[field] = {"from": getattr(material, field), "to": new_val}
                setattr(material, field, new_val)
    if "external_url" in data:
        new_url = _validate_external_url(data["external_url"])
        if new_url != material.external_url:
            changes["external_url"] = {"from": material.external_url, "to": new_url}
            material.external_url = new_url
    if "importance" in data and data["importance"]:
        if data["importance"] not in VALID_IMPORTANCE:
            raise ValueError("重要级不合法")
        if data["importance"] != material.importance:
            changes["importance"] = {"from": material.importance, "to": data["importance"]}
            material.importance = data["importance"]
    if "phase" in data:
        new_phase = data["phase"] if data["phase"] in (1, 2, 3, 4) else None
        if new_phase != material.phase:
            changes["phase"] = {"from": material.phase, "to": new_phase}
            material.phase = new_phase
    if not changes:
        return material
    material.updated_at = bj_now()
    audit(db, material.project_id, username, "update_material", "material", material.id, material.name, changes)
    try:
        db.commit()
    except IntegrityError:  # 并发改名撞唯一约束（TOCTOU），转友好 400（cerebrum 2026-07-14）
        db.rollback()
        raise ValueError(f"已存在同名资料「{material.name}」——名称在项目内必须唯一")
    db.refresh(material)
    return material


def delete_material(db: Session, material: PmMaterial, username: str) -> None:
    """软删整条资料。改名让位唯一约束（截断防溢出 VARCHAR(256)）。"""
    material.deleted_at = bj_now()
    original_name = material.name
    material.name = f"{original_name[:240]}#del{material.id}"
    audit(db, material.project_id, username, "delete_material", "material", material.id, original_name)
    db.commit()


# ── 版本写操作 ────────────────────────────────────────────────────────

def _next_version_no(db: Session, material_id: int) -> int:
    """下一个版本号：基于含已删除的全部版本取 max + 1（只增不复用）。"""
    return (
        db.query(func.max(PmMaterialVersion.version_no))
        .filter(PmMaterialVersion.material_id == material_id)
        .scalar()
        or 0
    ) + 1


def upload_version(db: Session, material: PmMaterial, username: str,
                   filename: str, content: bytes, content_type: Optional[str],
                   change_note: Optional[str],
                   audit_action: str = "upload_version",
                   audit_extra: Optional[dict] = None) -> PmMaterialVersion:
    """上传新版本。版本号并发安全：唯一约束 + IntegrityError 重试。"""
    if material.delivery_type == "offline":
        raise ValueError("该材料为凭据类线下交付，禁止上传原文——只跟踪状态与备注")
    if material.delivery_type == "link":
        raise ValueError("该材料为外部链接类型，请维护链接而非上传文件")
    max_bytes = get_settings().PM_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(f"单文件上限 {get_settings().PM_MAX_UPLOAD_MB}MB——超限请改用「外部链接」类型备注网盘地址")
    if not filename:
        raise ValueError("缺少文件名")

    ext = Path(filename).suffix.lower()
    rel_path = f"{material.id}/{uuid.uuid4().hex}{ext}"
    abs_path = to_abs(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    for attempt in range(UPLOAD_RETRY):
        next_no = _next_version_no(db, material.id)
        version = PmMaterialVersion(
            material_id=material.id,
            version_no=next_no,
            file_path=rel_path,
            original_name=filename[:256],
            file_size=len(content),
            content_type=(content_type or None) and content_type[:128],
            change_note=(change_note or "").strip()[:512] or None,
            diff_status="not_applicable" if next_no == 1 else "pending",
            uploaded_by=username,
            created_at=bj_now(),
        )
        db.add(version)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()  # 并发撞号：回滚后重取 max 重试（cerebrum：commit/flush 失败后必须 rollback）
            if attempt == UPLOAD_RETRY - 1:
                _remove_file_quietly(rel_path)
                raise ValueError("版本号分配冲突，请重试")

    # 上传成功即推进条目状态（未开始/准备中 → 已提交），已有更进一步状态则不回退
    if material.status in ("not_started", "preparing"):
        material.status = "submitted"
        material.updated_at = bj_now()
    audit(
        db, material.project_id, username, audit_action, "version", version.id,
        f"{material.name} v{version.version_no}",
        {"change_note": version.change_note, "size": len(content), **(audit_extra or {})},
    )
    try:
        db.commit()
    except Exception:  # DB 失败必须带走已落盘文件，否则留下无 DB 引用的孤儿
        db.rollback()
        _remove_file_quietly(rel_path)
        raise
    db.refresh(version)
    return version


def get_version_by_no(db: Session, material_id: int, version_no: int) -> Optional[PmMaterialVersion]:
    return (
        db.query(PmMaterialVersion)
        .filter(PmMaterialVersion.material_id == material_id, PmMaterialVersion.version_no == version_no)
        .first()
    )


def save_text_version(db: Session, material: PmMaterial, username: str,
                      base_version: PmMaterialVersion, content_text: str,
                      change_note: Optional[str]) -> PmMaterialVersion:
    """在线编辑保存：与上传走完全相同的版本通道（设计稿 §6.1，模型上无特例）。

    文件名承接被编辑版本的 original_name——下载名/预览类型/后续可编辑性都由扩展名派生，
    编辑链上保持不变。"""
    ext = Path(base_version.original_name).suffix.lower()
    if ext not in EDITABLE_TEXT_EXTS:
        raise ValueError("仅 Markdown / 纯文本类版本支持在线编辑")
    if not content_text.strip():
        raise ValueError("内容为空，未保存")
    return upload_version(
        db, material, username,
        filename=base_version.original_name,
        content=content_text.encode("utf-8"),
        content_type="text/markdown" if ext in (".md", ".markdown") else "text/plain",
        change_note=change_note,
        audit_action="edit_version",
        audit_extra={"based_on": base_version.version_no},
    )


def delete_version(db: Session, version: PmMaterialVersion, username: str) -> None:
    """软删单版本。文件保留在盘上（恢复找亮哥），下载端点立即拒绝。"""
    material = get_material(db, version.material_id, include_deleted=True)
    version.deleted_at = bj_now()
    audit(
        db, material.project_id if material else 0, username, "delete_version", "version",
        version.id, f"{material.name if material else '?'} v{version.version_no}",
    )
    db.commit()


def get_version(db: Session, version_id: int) -> Optional[PmMaterialVersion]:
    return db.query(PmMaterialVersion).filter(PmMaterialVersion.id == version_id).first()


def download_name(material_name: str, version: PmMaterialVersion) -> str:
    """对外文件名自动拼接：价格体系_v3.xlsx（原始文件名只存档）。"""
    ext = Path(version.original_name).suffix
    safe = "".join(c for c in material_name if c not in '\\/:*?"<>|').strip() or "material"
    return f"{safe}_v{version.version_no}{ext}"


def inline_disposition_allowed(version: PmMaterialVersion) -> bool:
    ext = Path(version.original_name).suffix.lower()
    if ext in FORCED_DOWNLOAD_EXTS:
        return False
    return ext in PREVIEWABLE_EXTS


def _remove_file_quietly(rel_path: str) -> None:
    try:
        to_abs(rel_path).unlink(missing_ok=True)
    except OSError as exc:  # 文件清理失败不该顶成 500（cerebrum 2026-07-15）
        logger.warning("[PM] remove file failed %s: %s", rel_path, exc)
        print(f"[PM] remove file failed {rel_path}: {exc}", flush=True)


# ── 上传重试辅助 ─────────────────────────────────────────────────────

def mark_diff_running(db: Session, version_id: int) -> None:
    v = get_version(db, version_id)
    if v:
        v.diff_status = "pending"
        v.diff_error = None
        db.commit()


def storage_root_ready() -> None:
    ensure_storage_root()
