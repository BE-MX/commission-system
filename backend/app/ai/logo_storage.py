"""AI 提供商 LOGO 存储边界：magic bytes 校验、禁 SVG、复用 core/storage 跨节点同步。"""

from __future__ import annotations

import logging
from pathlib import Path
import uuid

from app.core.storage import files

logger = logging.getLogger("commission.ai.logo")

STORAGE_DOMAIN = "ai-provider-logos"
ROOT = Path(__file__).resolve().parents[2] / "uploads" / "ai-logos"
MAX_LOGO_BYTES = 512 * 1024

_MAGIC_TYPES: tuple[tuple[str, str, object], ...] = (
    ("image/png", "png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    ("image/jpeg", "jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    ("image/webp", "webp", lambda b: len(b) >= 12 and b.startswith(b"RIFF") and b[8:12] == b"WEBP"),
)


def detect_logo_type(content: bytes) -> tuple[str, str]:
    """基于文件头 magic bytes 校验图片格式；显式拒绝 SVG 与其他任意格式。"""
    if not content:
        raise ValueError("LOGO 文件不能为空")
    if len(content) > MAX_LOGO_BYTES:
        raise ValueError("LOGO 文件大小不能超过 512KB")
    head = content[:64].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml", b"<!doctype")):
        raise ValueError("出于安全原因不支持 SVG，请上传 PNG / JPEG / WEBP 图片")
    for mime, ext, matcher in _MAGIC_TYPES:
        if matcher(content):
            return mime, ext
    raise ValueError("LOGO 仅支持真实 PNG / JPEG / WEBP 图片")


def save_logo(provider_id: int, content: bytes, *, root: Path | None = None) -> tuple[str, str]:
    base_root = root or ROOT
    mime, ext = detect_logo_type(content)
    key = f"provider-{provider_id}-{uuid.uuid4().hex[:16]}.{ext}"
    if not files.put_bytes(STORAGE_DOMAIN, key, content, mime):
        path = files.local_path(base_root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return key, mime


def read_logo_path(key: str, *, root: Path | None = None) -> Path:
    return files.read_path(STORAGE_DOMAIN, key, root or ROOT)


def mime_for_key(key: str) -> str:
    ext = Path(key).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def delete_logo_quietly(key: str, *, root: Path | None = None) -> None:
    if not key:
        return
    try:
        files.delete(STORAGE_DOMAIN, key, root or ROOT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to clean up old AI provider logo key=%s err=%s", key, type(exc).__name__)
        print(f"[AI-LOGO] cleanup failed key={key} err={type(exc).__name__}", flush=True)
