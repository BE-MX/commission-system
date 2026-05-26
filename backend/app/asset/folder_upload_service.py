"""素材管理 — 文件夹批量上传服务

流程：扫描文件夹 → 提取候选标签 → 校验标签库匹配 → 预览 → 执行入库
"""

import os
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.asset.asset_service import (
    ASSET_STORAGE_ROOT,
    _build_storage_path,
    _generate_thumbnail,
    _generate_video_thumbnail,
    _save_upload_file,
)
from app.asset.models import Asset, TagDimension, TagValue
from app.asset.schemas import AssetPermissionIn, AssetTagItem

# ── 配置 ────────────────────────────────────────────────

SUPPORTED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".gif", ".bmp", ".tiff", ".tif",
}

SUPPORTED_VIDEO_EXTS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv",
    ".flv", ".webm", ".m4v", ".3gp", ".mpeg", ".mpg",
}

SUPPORTED_FILE_EXTS = SUPPORTED_IMAGE_EXTS | SUPPORTED_VIDEO_EXTS

SKIP_FILES = {".ds_store", "thumbs.db", "desktop.ini"}

# 系统保留维度名：文件夹名等于这些时跳过，不作为标签提取
RESERVED_DIMENSION_LABELS = {"素材类型", "状态", "版本", "日期", "权限组"}

# staging 根目录（从环境变量读取）
UPLOAD_STAGING_ROOT = os.environ.get("ASSET_UPLOAD_STAGING", r"D:\upload_staging")

# 异步执行文件数量阈值
ASYNC_FILE_THRESHOLD = 20

# 异步任务状态存储（内存中，重启后丢失）
_folder_upload_jobs: dict[str, dict] = {}


# ── 文本工具 ────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """文本规范化：NFKC（全角→半角）+ 小写 + 去首尾空格。"""
    text = unicodedata.normalize("NFKC", text)
    return text.lower().strip()


# ── 扫描与提取 ──────────────────────────────────────────

def _detect_file_type(ext: str) -> str:
    """根据扩展名判断 file_type（image / video / document）。"""
    ext_lower = ext.lower().lstrip(".")
    if ext_lower in {"jpg", "jpeg", "png", "webp", "heic", "gif", "bmp", "tiff", "tif"}:
        return "image"
    if ext_lower in {"mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "3gp", "mpeg", "mpg"}:
        return "video"
    return "document"


def scan_folder(folder_path: str) -> list[str]:
    """递归扫描文件夹，返回所有图片/视频文件的绝对路径列表（按字母序）。"""
    result: list[str] = []
    root = Path(folder_path)

    if not root.exists() or not root.is_dir():
        return result

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        file_name_lower = path.name.lower()
        if file_name_lower in SKIP_FILES:
            continue

        ext = path.suffix.lower()
        if ext not in SUPPORTED_FILE_EXTS:
            continue

        result.append(str(path))

    return sorted(result)


def extract_tags_from_path(file_path: str, root_path: str) -> list[str]:
    """从文件路径提取文件夹名作为候选标签（排除根目录和保留维度名）。

    返回原始文件夹名（保持原始大小写/字符），用于展示和后续匹配。
    """
    file_p = Path(file_path).resolve()
    root_p = Path(root_path).resolve()

    try:
        rel = file_p.relative_to(root_p)
    except ValueError:
        return []

    reserved_norm = {_normalize_text(l) for l in RESERVED_DIMENSION_LABELS}

    tags: list[str] = []

    # 所选文件夹本身的名称也作为标签
    root_name = root_p.name
    norm_root = _normalize_text(root_name)
    if norm_root and norm_root not in reserved_norm:
        tags.append(root_name)

    for part in rel.parent.parts:
        normalized = _normalize_text(part)
        if not normalized or normalized in reserved_norm:
            continue
        tags.append(part)

    return tags


# ── 标签校验 ────────────────────────────────────────────

@dataclass
class TagValidationResult:
    matched: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.missing) == 0 and len(self.ambiguous) == 0


def validate_folder_tags(db: Session, tag_names: list[str]) -> TagValidationResult:
    """验证候选标签与标签库的匹配情况。

    匹配规则：
    1. 唯一匹配 → 成功
    2. 无匹配 → 缺失
    3. 多维度匹配 → 歧义
    """
    result = TagValidationResult()

    # 去重，保持顺序
    unique_names = list(dict.fromkeys(tag_names))

    # 一次加载所有活跃标签值到内存
    all_values = (
        db.query(TagValue)
        .filter(TagValue.is_active == 1)
        .all()
    )

    # 规范化值 -> [匹配记录]
    normalized_map: dict[str, list[dict]] = {}
    for v in all_values:
        norm = _normalize_text(v.value)
        entry = {
            "dimension_name": v.dimension.name,
            "dimension_label": v.dimension.label,
            "dimension_id": v.dimension_id,
            "tag_value_id": v.id,
            "original_value": v.value,
        }
        normalized_map.setdefault(norm, []).append(entry)

    for name in unique_names:
        norm_name = _normalize_text(name)
        matches = normalized_map.get(norm_name, [])

        if len(matches) == 0:
            result.missing.append(name)
        elif len(matches) == 1:
            result.matched.append({
                "tag_name": name,
                **matches[0],
            })
        else:
            result.ambiguous.append({
                "tag_name": name,
                "dimensions": [
                    {
                        "dimension_id": m["dimension_id"],
                        "dimension_name": m["dimension_name"],
                        "dimension_label": m["dimension_label"],
                        "tag_value_id": m["tag_value_id"],
                        "original_value": m["original_value"],
                    }
                    for m in matches
                ],
            })

    return result


# ── 预览 ────────────────────────────────────────────────

def _get_mapping_value(mapping, key: str, default=None):
    """兼容 dict 和 Pydantic 模型的属性读取。"""
    if hasattr(mapping, key):
        return getattr(mapping, key)
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return default


def preview_files(
    db: Session,
    folder_path: str,
    tag_mapping: dict[str, dict],
) -> list[dict]:
    """预览即将入库的文件清单。"""
    files = scan_folder(folder_path)

    result: list[dict] = []
    for file_path in files:
        tags = extract_tags_from_path(file_path, folder_path)

        file_tags: list[dict] = []
        for tag in tags:
            mapping = tag_mapping.get(tag) or tag_mapping.get(_normalize_text(tag))
            if mapping:
                file_tags.append({
                    "dimension_id": _get_mapping_value(mapping, "dimension_id"),
                    "tag_value_id": _get_mapping_value(mapping, "tag_value_id"),
                    "dimension_name": _get_mapping_value(mapping, "dimension_name", ""),
                    "tag_value": _get_mapping_value(mapping, "original_value", tag),
                })

        result.append({
            "file_path": file_path,
            "file_name": Path(file_path).name,
            "tags": file_tags,
        })

    return result


# ── 标签匹配 ────────────────────────────────────────────

def _tags_match(
    db: Session,
    asset_id: int,
    tag_items: list[AssetTagItem],
) -> bool:
    """比较已有素材的标签与目标标签是否完全一致。

    比较维度：dimension_id + tag_value_id 的集合。
    """
    from app.asset.models import asset_tag_association as ata

    existing_rows = db.query(
        ata.c.dimension_id,
        ata.c.tag_value_id,
    ).filter(ata.c.asset_id == asset_id).all()
    existing_set = {(r.dimension_id, r.tag_value_id) for r in existing_rows}

    target_set = set()
    for item in tag_items:
        for tv_id in item.tag_value_ids:
            target_set.add((item.dimension_id, tv_id))

    return existing_set == target_set


# ── 执行入库 ────────────────────────────────────────────

def _build_file_tag_items(
    file_path: str,
    folder_path: str,
    tag_mapping: dict[str, dict],
    extra_tags: list[AssetTagItem],
) -> tuple[list[AssetTagItem], set[tuple[int, int]]]:
    """构建文件的标签项列表和目标标签集合。"""
    tags = extract_tags_from_path(file_path, folder_path)
    tag_items: list[AssetTagItem] = []
    used_dimensions: set[int] = set()

    for tag in tags:
        mapping = tag_mapping.get(tag) or tag_mapping.get(_normalize_text(tag))
        if not mapping:
            continue
        dim_id = _get_mapping_value(mapping, "dimension_id")
        tv_id = _get_mapping_value(mapping, "tag_value_id")
        if dim_id in used_dimensions:
            continue
        used_dimensions.add(dim_id)
        tag_items.append(AssetTagItem(dimension_id=dim_id, tag_value_ids=[tv_id]))

    for item in extra_tags:
        if item.dimension_id in used_dimensions:
            continue
        used_dimensions.add(item.dimension_id)
        tag_items.append(item)

    target_set: set[tuple[int, int]] = set()
    for item in tag_items:
        for tv_id in item.tag_value_ids:
            target_set.add((item.dimension_id, tv_id))

    return tag_items, target_set


def execute_folder_upload(
    db: Session,
    folder_path: str,
    tag_mapping: dict[str, dict],
    permission: AssetPermissionIn,
    extra_tags: list[AssetTagItem],
    uploader_id: int,
    copy: bool = False,
) -> dict:
    """执行文件夹批量上传（优化版）。

    优化点：
    1. 预加载查重字典 + 标签字典 + 版本号，消除 N+1 查询
    2. 内联入库逻辑，避免 create_asset/upload_new_version 内部逐文件 commit
    3. 每 BATCH_SIZE 个文件一个事务 + savepoint 隔离，减少 commit 开销
    """
    from sqlalchemy import func
    from app.asset.models import asset_tag_association as ata

    files = scan_folder(folder_path)
    total = len(files)
    if total == 0:
        return {"total": 0, "success": 0, "new_version_count": 0, "failed": []}

    # ── 1. 预加载：一次性消除循环内的所有查询 ──────────────
    file_names = [Path(f).name for f in files]

    # 1a. 批量查重（加载完整 ORM 对象，后续可直接修改字段）
    existing_assets = db.query(Asset).filter(Asset.file_name.in_(file_names)).all()
    existing_map: dict[tuple[str, str], Asset] = {
        (a.file_name, a.file_type): a for a in existing_assets
    }

    # 1b. 批量加载已有素材的标签
    existing_ids = [a.id for a in existing_assets]
    asset_tags_map: dict[int, set[tuple[int, int]]] = {}
    if existing_ids:
        tag_rows = db.execute(
            ata.select().where(ata.c.asset_id.in_(existing_ids))
        ).fetchall()
        for row in tag_rows:
            asset_tags_map.setdefault(row.asset_id, set()).add(
                (row.dimension_id, row.tag_value_id)
            )

    # 1c. 批量预计算版本号（避免循环内逐素材 SELECT MAX）
    version_numbers: dict[int, int] = {}
    for a in existing_assets:
        max_v = db.query(func.max(AssetVersion.version_number)).filter(
            AssetVersion.asset_id == a.id
        ).scalar() or 0
        version_numbers[a.id] = max_v

    # ── 2. 批量入库 ────────────────────────────────────────
    BATCH_SIZE = 20
    success = 0
    new_version_count = 0
    failed: list[dict] = []

    for i in range(0, total, BATCH_SIZE):
        batch = files[i : i + BATCH_SIZE]

        for file_path in batch:
            path = Path(file_path)
            file_name = path.name
            try:
                with db.begin_nested():
                    ext = path.suffix.lower().lstrip(".")
                    file_size = path.stat().st_size
                    file_type = _detect_file_type(ext)

                    tag_items, target_set = _build_file_tag_items(
                        file_path, folder_path, tag_mapping, extra_tags
                    )

                    existing = existing_map.get((file_name, file_type))
                    should_merge = (
                        existing is not None
                        and asset_tags_map.get(existing.id, set()) == target_set
                    )

                    if should_merge and existing:
                        # ── 新版本 ──
                        eid = existing.id
                        version_numbers[eid] += 1
                        ver_num = version_numbers[eid]

                        existing.status = "history"

                        rel_path = _build_storage_path(file_type, ext)
                        _save_upload_file(file_path, rel_path, copy=copy)

                        thumbnail_path: Optional[str] = None
                        abs_storage = str(ASSET_STORAGE_ROOT / rel_path)
                        if file_type == "image":
                            thumbnail_path = _generate_thumbnail(abs_storage, rel_path)
                        elif file_type == "video":
                            thumbnail_path = _generate_video_thumbnail(abs_storage, rel_path)

                        version = AssetVersion(
                            asset_id=eid,
                            version_number=ver_num,
                            storage_path=rel_path,
                            file_size=file_size,
                            uploader_id=uploader_id,
                        )
                        db.add(version)
                        db.flush()

                        existing.current_version_id = version.id
                        existing.status = "latest"
                        existing.file_name = file_name
                        existing.file_size = file_size
                        existing.storage_path = rel_path
                        existing.thumbnail_path = thumbnail_path

                        # 清除旧标签并写入新标签
                        db.execute(ata.delete().where(ata.c.asset_id == eid))
                        for item in tag_items:
                            for tv_id in item.tag_value_ids:
                                db.execute(
                                    ata.insert().values(
                                        asset_id=eid,
                                        version_id=version.id,
                                        dimension_id=item.dimension_id,
                                        tag_value_id=tv_id,
                                    )
                                )

                        new_version_count += 1
                        success += 1

                    else:
                        # ── 新素材 ──
                        rel_path = _build_storage_path(file_type, ext)
                        _save_upload_file(file_path, rel_path, copy=copy)

                        thumbnail_path: Optional[str] = None
                        abs_storage = str(ASSET_STORAGE_ROOT / rel_path)
                        if file_type == "image":
                            thumbnail_path = _generate_thumbnail(abs_storage, rel_path)
                        elif file_type == "video":
                            thumbnail_path = _generate_video_thumbnail(abs_storage, rel_path)

                        asset = Asset(
                            file_name=file_name,
                            file_type=file_type,
                            file_format=ext,
                            storage_path=rel_path,
                            file_size=file_size,
                            thumbnail_path=thumbnail_path,
                            uploader_id=uploader_id,
                            status="latest",
                        )
                        db.add(asset)
                        db.flush()

                        version = AssetVersion(
                            asset_id=asset.id,
                            version_number=1,
                            storage_path=rel_path,
                            file_size=file_size,
                            uploader_id=uploader_id,
                        )
                        db.add(version)
                        db.flush()

                        asset.current_version_id = version.id

                        for item in tag_items:
                            for tv_id in item.tag_value_ids:
                                db.execute(
                                    ata.insert().values(
                                        asset_id=asset.id,
                                        version_id=version.id,
                                        dimension_id=item.dimension_id,
                                        tag_value_id=tv_id,
                                    )
                                )

                        perm = AssetPermission(
                            asset_id=asset.id,
                            permission_group=permission.permission_group,
                            allow_preview=permission.allow_preview,
                            allow_download=permission.allow_download,
                            specified_user_ids=permission.specified_user_ids,
                        )
                        db.add(perm)

                        success += 1

            except Exception as exc:
                failed.append({"file_name": file_name, "reason": str(exc)})

        db.commit()

    return {
        "total": total,
        "success": success,
        "new_version_count": new_version_count,
        "failed": failed,
    }


# ── 异步执行 ──────────────────────────────────────────────

def start_folder_upload_async(
    db_session_factory,
    folder_path: str,
    tag_mapping: dict,
    permission: AssetPermissionIn,
    extra_tags: list,
    uploader_id: int,
) -> str:
    """启动异步文件夹上传，返回 job_id。"""
    job_id = str(uuid.uuid4())[:16]
    _folder_upload_jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "folder_path": folder_path,
    }

    def _run():
        db = db_session_factory()
        try:
            _folder_upload_jobs[job_id]["status"] = "running"
            report = execute_folder_upload(
                db, folder_path, tag_mapping, permission, extra_tags, uploader_id,
                copy=True,
            )
            _folder_upload_jobs[job_id].update({
                "status": "completed",
                "report": report,
                "finished_at": datetime.now().isoformat(),
            })
        except Exception as e:
            _folder_upload_jobs[job_id].update({
                "status": "failed",
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            })
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_folder_upload_job(job_id: str) -> Optional[dict]:
    """获取异步任务状态。"""
    job = _folder_upload_jobs.get(job_id)
    if not job:
        return None
    # 返回副本，避免外部修改
    return {
        "id": job["id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "finished_at": job.get("finished_at"),
        "report": job.get("report"),
        "error": job.get("error"),
    }
