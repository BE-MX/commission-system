"""培训速递 — 附件存储（私有目录 + 鉴权下载，模式照 app/aftersales/file_service.py）

存储根：Settings.TRAINING_STORAGE_ROOT（默认 D:\\WORKSOURCE\\training）。
存库一律相对路径；下载走 FileResponse 鉴权端点，不走 /uploads 静态挂载。
"""

import uuid
from pathlib import Path

from app.core.config import get_settings

# 后缀 → (大小上限 MB, 允许的 MIME 前缀集合；空集 = 不校验 MIME)
UPLOAD_LIMITS: dict[str, tuple[int, set[str]]] = {
    ".jpg": (20, {"image/jpeg"}),
    ".jpeg": (20, {"image/jpeg"}),
    ".png": (20, {"image/png"}),
    ".webp": (20, {"image/webp"}),
    ".pdf": (60, {"application/pdf"}),
    ".ppt": (100, set()),
    ".pptx": (100, set()),
    ".doc": (60, set()),
    ".docx": (60, set()),
    ".xls": (60, set()),
    ".xlsx": (60, set()),
    ".txt": (10, set()),
    ".md": (10, set()),
    ".zip": (200, set()),
    ".mp4": (300, set()),
    ".mp3": (100, set()),
    ".m4a": (100, set()),
}

# AI 提炼可直接消费的类型
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTS = {".pdf"}


class FileValidationError(ValueError):
    pass


def storage_root() -> Path:
    return Path(get_settings().TRAINING_STORAGE_ROOT)


def validate_upload(filename: str, mime_type: str, file_size: int) -> str:
    """校验后缀/大小/MIME，返回小写后缀。失败抛 FileValidationError（中文提示）。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in UPLOAD_LIMITS:
        allowed = " ".join(sorted(UPLOAD_LIMITS))
        raise FileValidationError(f"不支持的文件类型 {ext or '(无后缀)'}，允许：{allowed}")
    max_mb, mimes = UPLOAD_LIMITS[ext]
    if file_size > max_mb * 1024 * 1024:
        raise FileValidationError(f"{ext} 文件不能超过 {max_mb}MB")
    if mimes and mime_type and mime_type not in mimes:
        raise FileValidationError(f"文件内容类型 {mime_type} 与后缀 {ext} 不匹配")
    return ext


def store_bytes(original_filename: str, content: bytes) -> str:
    """落盘到 TRAINING_STORAGE_ROOT，uuid 命名 + 前两位散列子目录，返回相对路径。"""
    ext = Path(original_filename or "").suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    rel = Path(name[:2]) / name
    abs_path = storage_root() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return rel.as_posix()


def resolve_private_path(relative_path: str) -> Path:
    """相对路径 → 绝对路径，含目录穿越防护。"""
    root = storage_root().resolve()
    p = (root / relative_path).resolve()
    if not p.is_relative_to(root):
        raise FileValidationError("非法文件路径")
    return p


def remove_quietly(relative_path: str) -> None:
    """尽力删除盘上文件；失败只记日志不抛（DB 已成功的操作不被清盘失败顶掉）。"""
    import logging

    try:
        p = resolve_private_path(relative_path)
        if p.is_file():
            p.unlink()
    except Exception as e:  # noqa: BLE001
        logging.getLogger("commission").warning("training file cleanup failed %s: %s", relative_path, e)
        print(f"[training] file cleanup failed {relative_path}: {e}", flush=True)
