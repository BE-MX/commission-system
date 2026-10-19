"""客户素材私有存储适配器；本地 object key 为未来 COS 迁移边界。"""

import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.storage.cos import CosObjectStore, ObjectMissing, StorageError, enabled
from app.customer_media import transcode


logger = logging.getLogger("commission")


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
    duration_seconds: int | None = None
    playback_key: str | None = None
    playback_size: int | None = None
    thumbnail_key: str | None = None
    thumbnail_size: int | None = None
    # 上传过程内的本地文件位置；写入数据库前不落库，云端上传完成后随临时目录销毁。
    playback_path: Path | None = None
    thumbnail_path: Path | None = None


def derivative_keys(object_key: str) -> tuple[str, str]:
    """由原件键推导播放版与海报键：.../originals/x.mp4 -> playback/x.mp4 + thumbnails/x.jpg。"""
    source = Path(object_key)
    stem = source.stem
    batch_dir = source.parent.parent
    return (
        (batch_dir / "playback" / f"{stem}.mp4").as_posix(),
        (batch_dir / "thumbnails" / f"{stem}.jpg").as_posix(),
    )


def _variant_object(asset, variant: str | None) -> tuple[str, str]:
    """返回 (对象键, MIME)。海报缺失视为不存在；播放版缺失时回退到原件。"""
    if variant == "poster":
        key = getattr(asset, "thumbnail_key", None)
        if not key:
            from fastapi import HTTPException
            raise HTTPException(404, "素材海报不存在")
        return key, transcode.POSTER_CONTENT_TYPE
    if variant == "playback":
        key = getattr(asset, "playback_key", None)
        if key:
            return key, transcode.PLAYBACK_CONTENT_TYPE
    return asset.object_key, getattr(asset, "content_type", "application/octet-stream")


def _original_object(asset) -> tuple[str, str]:
    return asset.object_key, getattr(asset, "content_type", "application/octet-stream")


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

        playback_key = playback_size = thumbnail_key = thumbnail_size = duration = None
        playback_path = thumbnail_path = None
        if declared[0] == "video":
            try:
                # 转码是秒级 CPU 操作，放到线程池，避免阻塞单 worker 的事件循环。
                from starlette.concurrency import run_in_threadpool
                derivatives = await run_in_threadpool(self.build_derivatives, object_key)
            except transcode.TranscodeError as exc:
                # 转码失败即拒绝上传：不能让客户拿到浏览器无法播放的文件。
                target.unlink(missing_ok=True)
                raise MediaStorageError(str(exc)) from exc
            except Exception:
                # 无法生成浏览器可播放版本时不保留半成品原件。
                target.unlink(missing_ok=True)
                raise
            (playback_key, playback_size, thumbnail_key, thumbnail_size,
             playback_path, thumbnail_path, duration) = derivatives

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
            duration_seconds=duration,
            playback_key=playback_key,
            playback_size=playback_size,
            thumbnail_key=thumbnail_key,
            thumbnail_size=thumbnail_size,
            playback_path=playback_path,
            thumbnail_path=thumbnail_path,
        )

    def build_derivatives(self, object_key: str) -> tuple:
        """生成 H.264 播放版与首帧海报。

        返回 (播放键, 播放大小, 海报键, 海报大小, 播放路径, 海报路径, 时长秒)。
        """
        playback_key, thumbnail_key = derivative_keys(object_key)
        source = self.resolve(object_key)
        target = self.resolve(playback_key)
        poster = self.resolve(thumbnail_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        poster.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        temp_poster = poster.with_name(f".{poster.name}.{uuid.uuid4().hex}.part")
        try:
            result = transcode.build_playback(source, temp_target, temp_poster)
            os.replace(temp_target, target)
            if result.poster_path is not None:
                os.replace(temp_poster, poster)
            else:
                poster.unlink(missing_ok=True)
        except Exception:
            # 任一派生文件落位失败都不保留半套结果。
            target.unlink(missing_ok=True)
            poster.unlink(missing_ok=True)
            raise
        finally:
            temp_target.unlink(missing_ok=True)
            temp_poster.unlink(missing_ok=True)
        return (
            playback_key,
            result.size,
            thumbnail_key if result.poster_path is not None else None,
            result.poster_size or None,
            self.resolve(playback_key),
            self.resolve(thumbnail_key) if result.poster_path is not None else None,
            result.info.duration_seconds,
        )

    def delete(self, object_key: str | None) -> None:
        if object_key:
            self.resolve(object_key).unlink(missing_ok=True)

    def response(self, asset, *, download: bool = False, variant: str | None = None):
        from fastapi import HTTPException
        from fastapi.responses import FileResponse
        object_key, content_type = _variant_object(asset, variant)
        path = self.resolve(object_key)
        if not path.is_file() and variant == "playback":
            # 派生对象丢失时退回原件，避免整段视频 404。
            object_key, content_type = _original_object(asset)
            path = self.resolve(object_key)
        if not path.is_file():
            raise HTTPException(404, "素材文件不存在")
        return FileResponse(path, media_type=content_type,
                            filename=asset.file_name if download else None,
                            content_disposition_type="attachment" if download else "inline",
                            headers={"Cache-Control": "private, no-store"})


class CosMediaStorage:
    """Validate in a private temporary workspace; only verified objects are bound."""
    provider = "cos"

    def __init__(self, store=None):
        self.store = store or CosObjectStore("customer-media")

    async def save_upload(self, upload, *, customer_id, batch_id, max_bytes):
        from starlette.concurrency import run_in_threadpool
        cache = Path(get_settings().COS_CACHE_ROOT)
        cache.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="customer-media-", dir=cache) as directory:
            local = LocalMediaStorage(directory)
            stored = await local.save_upload(upload, customer_id=customer_id,
                                            batch_id=batch_id, max_bytes=max_bytes)
            published: list[str] = []
            try:
                # 先登记键再上传：put_file 在写完后才校验，失败时对象可能已存在。
                published.append(stored.object_key)
                result = await run_in_threadpool(self.store.put_file, stored.object_key,
                                                 local.resolve(stored.object_key), stored.content_type)
                if result.sha256 != stored.sha256 or result.size != stored.file_size:
                    raise MediaStorageError("云端素材校验失败")
                if stored.playback_path and stored.playback_key:
                    published.append(stored.playback_key)
                    playback = await run_in_threadpool(
                        self.store.put_file, stored.playback_key,
                        stored.playback_path, transcode.PLAYBACK_CONTENT_TYPE,
                    )
                    if playback.size != stored.playback_size:
                        raise MediaStorageError("云端播放版校验失败")
                if stored.thumbnail_path and stored.thumbnail_key:
                    published.append(stored.thumbnail_key)
                    poster = await run_in_threadpool(
                        self.store.put_file, stored.thumbnail_key,
                        stored.thumbnail_path, transcode.POSTER_CONTENT_TYPE,
                    )
                    if poster.size != stored.thumbnail_size:
                        raise MediaStorageError("云端海报校验失败")
            except Exception:
                # 上传失败时尚无数据库行引用这些对象（uuid 键且尚未返回），可安全回收。
                for key in published:
                    try:
                        self.store.delete(key)
                    except Exception as exc:  # noqa: BLE001 - 清理失败不覆盖原始错误
                        logger.warning("[customer-media] orphan cleanup deferred type=%s", type(exc).__name__)
                raise
            # 临时目录即将销毁，返回的对象不再携带本地路径。
            return replace(stored, provider=self.provider, playback_path=None, thumbnail_path=None)

    def delete(self, object_key):
        if object_key:
            self.store.delete(object_key)

    def response(self, asset, *, download=False, variant=None):
        from fastapi import HTTPException
        from fastapi.responses import RedirectResponse
        object_key, content_type = _variant_object(asset, variant)
        try:
            self.store.head(object_key)
        except ObjectMissing:
            if variant != "playback":
                raise HTTPException(404, "素材文件不存在") from None
            # 派生对象丢失时退回原件，避免整段视频 404。
            object_key, content_type = _original_object(asset)
            try:
                self.store.head(object_key)
            except ObjectMissing:
                raise HTTPException(404, "素材文件不存在") from None
        except StorageError:
            raise HTTPException(503, "云存储暂时不可用，请稍后重试", headers={"Retry-After": "10"}) from None
        try:
            url = self.store.download_url(object_key, filename=asset.file_name,
                                          content_type=content_type, download=download)
        except StorageError:
            raise HTTPException(503, "云存储暂时不可用，请稍后重试", headers={"Retry-After": "10"}) from None
        return RedirectResponse(url, status_code=303,
                                headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})


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


def storage_for(provider: str | None = None):
    provider = provider or ("cos" if enabled("customer-media") else "local")
    if provider == "local":
        return LocalMediaStorage()
    if provider == "cos":
        return CosMediaStorage()
    raise MediaStorageError(f"暂不支持存储类型 {provider}")
