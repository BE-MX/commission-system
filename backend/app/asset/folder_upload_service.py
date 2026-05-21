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
    create_asset,
    upload_new_version,
)
from app.asset.models import Asset, TagDimension, TagValue
from app.asset.schemas import AssetPermissionIn, AssetTagItem

# ── 配置 ────────────────────────────────────────────────

SUPPORTED_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".gif", ".bmp", ".tiff", ".tif",
}

SKIP_FILES = {".ds_store", "thumbs.db", "desktop.ini"}

# 系统保留维度名：文件夹名等于这些时跳过，不作为标签提取
RESERVED_DIMENSION_LABELS = {"素材类型", "状态", "版本", "日期", "权限组"}

# staging 根目录（从环境变量读取）
UPLOAD_STAGING_ROOT = os.environ.get("ASSET_UPLOAD_STAGING", r"D:\upload_staging")

# 异步执行文件数量阈值
ASYNC_FILE_THRESHOLD = 100

# 异步任务状态存储（内存中，重启后丢失）
_folder_upload_jobs: dict[str, dict] = {}


# ── 文本工具 ────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """文本规范化：NFKC（全角→半角）+ 小写 + 去首尾空格。"""
    text = unicodedata.normalize("NFKC", text)
    return text.lower().strip()


# ── 扫描与提取 ──────────────────────────────────────────

def scan_folder(folder_path: str) -> list[str]:
    """递归扫描文件夹，返回所有图片文件的绝对路径列表（按字母序）。"""
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
        if ext not in SUPPORTED_IMAGE_EXTS:
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


# ── 执行入库 ────────────────────────────────────────────

def execute_folder_upload(
    db: Session,
    folder_path: str,
    tag_mapping: dict[str, dict],
    permission: AssetPermissionIn,
    extra_tags: list[AssetTagItem],
    uploader_id: int,
    copy: bool = False,
) -> dict:
    """执行文件夹批量上传。

    对每文件：
    1. 提取路径标签 → 按 tag_mapping 转换 → 合并 extra_tags
    2. 按 file_name 检查是否已存在 → 存在则作为新版本
    3. 不存在则创建新素材

    返回执行报告。
    """
    files = scan_folder(folder_path)

    total = len(files)
    success = 0
    new_version_count = 0
    failed: list[dict] = []

    for file_path in files:
        path = Path(file_path)
        file_name = path.name
        ext = path.suffix.lower().lstrip(".")
        file_size = path.stat().st_size

        # 构建标签项
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
            tag_items.append(AssetTagItem(
                dimension_id=dim_id,
                tag_value_ids=[tv_id],
            ))

        # 追加额外标签
        for item in extra_tags:
            if item.dimension_id in used_dimensions:
                continue
            used_dimensions.add(item.dimension_id)
            tag_items.append(item)

        # 检查是否已存在（按 file_name + file_type='image' 匹配）
        existing = db.query(Asset).filter(
            Asset.file_name == file_name,
            Asset.file_type == "image",
        ).first()

        try:
            if existing:
                # 作为新版本上传
                version = upload_new_version(
                    db, existing.id, file_name, file_size,
                    str(path), uploader_id, remark=None, copy=copy,
                )
                if version:
                    # 新版本继承旧版标签后，再更新为用户指定的标签
                    from app.asset.asset_service import update_asset_tags
                    update_asset_tags(db, existing.id, tag_items)
                    new_version_count += 1
                    success += 1
                else:
                    failed.append({
                        "file_name": file_name,
                        "reason": "版本上传失败",
                    })
            else:
                # 创建新素材
                asset = create_asset(
                    db,
                    file_name=file_name,
                    file_type="image",
                    file_format=ext,
                    file_size=file_size,
                    temp_storage_path=str(path),
                    uploader_id=uploader_id,
                    tags=tag_items,
                    permission=permission,
                    remark=None,
                    copy=copy,
                )
                success += 1
        except Exception as exc:
            failed.append({
                "file_name": file_name,
                "reason": str(exc),
            })

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
