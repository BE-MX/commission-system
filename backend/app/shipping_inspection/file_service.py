"""发货检验 — 验货照片存储（私有目录 + 鉴权访问，模式照 app/domestic/file_service.py）

存储根：Settings.SHIPPING_INSPECTION_STORAGE_ROOT。存库一律相对路径；
读图走鉴权端点返回 FileResponse，不挂静态目录。
照片与视频分别校验，视频分块落盘并限制大小；二者都只通过鉴权端点读取。
"""

import uuid
import logging
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("commission")
VIDEO_MAX_BYTES = 100 * 1024 * 1024
VIDEO_MIMES = {".mp4": {"video/mp4"}, ".mov": {"video/quicktime"}, ".m4v": {"video/mp4", "video/x-m4v"}}

# 后缀 → (大小上限 MB, 允许的 MIME)
UPLOAD_LIMITS: dict[str, tuple[int, set[str]]] = {
    ".jpg": (20, {"image/jpeg"}),
    ".jpeg": (20, {"image/jpeg"}),
    ".png": (20, {"image/png"}),
    ".webp": (20, {"image/webp"}),
}


class FileValidationError(ValueError):
    pass


def storage_root() -> Path:
    root = Path(get_settings().SHIPPING_INSPECTION_STORAGE_ROOT)
    return root if root.is_absolute() else Path(__file__).resolve().parents[3] / root


def remove_file(rel_path: str) -> None:
    try:
        resolve_path(rel_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("清理验货媒体失败 path=%s: %s", rel_path, exc)
        print(f"[shipping_inspection] 清理媒体失败 path={rel_path}: {exc}", flush=True)


async def store_video(upload) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in VIDEO_MIMES:
        raise FileValidationError("视频仅支持 MP4、MOV、M4V")
    mime = (upload.content_type or "").lower()
    if mime and mime not in VIDEO_MIMES[ext] | {"application/octet-stream"}:
        raise FileValidationError("视频类型与后缀不匹配")
    if upload.size is not None and upload.size > VIDEO_MAX_BYTES:
        raise FileValidationError("视频不能超过 100MB")
    name = uuid.uuid4().hex + ext
    rel_path = f"{name[:2]}/{name}"
    target = resolve_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        first = await upload.read(1024 * 1024)
        # ISO BMFF/QuickTime 文件头；拒绝仅更改扩展名的非视频文件。
        if len(first) < 12 or first[4:8] not in {b"ftyp", b"moov", b"mdat", b"wide"}:
            raise FileValidationError("无法识别视频文件，请从相册重新选择")
        total = 0
        with target.open("wb") as stream:
            chunk = first
            while chunk:
                total += len(chunk)
                if total > VIDEO_MAX_BYTES:
                    raise FileValidationError("视频不能超过 100MB")
                stream.write(chunk)
                chunk = await upload.read(1024 * 1024)
    except BaseException:
        remove_file(rel_path)
        raise
    return rel_path


def validate_upload(filename: str, mime_type: str, file_size: int) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in UPLOAD_LIMITS:
        raise FileValidationError(f"只支持图片：{' '.join(sorted(UPLOAD_LIMITS))}")
    max_mb, mimes = UPLOAD_LIMITS[ext]
    if file_size > max_mb * 1024 * 1024:
        raise FileValidationError(f"图片不能超过 {max_mb}MB")
    if mimes and mime_type and mime_type not in mimes:
        raise FileValidationError(f"文件内容类型 {mime_type} 与后缀 {ext} 不匹配")
    return ext


def store_bytes(original_filename: str, content: bytes) -> str:
    """落盘，uuid 命名 + 前两位散列子目录，返回相对路径。"""
    ext = Path(original_filename or "").suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    rel = Path(name[:2]) / name
    abs_path = storage_root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return rel.as_posix()


def resolve_path(rel_path: str) -> Path:
    """相对路径 → 绝对路径，挡住 ../ 穿越（is_relative_to，与 domestic 同一写法）。"""
    root = storage_root().resolve()
    target = (root / (rel_path or "")).resolve()
    if not target.is_relative_to(root):
        raise FileValidationError("非法的图片路径")
    return target
