"""Private knowledge image normalization and storage."""

from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings


MEBIBYTE = 1024 * 1024
MAX_PIXELS = 60_000_000
MAX_EDGE = 2400
_MIME_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_FORMAT_SUFFIX = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
logger = logging.getLogger("commission")


class ImageValidationError(ValueError):
    pass


class ImageStorageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredKnowledgeImage:
    storage_path: str
    mime_type: str
    file_size: int
    width: int
    height: int
    sha256: str


def max_upload_bytes() -> int:
    return get_settings().KNOWLEDGE_IMAGE_MAX_UPLOAD_MB * MEBIBYTE


def storage_root() -> Path:
    return Path(os.path.abspath(get_settings().KNOWLEDGE_STORAGE_ROOT))


def resolve_private_path(relative_path: str) -> Path:
    root = storage_root().resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ImageStorageError("非法知识库图片路径") from None
    return path


def _normalized_bytes(content: bytes, declared_mime: str) -> tuple[bytes, str, int, int]:
    if not content:
        raise ImageValidationError("图片内容为空")
    if len(content) > max_upload_bytes():
        raise ImageValidationError(
            f"图片不能超过 {get_settings().KNOWLEDGE_IMAGE_MAX_UPLOAD_MB}MiB"
        )
    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    expected = _MIME_FORMAT.get(mime)
    if expected is None:
        raise ImageValidationError("仅支持 JPEG、PNG 和 WebP 图片")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            if probe.format != expected:
                raise ImageValidationError("图片真实格式与声明类型不一致")
            if probe.width < 1 or probe.height < 1 or probe.width * probe.height > MAX_PIXELS:
                raise ImageValidationError("图片分辨率无效或超过 60MP")
            probe.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            if expected == "JPEG":
                if image.mode in {"RGBA", "LA"}:
                    rgba = image.convert("RGBA")
                    clean = Image.new("RGB", rgba.size, "white")
                    clean.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    clean = image.convert("RGB")
            elif image.mode not in {"RGB", "RGBA", "L", "LA"}:
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                clean = image.convert("RGBA" if has_alpha else "RGB")
            else:
                clean = image.copy()
            clean.info.clear()
            if max(clean.size) > MAX_EDGE:
                clean.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
            width, height = clean.size
            output = io.BytesIO()
            if expected == "JPEG":
                clean.save(output, "JPEG", quality=90, optimize=True, progressive=False, exif=b"")
            elif expected == "PNG":
                clean.save(output, "PNG", optimize=True, compress_level=9)
            else:
                clean.save(output, "WEBP", quality=90, method=6, exif=b"")
            normalized = output.getvalue()
            clean.close()
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageValidationError("上传的文件不是有效图片") from None
    if len(normalized) > max_upload_bytes():
        raise ImageValidationError("图片规范化后仍超过大小限制")
    return normalized, mime, width, height


def store_upload(library_id: int, content: bytes, declared_mime: str) -> StoredKnowledgeImage:
    normalized, mime, width, height = _normalized_bytes(content, declared_mime)
    digest = hashlib.sha256(normalized).hexdigest()
    suffix = _FORMAT_SUFFIX[_MIME_FORMAT[mime]]
    name = f"{uuid4().hex}{suffix}"
    relative = Path(str(library_id)) / name[:2] / name
    path = resolve_private_path(relative.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(normalized)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ImageStorageError("知识库图片保存失败") from exc
    return StoredKnowledgeImage(
        storage_path=relative.as_posix(),
        mime_type=mime,
        file_size=len(normalized),
        width=width,
        height=height,
        sha256=digest,
    )


def remove_quietly(relative_path: str) -> bool:
    try:
        resolve_private_path(relative_path).unlink(missing_ok=True)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge image cleanup failed path=%s error=%s", relative_path, exc)
        print(f"[knowledge] image cleanup failed path={relative_path}: {exc}", flush=True)
        return False
