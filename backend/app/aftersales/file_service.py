"""售后私有文件的校验、落盘和路径约束。"""

from pathlib import Path
from uuid import uuid4


class FileValidationError(ValueError):
    pass


EVIDENCE_LIMITS = {
    ".jpg": (20, {"image/jpeg"}),
    ".jpeg": (20, {"image/jpeg"}),
    ".png": (20, {"image/png"}),
    ".webp": (20, {"image/webp"}),
    ".mp4": (200, {"video/mp4"}),
    ".mov": (200, {"video/quicktime", "video/mov"}),
    ".pdf": (20, {"application/pdf"}),
    ".doc": (20, {"application/msword"}),
    ".docx": (
        20,
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ),
}
SOP_LIMITS = {key: value for key, value in EVIDENCE_LIMITS.items() if key in {".docx", ".pdf"}}


def validate_upload(
    filename: str,
    mime_type: str,
    file_size: int,
    *,
    purpose: str,
) -> None:
    limits = SOP_LIMITS if purpose == "sop" else EVIDENCE_LIMITS
    suffix = Path(filename).suffix.lower()
    if suffix not in limits:
        raise FileValidationError("不支持的文件格式")
    max_mb, allowed_mimes = limits[suffix]
    if file_size < 1:
        raise FileValidationError("文件内容为空")
    if file_size > max_mb * 1024 * 1024:
        raise FileValidationError(f"{suffix[1:].upper()} 文件不能超过 {max_mb}MB")
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in allowed_mimes:
        raise FileValidationError("文件 MIME 类型与扩展名不匹配")


def resolve_private_path(storage_root: str | Path, relative_path: str) -> Path:
    root = Path(storage_root).resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise FileValidationError("非法文件路径")
    return target


def store_bytes(
    storage_root: str | Path,
    purpose: str,
    original_filename: str,
    content: bytes,
) -> str:
    suffix = Path(original_filename).suffix.lower()
    relative = Path(purpose) / uuid4().hex[:2] / f"{uuid4().hex}{suffix}"
    target = resolve_private_path(storage_root, relative.as_posix())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative.as_posix()
