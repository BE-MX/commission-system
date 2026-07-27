"""内贸订单 — 参考图存储（私有目录 + 鉴权访问，模式照 app/training/file_service.py）

存储根：Settings.DOMESTIC_STORAGE_ROOT。存库一律相对路径；
读图走鉴权端点返回 FileResponse，不挂静态目录。
只收图片：明细的图文四区就是给车间看参考图的，别的类型没有意义。
"""

import uuid
from pathlib import Path

from app.core.config import get_settings

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
    return Path(get_settings().DOMESTIC_STORAGE_ROOT)


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
    """相对路径 → 绝对路径，挡住 ../ 穿越。

    用 is_relative_to 而非字符串前缀比较（与 training/aftersales 同一写法）：
    前缀比较放得过同级同前缀目录，如 ../domestic-backup/x 也 startswith 得上。
    """
    root = storage_root().resolve()
    target = (root / (rel_path or "")).resolve()
    if not target.is_relative_to(root):
        raise FileValidationError("非法的图片路径")
    return target
