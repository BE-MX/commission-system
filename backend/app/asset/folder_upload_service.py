"""素材管理 — 文件夹批量上传服务

流程：扫描文件夹 → 提取候选标签 → 校验标签库匹配 → 预览 → 执行入库
"""

import json
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Optional

from sqlalchemy import bindparam, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.asset.asset_service import (
    ASSET_STORAGE_ROOT,
    _build_storage_path,
    _compute_orientation,
    _generate_thumbnail,
    _generate_video_thumbnail,
    _save_upload_file,
)
from app.asset.color_rules import sync_color_family
from app.asset.models import Asset, AssetPermission, AssetVersion, TagDimension, TagValue
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
from app.core.config import get_settings

UPLOAD_STAGING_ROOT = get_settings().ASSET_UPLOAD_STAGING

# 异步执行文件数量阈值
ASYNC_FILE_THRESHOLD = 20

# 浏览器直传限制。分块保持在常见 5MB 网关限制内，清单限制避免临时盘被单次请求打满。
DIRECT_UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
DIRECT_UPLOAD_MAX_FILE_BYTES = 500 * 1024 * 1024
DIRECT_UPLOAD_MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024
DIRECT_UPLOAD_MAX_FILES = 2000
DIRECT_UPLOAD_MAX_DEPTH = 20
DIRECT_UPLOAD_MAX_PATH_LENGTH = 1024
DIRECT_UPLOAD_SESSION_FILE = ".upload-session.json"
DIRECT_UPLOAD_INGEST_FILE = ".ingest-active"

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


def _safe_relative_upload_path(relative_path: str) -> PurePosixPath:
    """校验浏览器相对路径，阻止绝对路径和目录穿越。"""
    normalized = relative_path.replace("\\", "/").strip("/")
    rel = PurePosixPath(normalized)
    if (
        not normalized
        or rel.is_absolute()
        or any(part in {"", ".", ".."} for part in rel.parts)
        or any(":" in part for part in rel.parts)
    ):
        raise ValueError(f"无效的文件相对路径: {relative_path}")
    if rel.suffix.lower() not in SUPPORTED_FILE_EXTS:
        raise ValueError(f"不支持的文件类型: {rel.name}")
    if len(normalized) > DIRECT_UPLOAD_MAX_PATH_LENGTH:
        raise ValueError(f"文件相对路径超过 {DIRECT_UPLOAD_MAX_PATH_LENGTH} 个字符: {rel.name}")
    if len(rel.parts) > DIRECT_UPLOAD_MAX_DEPTH:
        raise ValueError(f"文件夹层级超过 {DIRECT_UPLOAD_MAX_DEPTH} 层: {rel.name}")
    return rel


def validate_direct_upload_manifest(
    relative_paths: list[str],
    file_sizes: list[int],
) -> list[str]:
    """校验浏览器上传清单并返回规范化路径。"""
    if len(relative_paths) != len(file_sizes):
        raise ValueError("上传文件数量与大小清单不一致")
    if not relative_paths:
        raise ValueError("上传清单不能为空")
    if len(relative_paths) > DIRECT_UPLOAD_MAX_FILES:
        raise ValueError(f"单次最多上传 {DIRECT_UPLOAD_MAX_FILES} 个文件")

    normalized_paths = [str(_safe_relative_upload_path(path)) for path in relative_paths]
    path_keys = [_normalize_text(path) for path in normalized_paths]
    if len(path_keys) != len(set(path_keys)):
        raise ValueError("上传路径清单中存在重复文件")

    total_size = 0
    for relative_path, file_size in zip(normalized_paths, file_sizes):
        if file_size < 0:
            raise ValueError(f"文件大小无效: {relative_path}")
        if file_size > DIRECT_UPLOAD_MAX_FILE_BYTES:
            raise ValueError(f"文件超过 500MB 限制: {PurePosixPath(relative_path).name}")
        total_size += file_size
    if total_size > DIRECT_UPLOAD_MAX_TOTAL_BYTES:
        raise ValueError("单次文件夹上传总大小不能超过 20GB")
    return normalized_paths


def _direct_upload_root(upload_id: str) -> Path:
    """解析并约束浏览器直传会话目录。"""
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise ValueError("上传会话 ID 无效")
    staging_root = Path(UPLOAD_STAGING_ROOT).resolve()
    target = (staging_root / f".web-upload-{upload_id}").resolve()
    if target.parent != staging_root:
        raise ValueError("上传会话目录不合法")
    return target


def cleanup_stale_direct_upload_sessions(max_age_hours: int = 24) -> None:
    """回收浏览器中断后遗留的未完成会话，不触碰已进入异步入库的目录。"""
    staging_root = Path(UPLOAD_STAGING_ROOT).resolve()
    if not staging_root.is_dir():
        return
    cutoff = time.time() - max_age_hours * 3600
    for batch_root in staging_root.glob(".web-upload-*"):
        activity_files = [
            batch_root / DIRECT_UPLOAD_SESSION_FILE,
            batch_root / DIRECT_UPLOAD_INGEST_FILE,
        ]
        try:
            active_file = next((path for path in activity_files if path.is_file()), None)
            if active_file and active_file.stat().st_mtime < cutoff:
                cleanup_direct_upload_root(batch_root)
        except OSError:
            continue


def create_direct_upload_session(
    relative_paths: list[str],
    file_sizes: list[int],
    uploader_id: int,
    payload: dict,
) -> tuple[str, Path]:
    """创建可分块上传的受控会话，元数据落盘以支持进程重启后的重试。"""
    normalized_paths = validate_direct_upload_manifest(relative_paths, file_sizes)
    staging_root = Path(UPLOAD_STAGING_ROOT).resolve()
    staging_root.mkdir(parents=True, exist_ok=True)
    cleanup_stale_direct_upload_sessions()
    upload_id = uuid.uuid4().hex
    batch_root = _direct_upload_root(upload_id)
    batch_root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "upload_id": upload_id,
        "uploader_id": uploader_id,
        "relative_paths": normalized_paths,
        "file_sizes": file_sizes,
        "payload": payload,
        "created_at": datetime.now().isoformat(),
    }
    (batch_root / DIRECT_UPLOAD_SESSION_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return upload_id, batch_root


def load_direct_upload_session(upload_id: str, uploader_id: int) -> tuple[Path, dict]:
    """读取上传会话，并校验当前用户是会话创建者。"""
    batch_root = _direct_upload_root(upload_id)
    manifest_path = batch_root / DIRECT_UPLOAD_SESSION_FILE
    if not manifest_path.is_file():
        raise ValueError("上传会话不存在或已结束")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("上传会话数据损坏，请重新选择文件夹") from exc
    if int(manifest.get("uploader_id") or 0) != uploader_id:
        raise ValueError("无权使用该上传会话")
    return batch_root, manifest


def save_direct_upload_chunk(
    upload_id: str,
    uploader_id: int,
    relative_path: str,
    chunk_index: int,
    total_chunks: int,
    upload,
) -> dict:
    """保存一个不超过 4MB 的文件块；块按路径隔离，可安全重传。"""
    batch_root, manifest = load_direct_upload_session(upload_id, uploader_id)
    normalized = str(_safe_relative_upload_path(relative_path))
    try:
        file_index = manifest["relative_paths"].index(normalized)
    except ValueError as exc:
        raise ValueError("文件不在当前上传清单中") from exc
    file_size = int(manifest["file_sizes"][file_index])
    expected_chunks = max(1, (file_size + DIRECT_UPLOAD_CHUNK_BYTES - 1) // DIRECT_UPLOAD_CHUNK_BYTES)
    if total_chunks != expected_chunks or chunk_index < 0 or chunk_index >= expected_chunks:
        raise ValueError("文件分块参数无效")

    expected_size = min(
        DIRECT_UPLOAD_CHUNK_BYTES,
        max(0, file_size - chunk_index * DIRECT_UPLOAD_CHUNK_BYTES),
    )
    chunk = upload.file.read(DIRECT_UPLOAD_CHUNK_BYTES + 1)
    if len(chunk) != expected_size:
        raise ValueError(f"文件块大小不一致: {PurePosixPath(normalized).name}")

    rel = PurePosixPath(normalized)
    chunk_dir = batch_root / ".chunks" / Path(*rel.parts)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    target = chunk_dir / f"{chunk_index:04d}.part"
    temp_target = chunk_dir / f"{chunk_index:04d}.tmp"
    temp_target.write_bytes(chunk)
    temp_target.replace(target)
    # 清理器以 manifest 活跃时间判断过期；长时间上传期间持续续期，避免误删。
    os.utime(batch_root / DIRECT_UPLOAD_SESSION_FILE, None)
    return {
        "relative_path": normalized,
        "chunk_index": chunk_index,
        "uploaded_bytes": expected_size,
    }


def finalize_direct_upload_session(upload_id: str, uploader_id: int) -> tuple[Path, dict]:
    """验证所有文件块后组装文件，返回可复用既有入库流程的暂存目录。"""
    batch_root, manifest = load_direct_upload_session(upload_id, uploader_id)
    plans: list[tuple[PurePosixPath, list[Path], int]] = []
    for relative_path, file_size in zip(manifest["relative_paths"], manifest["file_sizes"]):
        rel = PurePosixPath(relative_path)
        chunk_count = max(1, (file_size + DIRECT_UPLOAD_CHUNK_BYTES - 1) // DIRECT_UPLOAD_CHUNK_BYTES)
        chunk_dir = batch_root / ".chunks" / Path(*rel.parts)
        chunks = [chunk_dir / f"{index:04d}.part" for index in range(chunk_count)]
        if any(not chunk.is_file() for chunk in chunks):
            raise ValueError(f"文件尚未上传完整: {rel.name}")
        if sum(chunk.stat().st_size for chunk in chunks) != file_size:
            raise ValueError(f"文件大小校验失败: {rel.name}")
        plans.append((rel, chunks, file_size))

    for rel, chunks, file_size in plans:
        target = (batch_root / Path(*rel.parts)).resolve()
        if not target.is_relative_to(batch_root):
            raise ValueError(f"文件路径越界: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            for chunk in chunks:
                with chunk.open("rb") as source:
                    shutil.copyfileobj(source, output)
        if target.stat().st_size != file_size:
            raise ValueError(f"文件组装失败: {rel.name}")

    shutil.rmtree(batch_root / ".chunks", ignore_errors=True)
    (batch_root / DIRECT_UPLOAD_INGEST_FILE).touch()
    (batch_root / DIRECT_UPLOAD_SESSION_FILE).unlink(missing_ok=True)
    return batch_root, manifest


def cleanup_direct_upload_root(folder_path: str | Path) -> None:
    """仅清理浏览器直传创建的受控临时目录。"""
    staging_root = Path(UPLOAD_STAGING_ROOT).resolve()
    target = Path(folder_path).resolve()
    if (
        target.parent == staging_root
        and target.name.startswith(".web-upload-")
        and target.is_dir()
    ):
        shutil.rmtree(target, ignore_errors=True)


def _filename_tag(file_name: str) -> str:
    """文件名候选标签：只移除最后一个扩展名，保留名称中的其他点号。"""
    return Path(file_name).stem.strip()


def extract_tags_from_relative_path(
    relative_path: str,
    include_filename_tag: bool = False,
) -> list[str]:
    """从浏览器提供的相对路径提取文件夹名和可选文件名标签。"""
    rel = PurePosixPath(relative_path.replace("\\", "/"))
    reserved_norm = {_normalize_text(label) for label in RESERVED_DIMENSION_LABELS}
    tags: list[str] = []

    for part in rel.parent.parts:
        normalized = _normalize_text(part)
        if not normalized or normalized in reserved_norm or part in {".", ".."}:
            continue
        tags.append(part)

    if include_filename_tag:
        file_tag = _filename_tag(rel.name)
        if file_tag:
            tags.append(file_tag)
    return tags


def extract_tags_from_path(
    file_path: str,
    root_path: str,
    include_filename_tag: bool = False,
    include_root_name: bool = True,
) -> list[str]:
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

    # 所选文件夹本身的名称也作为标签；浏览器直传的临时根目录除外
    if include_root_name:
        root_name = root_p.name
        norm_root = _normalize_text(root_name)
        if norm_root and norm_root not in reserved_norm:
            tags.append(root_name)

    for part in rel.parent.parts:
        normalized = _normalize_text(part)
        if not normalized or normalized in reserved_norm:
            continue
        tags.append(part)

    if include_filename_tag:
        file_tag = _filename_tag(rel.name)
        if file_tag:
            tags.append(file_tag)

    return tags


# ── 标签校验 ────────────────────────────────────────────

@dataclass
class TagValidationResult:
    matched: list[dict] = field(default_factory=list)
    suggested: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return (
            len(self.suggested) == 0
            and len(self.missing) == 0
            and len(self.ambiguous) == 0
        )


SIMILARITY_THRESHOLD = 0.58


def _similarity_score(source: str, candidate: str) -> float:
    """关键词友好的相似度：兼顾错别字、分隔符和长文件名包含短标签。"""
    source_norm = _normalize_text(source)
    candidate_norm = _normalize_text(candidate)
    source_compact = re.sub(r"[\W_]+", "", source_norm, flags=re.UNICODE)
    candidate_compact = re.sub(r"[\W_]+", "", candidate_norm, flags=re.UNICODE)
    if not source_compact or not candidate_compact:
        return 0.0
    if source_compact == candidate_compact:
        return 1.0

    score = SequenceMatcher(None, source_compact, candidate_compact).ratio()
    shorter, longer = sorted((source_compact, candidate_compact), key=len)
    if len(shorter) >= 2 and shorter in longer:
        containment = min(0.95, 0.72 + 0.23 * len(shorter) / len(longer))
        score = max(score, containment)

    source_tokens = {token for token in re.split(r"[\W_]+", source_norm) if token}
    candidate_tokens = {token for token in re.split(r"[\W_]+", candidate_norm) if token}
    if source_tokens and candidate_tokens:
        overlap = len(source_tokens & candidate_tokens) / len(source_tokens | candidate_tokens)
        score = max(score, overlap)
    return round(score, 4)


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

    # 只加载可见且非托管维度的活跃标签值：并存期新旧体系同名值共存，
    # 若不限维度会全员歧义（is_visible 是体系切换的执行机制）；
    # 托管维度（色系）由派生脚本独占写入，文件夹名不允许匹配进去
    from app.asset.models import TagDimension

    all_values = (
        db.query(TagValue)
        .join(TagDimension, TagDimension.id == TagValue.dimension_id)
        .filter(TagValue.is_active == 1, TagDimension.is_visible == 1,
                TagDimension.is_managed == 0)
        .all()
    )

    # 规范化值 -> [匹配记录]；value / name_en / aliases 三路进索引
    normalized_map: dict[str, list[dict]] = {}
    similarity_candidates: list[tuple[str, dict]] = []
    for v in all_values:
        entry = {
            "dimension_name": v.dimension.name,
            "dimension_label": v.dimension.label,
            "dimension_id": v.dimension_id,
            "tag_value_id": v.id,
            "original_value": v.value,
        }
        candidates = [v.value]
        if v.name_en:
            candidates.append(v.name_en)
        if v.aliases:
            candidates.extend(a for a in v.aliases if isinstance(a, str))
        for cand in candidates:
            norm = _normalize_text(cand)
            bucket = normalized_map.setdefault(norm, [])
            if not any(e["tag_value_id"] == entry["tag_value_id"] for e in bucket):
                bucket.append(entry)
            similarity_candidates.append((cand, entry))

    for name in unique_names:
        norm_name = _normalize_text(name)
        matches = normalized_map.get(norm_name, [])

        if len(matches) == 0:
            best_by_value: dict[int, dict] = {}
            for candidate_text, entry in similarity_candidates:
                score = _similarity_score(name, candidate_text)
                current = best_by_value.get(entry["tag_value_id"])
                if score >= SIMILARITY_THRESHOLD and (
                    current is None or score > current["score"]
                ):
                    best_by_value[entry["tag_value_id"]] = {
                        **entry,
                        "score": score,
                        "matched_keyword": candidate_text,
                    }
            ranked = sorted(
                best_by_value.values(),
                key=lambda item: (-item["score"], item["original_value"]),
            )[:3]
            if ranked:
                result.suggested.append({
                    "tag_name": name,
                    "recommended": ranked[0],
                    "alternatives": ranked,
                })
            else:
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
    include_filename_tags: bool = False,
    include_root_name: bool = True,
) -> list[dict]:
    """预览即将入库的文件清单。"""
    files = scan_folder(folder_path)

    result: list[dict] = []
    for file_path in files:
        tags = extract_tags_from_path(
            file_path,
            folder_path,
            include_filename_tag=include_filename_tags,
            include_root_name=include_root_name,
        )

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


def preview_manifest_files(
    relative_paths: list[str],
    tag_mapping: dict[str, dict],
    include_filename_tags: bool = False,
) -> list[dict]:
    """无需上传文件本体，根据浏览器文件清单生成确认预览。"""
    result: list[dict] = []
    for relative_path in relative_paths:
        tags = extract_tags_from_relative_path(relative_path, include_filename_tags)
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
            "file_path": relative_path,
            "file_name": PurePosixPath(relative_path.replace("\\", "/")).name,
            "tags": file_tags,
        })
    return result


# ── 标签匹配 ────────────────────────────────────────────

def _comparable_dim_ids(db: Session) -> set[int]:
    """合并判定可比较的维度：可见且非托管。

    存量重打标/派生脚本给素材追加的隐藏维度或托管维度（色系）标签不在
    路径映射的目标集里，若做全维度比较，重传同一文件夹会把所有同名文件
    误判为新素材、批量建重。
    """
    from app.asset.models import TagDimension

    return {
        d.id for d in db.query(TagDimension)
        .filter(TagDimension.is_visible == 1, TagDimension.is_managed == 0)
    }


def _tags_match(
    existing_tags: set[tuple[int, int]],
    target_set: set[tuple[int, int]],
    comparable_dims: set[int],
) -> bool:
    """判定「同名文件是否视为同一素材」：目标标签 ⊆ 已有素材的可比较维度标签。

    子集语义的代价：同名但标签更少的不同文件可能被误并为新版本
    （相机文件名跨拍摄批次复用时），版本历史可回溯，风险可接受。
    """
    existing_cmp = {t for t in existing_tags if t[0] in comparable_dims}
    target_cmp = {t for t in target_set if t[0] in comparable_dims}
    return bool(target_cmp) and target_cmp <= existing_cmp


# ── 执行入库 ────────────────────────────────────────────

def _build_file_tag_items(
    file_path: str,
    folder_path: str,
    tag_mapping: dict[str, dict],
    extra_tags: list[AssetTagItem],
    single_select_dims: Optional[set[int]] = None,
    include_filename_tags: bool = False,
    include_root_name: bool = True,
) -> tuple[list[AssetTagItem], set[tuple[int, int]]]:
    """构建文件的标签项列表和目标标签集合。"""
    tags = extract_tags_from_path(
        file_path,
        folder_path,
        include_filename_tag=include_filename_tags,
        include_root_name=include_root_name,
    )
    values_by_dimension: dict[int, list[int]] = {}
    single_select_dims = single_select_dims or set()

    for tag in tags:
        mapping = tag_mapping.get(tag) or tag_mapping.get(_normalize_text(tag))
        if not mapping:
            continue
        dim_id = _get_mapping_value(mapping, "dimension_id")
        tv_id = _get_mapping_value(mapping, "tag_value_id")
        values = values_by_dimension.setdefault(dim_id, [])
        if dim_id in single_select_dims and values:
            continue
        if tv_id not in values:
            values.append(tv_id)

    for item in extra_tags:
        values = values_by_dimension.setdefault(item.dimension_id, [])
        for tv_id in item.tag_value_ids:
            if item.dimension_id in single_select_dims and values:
                break
            if tv_id not in values:
                values.append(tv_id)

    tag_items = [
        AssetTagItem(dimension_id=dimension_id, tag_value_ids=value_ids)
        for dimension_id, value_ids in values_by_dimension.items()
    ]

    target_set: set[tuple[int, int]] = set()
    for item in tag_items:
        for tv_id in item.tag_value_ids:
            target_set.add((item.dimension_id, tv_id))

    return tag_items, target_set


def _resolve_auto_create_tags(
    db: Session,
    tag_mapping: dict[str, dict],
    auto_create_tags: dict[str, int],
) -> tuple[dict[str, dict], list[dict]]:
    """在上传事务内创建缺失标签，并补齐路径映射。"""
    if not auto_create_tags:
        return dict(tag_mapping), []

    resolved = dict(tag_mapping)
    created: list[dict] = []
    dimension_ids = set(auto_create_tags.values())
    dimensions = {
        dim.id: dim
        for dim in db.query(TagDimension).filter(TagDimension.id.in_(dimension_ids)).all()
    }

    for tag_name, dimension_id in auto_create_tags.items():
        clean_name = tag_name.strip()
        dim = dimensions.get(dimension_id)
        if not clean_name:
            raise ValueError("自动创建的标签名不能为空")
        if len(clean_name) > 128:
            raise ValueError(f"标签[{clean_name[:20]}…]超过 128 个字符，不能自动创建")
        if not dim or not dim.is_visible:
            raise ValueError(f"标签[{clean_name}]选择的维度不存在或不可见")
        if dim.is_managed:
            raise ValueError(f"维度[{dim.label}]由系统维护，不能自动创建标签")

        existing = (
            db.query(TagValue)
            .filter(
                TagValue.dimension_id == dimension_id,
                func.lower(TagValue.value) == clean_name.lower(),
            )
            .first()
        )
        if existing and not existing.is_active:
            raise ValueError(f"标签[{clean_name}]已存在但已停用，请联系管理员启用")
        if existing:
            tag_value = existing
        else:
            try:
                with db.begin_nested():
                    tag_value = TagValue(
                        dimension_id=dimension_id,
                        value=clean_name,
                        sort_order=0,
                        is_active=1,
                    )
                    db.add(tag_value)
                    db.flush()
            except IntegrityError:
                # 并发上传可能同时创建同一标签；唯一索引裁决后复用胜者。
                tag_value = (
                    db.query(TagValue)
                    .filter(
                        TagValue.dimension_id == dimension_id,
                        func.lower(TagValue.value) == clean_name.lower(),
                        TagValue.is_active == 1,
                    )
                    .with_for_update()
                    .first()
                )
                if not tag_value:
                    raise
            else:
                created.append({
                    "dimension_id": dimension_id,
                    "dimension_name": dim.label,
                    "tag_value_id": tag_value.id,
                    "tag_value": clean_name,
                })

        resolved[tag_name] = {
            "dimension_id": dimension_id,
            "dimension_name": dim.label,
            "tag_value_id": tag_value.id,
            "original_value": tag_value.value,
        }

    return resolved, created


def execute_folder_upload(
    db: Session,
    folder_path: str,
    tag_mapping: dict[str, dict],
    permission: AssetPermissionIn,
    extra_tags: list[AssetTagItem],
    uploader_id: int,
    copy: bool = False,
    update_duplicates: bool = True,
    include_filename_tags: bool = False,
    include_root_name: bool = True,
    auto_create_tags: Optional[dict[str, int]] = None,
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
        return {"total": 0, "success": 0, "new_version_count": 0, "skipped": 0, "failed": []}

    tag_mapping, created_tags = _resolve_auto_create_tags(
        db, tag_mapping, auto_create_tags or {},
    )

    # ── 1. 预加载：一次性消除循环内的所有查询 ──────────────
    file_names = [Path(f).name for f in files]
    print(f"[folder-upload] preload: scanning {total} files, looking up existing assets", flush=True)

    # 1a. 批量查重（加载完整 ORM 对象，后续可直接修改字段）
    existing_assets = db.query(Asset).filter(Asset.file_name.in_(file_names)).all()
    existing_map: dict[tuple[str, str], Asset] = {
        (a.file_name, a.file_type): a for a in existing_assets
    }
    print(f"[folder-upload] preload: matched {len(existing_assets)} existing assets", flush=True)

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
        print(f"[folder-upload] preload: loaded {len(tag_rows)} tag rows", flush=True)

    # 1c. 批量预计算版本号（避免循环内逐素材 SELECT MAX）
    # 仅在需要写新版本时执行；update_duplicates=False 模式下纯跳过,完全用不到
    version_numbers: dict[int, int] = {}
    if update_duplicates and existing_ids:
        ver_rows = db.execute(
            text("""
                SELECT asset_id, MAX(version_number) AS max_v
                FROM ark_asset_versions
                WHERE asset_id IN :ids
                GROUP BY asset_id
            """).bindparams(bindparam("ids", expanding=True)),
            {"ids": existing_ids},
        ).fetchall()
        version_numbers = {r.asset_id: int(r.max_v or 0) for r in ver_rows}
        print(f"[folder-upload] preload: loaded version numbers for {len(version_numbers)} assets", flush=True)

    # 1d. 合并判定只看可见非托管维度（详见 _comparable_dim_ids docstring）
    comparable_dims = _comparable_dim_ids(db)
    single_select_dims = {
        dim.id for dim in db.query(TagDimension)
        .filter(TagDimension.is_single_select == 1)
        .all()
    }
    print(f"[folder-upload] preload done, start ingesting", flush=True)

    # ── 2. 批量入库 ────────────────────────────────────────
    BATCH_SIZE = 20
    success = 0
    new_version_count = 0
    skipped = 0
    failed: list[dict] = []
    created_tag_cache_invalidated = False
    ingest_marker = Path(folder_path) / DIRECT_UPLOAD_INGEST_FILE

    for i in range(0, total, BATCH_SIZE):
        batch = files[i : i + BATCH_SIZE]
        if i % 200 == 0:
            print(f"[folder-upload] progress {i}/{total} success={success} skipped={skipped} new_version={new_version_count} failed={len(failed)}", flush=True)

        for file_path in batch:
            path = Path(file_path)
            file_name = path.name
            try:
                with db.begin_nested():
                    ext = path.suffix.lower().lstrip(".")
                    file_size = path.stat().st_size
                    file_type = _detect_file_type(ext)

                    tag_items, target_set = _build_file_tag_items(
                        file_path,
                        folder_path,
                        tag_mapping,
                        extra_tags,
                        single_select_dims=single_select_dims,
                        include_filename_tags=include_filename_tags,
                        include_root_name=include_root_name,
                    )

                    existing = existing_map.get((file_name, file_type))
                    should_merge = (
                        existing is not None
                        and _tags_match(
                            asset_tags_map.get(existing.id, set()),
                            target_set, comparable_dims,
                        )
                    )

                    if should_merge and not update_duplicates:
                        # 关闭"更新为新版本"开关 → 同名同标签直接跳过
                        skipped += 1
                        continue

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
                        existing.orientation = _compute_orientation(abs_storage, file_type)

                        # 按维度合并：只清目标涉及的维度，重打标/派生脚本
                        # 写入的其他维度标签（隐藏体系、色系）保留
                        touched_dims = list({item.dimension_id for item in tag_items})
                        if touched_dims:
                            db.execute(ata.delete().where(
                                ata.c.asset_id == eid,
                                ata.c.dimension_id.in_(touched_dims),
                            ))
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
                        sync_color_family(db, eid, version.id)

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
                            orientation=_compute_orientation(abs_storage, file_type),
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

                        sync_color_family(db, asset.id, version.id)

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
                import traceback
                err = f"{type(exc).__name__}: {exc}"
                failed.append({"file_name": file_name, "reason": err})
                # 打到 stderr,确保 uvicorn 控制台 / NSSM 日志能看到
                print(f"[folder-upload] FAIL file={file_name} err={err}", flush=True)
                traceback.print_exc()

        db.commit()
        if ingest_marker.is_file():
            os.utime(ingest_marker, None)
        if created_tags and not created_tag_cache_invalidated:
            from app.asset.tag_service import invalidate_dim_cache
            invalidate_dim_cache()
            created_tag_cache_invalidated = True

    if created_tags and success == 0:
        # 所有文件均失败时不留下孤立标签；标签创建本身不应成为失败上传的副作用。
        created_ids = [item["tag_value_id"] for item in created_tags]
        used_ids = {
            row.tag_value_id for row in db.execute(
                ata.select().where(ata.c.tag_value_id.in_(created_ids))
            ).fetchall()
        }
        removable_ids = [tag_id for tag_id in created_ids if tag_id not in used_ids]
        if removable_ids:
            db.query(TagValue).filter(TagValue.id.in_(removable_ids)).delete(
                synchronize_session=False,
            )
            db.commit()
            created_tags = [
                item for item in created_tags if item["tag_value_id"] not in removable_ids
            ]

    if created_tags or created_tag_cache_invalidated:
        from app.asset.tag_service import invalidate_dim_cache
        invalidate_dim_cache()

    return {
        "total": total,
        "success": success,
        "new_version_count": new_version_count,
        "skipped": skipped,
        "failed": failed,
        "created_tags": created_tags,
    }


# ── 异步执行 ──────────────────────────────────────────────

def start_folder_upload_async(
    db_session_factory,
    folder_path: str,
    tag_mapping: dict,
    permission: AssetPermissionIn,
    extra_tags: list,
    uploader_id: int,
    update_duplicates: bool = True,
    copy: bool = True,
    include_filename_tags: bool = False,
    include_root_name: bool = True,
    auto_create_tags: Optional[dict[str, int]] = None,
    cleanup_dir: Optional[str] = None,
) -> str:
    """启动异步文件夹上传，返回 job_id。"""
    import logging
    logger = logging.getLogger("asset.folder_upload")

    job_id = str(uuid.uuid4())[:16]
    _folder_upload_jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "folder_path": folder_path,
        "uploader_id": uploader_id,
    }

    def _run():
        db = db_session_factory()
        try:
            _folder_upload_jobs[job_id]["status"] = "running"
            print(f"[folder-upload {job_id}] START path={folder_path} update_duplicates={update_duplicates}", flush=True)
            logger.info("[folder-upload %s] start path=%s update_duplicates=%s",
                        job_id, folder_path, update_duplicates)
            report = execute_folder_upload(
                db, folder_path, tag_mapping, permission, extra_tags, uploader_id,
                copy=copy,
                update_duplicates=update_duplicates,
                include_filename_tags=include_filename_tags,
                include_root_name=include_root_name,
                auto_create_tags=auto_create_tags,
            )
            print(f"[folder-upload {job_id}] DONE report={report}", flush=True)
            logger.info("[folder-upload %s] done report=%s", job_id, report)
            _folder_upload_jobs[job_id].update({
                "status": "completed",
                "report": report,
                "finished_at": datetime.now().isoformat(),
            })
        except Exception as e:
            import traceback
            print(f"[folder-upload {job_id}] FAILED err={e}", flush=True)
            traceback.print_exc()
            logger.exception("[folder-upload %s] failed", job_id)
            _folder_upload_jobs[job_id].update({
                "status": "failed",
                "error": str(e),
                "finished_at": datetime.now().isoformat(),
            })
        finally:
            db.close()
            if cleanup_dir:
                cleanup_direct_upload_root(cleanup_dir)

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def get_folder_upload_job(job_id: str, uploader_id: int) -> Optional[dict]:
    """获取当前上传者自己的异步任务状态。"""
    job = _folder_upload_jobs.get(job_id)
    if not job or int(job.get("uploader_id") or 0) != uploader_id:
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
