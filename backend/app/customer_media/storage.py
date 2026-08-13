"""客户素材私有存储适配器；本地 object key 为未来 COS 迁移边界。"""

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings


CHUNK_BYTES = 4 * 1024 * 1024
_SAFE_CUSTOMER = re.compile(r"[^A-Za-z0-9_.-]+")
_ALLOWED_EXTENSIONS = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".gif": ("image", "image/gif"),
    ".mp4": ("video", "video/mp4"),
    ".mov": ("video", "video/quicktime"),
    ".webm": ("video", "video/webm"),
}


class MediaStorageError(ValueError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    provider: str
    object_key: str
    file_name: str
    media_type: str
    content_type: str
    file_size: int
    sha256: str
    width: int | None = None
    height: int | None = None


class LocalMediaStorage:
    provider = "local"

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_settings().CUSTOMER_MEDIA_STORAGE_ROOT).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, object_key: str) -> Path:
        target = (self.root / object_key).resolve()
        if self.root != target and self.root not in target.parents:
            raise MediaStorageError("非法素材路径")
        return target

    async def save_upload(
        self,
        upload: UploadFile,
        *,
        customer_id: str,
        batch_id: int,
        max_bytes: int,
    ) -> StoredUpload:
        original_name = Path(upload.filename or "upload").name[:255]
        extension = Path(original_name).suffix.lower()
        declared = _ALLOWED_EXTENSIONS.get(extension)
        if not declared:
            raise MediaStorageError("仅支持 JPG/PNG/WebP/GIF/MP4/MOV/WebM")

        safe_customer = _SAFE_CUSTOMER.sub("_", customer_id).replace("..", "_")[:64] or "unknown"
        object_key = (
            f"customers/{safe_customer}/batches/{batch_id}/originals/"
            f"{uuid.uuid4().hex}{extension}"
        )
        target = self.resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        total = 0
        header = b""
        try:
            with temp.open("xb") as stream:
                while True:
                    chunk = await upload.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    if len(header) < 32:
                        header += chunk[: 32 - len(header)]
                    total += len(chunk)
                    if total > max_bytes:
                        raise MediaStorageError(f"单个文件不能超过 {max_bytes // 1024 // 1024}MB")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if total <= 0:
                raise MediaStorageError("不能上传空文件")
            actual_type, actual_content_type = _detect_file_type(header)
            if actual_type != declared[0] or actual_content_type != declared[1]:
                raise MediaStorageError("文件扩展名与真实格式不一致")
            os.replace(temp, target)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        width = height = None
        if declared[0] == "image":
            try:
                from PIL import Image
                with Image.open(target) as image:
                    image.verify()
                with Image.open(target) as image:
                    width, height = image.size
            except Exception as exc:
                target.unlink(missing_ok=True)
                raise MediaStorageError("图片无法解码或已损坏") from exc

        return StoredUpload(
            provider=self.provider,
            object_key=object_key,
            file_name=original_name,
            media_type=declared[0],
            content_type=declared[1],
            file_size=total,
            sha256=digest.hexdigest(),
            width=width,
            height=height,
        )

    def delete(self, object_key: str | None) -> None:
        if object_key:
            self.resolve(object_key).unlink(missing_ok=True)


def _detect_file_type(header: bytes) -> tuple[str, str]:
    if header.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image", "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image", "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in {b"qt  "}:
            return "video", "video/quicktime"
        return "video", "video/mp4"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "video", "video/webm"
    raise MediaStorageError("无法识别文件真实格式")


def storage_for(provider: str = "local") -> LocalMediaStorage:
    if provider != "local":
        raise MediaStorageError(f"暂不支持存储类型 {provider}")
    return LocalMediaStorage()
