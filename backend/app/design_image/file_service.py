"""Private image normalization, storage, and provider-download boundaries."""

from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import logging
import os
import queue
import re
import socket
import ssl
import stat
import threading
import time
import warnings
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 60_000_000
MAX_IMAGE_EDGE = 2048
THUMBNAIL_EDGE = 320
MAX_REDIRECTS = 5
DOWNLOAD_TIMEOUT_SECONDS = 30
DOWNLOAD_CHUNK_BYTES = 64 * 1024

_FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_MIME_FORMAT = {mime: fmt for fmt, mime in _FORMAT_MIME.items()}
_FORMAT_SUFFIX = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
_KIND_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "instance-data.ec2.internal",
}
_STORAGE_LOCK = threading.RLock()
logger = logging.getLogger("commission")


class _BoundedResolverExecutor:
    def __init__(self, workers: int = 2, queued: int = 2):
        self._queue: queue.Queue = queue.Queue(maxsize=queued)
        for index in range(workers):
            worker = threading.Thread(
                target=self._run, name=f"design-image-dns-{index}", daemon=True
            )
            worker.start()

    def submit(self, function, *args, timeout: float) -> Future:
        future: Future = Future()
        try:
            self._queue.put((future, function, args), timeout=max(0, timeout))
        except queue.Full:
            raise ProviderDownloadError("provider DNS deadline exceeded") from None
        return future

    def _run(self) -> None:
        while True:
            future, function, args = self._queue.get()
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(function(*args))
                    except BaseException as exc:
                        future.set_exception(exc)
            finally:
                self._queue.task_done()


_DNS_RESOLVER = _BoundedResolverExecutor()


class ImageValidationError(ValueError):
    """The supplied bytes are not an acceptable image."""


class ImageStorageError(ValueError):
    """A private storage path violates the storage boundary."""


class ProviderDownloadError(ValueError):
    """A provider URL or response violates the download boundary."""


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    content: bytes
    mime_type: str
    width: int
    height: int
    sha256: str

    @property
    def file_size(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class StoredImage:
    relative_path: str
    thumbnail_relative_path: str
    mime_type: str
    file_size: int
    width: int
    height: int
    sha256: str


def _magic_format(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "WEBP"
    return None


def _clean_mode(image: Image.Image, fmt: str) -> Image.Image:
    if fmt == "JPEG":
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")
    if image.mode == "P":
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    if image.mode not in {"RGB", "RGBA", "L", "LA"}:
        return image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image.copy()


def _encode_image(image: Image.Image, fmt: str) -> bytes:
    output = io.BytesIO()
    if fmt == "JPEG":
        image.save(
            output,
            format="JPEG",
            quality=90,
            optimize=True,
            progressive=False,
            subsampling=0,
            exif=b"",
        )
    elif fmt == "PNG":
        image.save(output, format="PNG", optimize=True, compress_level=9)
    else:
        image.save(output, format="WEBP", quality=90, method=6, exif=b"", icc_profile=b"")
    return output.getvalue()


def normalize_upload(content: bytes, declared_mime: str) -> NormalizedImage:
    """Validate real image bytes, orient, resize, and re-encode without metadata."""
    if not content:
        raise ImageValidationError("图片内容为空")
    configured_limit = get_settings().DESIGN_IMAGE_MAX_UPLOAD_MB * 1024 * 1024
    byte_limit = min(MAX_IMAGE_BYTES, configured_limit)
    if len(content) > byte_limit:
        raise ImageValidationError("图片不能超过 20MiB")

    mime = (declared_mime or "").split(";", 1)[0].strip().lower()
    fmt = _magic_format(content)
    if fmt is None or mime not in _MIME_FORMAT or _MIME_FORMAT[mime] != fmt:
        raise ImageValidationError("图片真实格式与声明的 MIME 不匹配")

    configured_pixels = get_settings().DESIGN_IMAGE_MAX_PIXELS
    pixel_limit = min(MAX_IMAGE_PIXELS, configured_pixels)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                if probe.format != fmt:
                    raise ImageValidationError("图片格式解析结果不一致")
                if probe.width < 1 or probe.height < 1:
                    raise ImageValidationError("图片尺寸无效")
                # This check intentionally precedes verify/load: compressed headers alone can
                # declare an unsafe pixel budget and must be rejected before allocation.
                if probe.width * probe.height > pixel_limit:
                    raise ImageValidationError("图片分辨率不能超过 60MP")
                probe.verify()

            with Image.open(io.BytesIO(content)) as source:
                oriented = ImageOps.exif_transpose(source)
                cleaned = _clean_mode(oriented, fmt)
                cleaned.info.clear()
                if max(cleaned.size) > MAX_IMAGE_EDGE:
                    cleaned.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                width, height = cleaned.size
                normalized_content = _encode_image(cleaned, fmt)
                cleaned.close()
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageValidationError("图片分辨率不能超过 60MP") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageValidationError("上传的文件不是有效图片") from None

    return NormalizedImage(
        content=normalized_content,
        mime_type=_FORMAT_MIME[fmt],
        width=width,
        height=height,
        sha256=hashlib.sha256(normalized_content).hexdigest(),
    )


def _storage_root() -> Path:
    configured = Path(get_settings().DESIGN_IMAGE_STORAGE_ROOT)
    return Path(os.path.abspath(configured))


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        ):
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise ImageStorageError("无法验证私有存储路径") from exc
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _reject_existing_reparse_points(path: Path) -> None:
    current = Path(path.anchor)
    if os.path.lexists(current) and _is_reparse_point(current):
        raise ImageStorageError("私有存储路径包含 reparse point: root")
    for part in path.parts[1:]:
        current /= part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ImageStorageError(f"私有存储路径包含 reparse point: {current.name}")


def _validate_storage_boundary_unlocked(relative_path: str | None = None) -> Path:
    root = _storage_root()
    _reject_existing_reparse_points(root)
    if relative_path is None:
        return root
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ImageStorageError("非法文件路径")
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive:
        raise ImageStorageError("非法文件路径")
    try:
        target = Path(os.path.abspath(root / candidate))
    except (OSError, ValueError):
        raise ImageStorageError("非法文件路径") from None
    if target == root or not target.is_relative_to(root):
        raise ImageStorageError("非法文件路径")
    _reject_existing_reparse_points(target)
    return target


def validate_storage_boundary(relative_path: str | None = None) -> Path:
    """Validate the configured root and existing path components.

    This process-local check assumes the root and its parents are writable only by the
    service account. Deployment ACL validation remains an operational responsibility.
    """
    with _STORAGE_LOCK:
        return _validate_storage_boundary_unlocked(relative_path)


def resolve_private_path(relative_path: str) -> Path:
    """Resolve a path inside the trusted, non-reparse private storage boundary."""
    with _STORAGE_LOCK:
        return _validate_storage_boundary_unlocked(relative_path)


def _cleanup_best_effort(path: Path, context: str) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        message = f"[design-image] {context} cleanup failed {path.name}: {exc}"
        logger.warning(message)
        print(message, flush=True)


def _write_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_existing_reparse_points(target.parent)
    temporary = target.with_name(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        _cleanup_best_effort(temporary, "temporary file")


def _thumbnail_content(image: NormalizedImage, fmt: str) -> bytes:
    with Image.open(io.BytesIO(image.content)) as source:
        thumbnail = source.copy()
    thumbnail.info.clear()
    thumbnail.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
    try:
        return _encode_image(thumbnail, fmt)
    finally:
        thumbnail.close()


def save_private_image(
    image: NormalizedImage, *, owner_user_id: int, kind: str
) -> StoredImage:
    """Atomically store a normalized original and thumbnail under the private root."""
    if owner_user_id <= 0:
        raise ImageStorageError("文件所有者无效")
    if not isinstance(kind, str) or _KIND_RE.fullmatch(kind) is None:
        raise ImageStorageError("文件类型无效")
    fmt = _MIME_FORMAT.get(image.mime_type)
    if fmt is None or _magic_format(image.content) != fmt:
        raise ImageStorageError("只能保存已归一化的图片")

    with _STORAGE_LOCK:
        image_id = uuid4().hex
        suffix = _FORMAT_SUFFIX[fmt]
        base = Path(str(owner_user_id)) / kind
        relative = (base / f"{image_id}{suffix}").as_posix()
        thumbnail_relative = (base / f"{image_id}_thumb{suffix}").as_posix()
        target = _validate_storage_boundary_unlocked(relative)
        thumbnail_target = _validate_storage_boundary_unlocked(thumbnail_relative)

        _write_atomic(target, image.content)
        try:
            thumbnail = _thumbnail_content(image, fmt)
            _write_atomic(thumbnail_target, thumbnail)
        except Exception:
            _cleanup_best_effort(target, "original rollback")
            raise

    return StoredImage(
        relative_path=relative,
        thumbnail_relative_path=thumbnail_relative,
        mime_type=image.mime_type,
        file_size=len(image.content),
        width=image.width,
        height=image.height,
        sha256=image.sha256,
    )


def delete_private_file(relative_path: str) -> None:
    with _STORAGE_LOCK:
        target = _validate_storage_boundary_unlocked(relative_path)
        if target.is_file():
            target.unlink()


def _normalize_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ProviderDownloadError("provider URL host is invalid") from None


def _resolve_host_ips(host: str, port: int, deadline: float | None = None) -> list[str]:
    deadline = deadline or (time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS)
    remaining = _remaining_download_time(deadline)
    future = None
    try:
        future = _DNS_RESOLVER.submit(
            socket.getaddrinfo,
            host,
            port,
            0,
            socket.SOCK_STREAM,
            timeout=remaining,
        )
        records = future.result(timeout=_remaining_download_time(deadline))
    except ProviderDownloadError:
        if future is not None:
            future.cancel()
        raise
    except FutureTimeoutError:
        future.cancel()
        raise ProviderDownloadError("provider DNS deadline exceeded") from None
    except (socket.gaierror, OSError):
        raise ProviderDownloadError("provider host DNS resolution failed") from None
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses:
        raise ProviderDownloadError("provider host DNS resolution returned no address")
    return addresses


def _is_forbidden_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # `is_global` alone is insufficient on some Python versions: multicast can report
    # global scope even though connecting to it is never valid for a provider download.
    return (
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _validated_url(url: str, allowed_hosts: set[str]):
    try:
        parsed = urlsplit(url)
        port = parsed.port if parsed.port is not None else 443
    except ValueError:
        raise ProviderDownloadError("provider URL is invalid") from None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ProviderDownloadError("provider URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderDownloadError("provider URL must not contain credentials")
    if port != 443:
        raise ProviderDownloadError("provider URL must use port 443")
    host = _normalize_host(parsed.hostname)
    normalized_allowed = {_normalize_host(item) for item in allowed_hosts if item}
    if not normalized_allowed or host not in normalized_allowed:
        raise ProviderDownloadError("provider URL host is not allowlisted")
    if host in _METADATA_HOSTS:
        raise ProviderDownloadError("provider URL metadata host is forbidden")
    return parsed, host, port


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, *, port: int, timeout: int):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip
        self._abort_lock = threading.Lock()
        self._aborted = False

    @staticmethod
    def _shutdown_and_close(sock) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
        # socket.close() defers the OS-handle close while makefile() readers exist.
        # Detach and close that handle explicitly so a blocked HTTPResponse/file read wakes.
        detach = getattr(sock, "detach", None)
        if detach is not None:
            try:
                handle = detach()
                if handle != -1:
                    socket.close(handle)
            except OSError:
                pass

    def abort(self) -> None:
        """Idempotently hard-close the active socket to interrupt blocking file reads."""
        with self._abort_lock:
            if self._aborted:
                return
            self._aborted = True
            sock = self.sock
        if sock is not None:
            self._shutdown_and_close(sock)

    def connect(self) -> None:
        with self._abort_lock:
            if self._aborted:
                raise TimeoutError("provider connection deadline exceeded")
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )
        try:
            wrapped = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise
        with self._abort_lock:
            if not self._aborted:
                self.sock = wrapped
                return
        self._shutdown_and_close(wrapped)
        raise TimeoutError("provider connection deadline exceeded")


class _DeadlineWatchdog:
    def __init__(self, deadline: float, close_callback):
        self._lock = threading.Lock()
        self._active = True
        self._close_callback = close_callback
        self._timer = threading.Timer(
            max(0, deadline - time.monotonic()), self._expire
        )
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
        try:
            self._close_callback()
        except Exception as exc:
            logger.warning("design-image deadline close failed: %s", exc)
            print(f"[design-image] deadline close failed: {exc}", flush=True)

    def cancel(self) -> None:
        with self._lock:
            self._active = False
        self._timer.cancel()


class _ConnectionResponse:
    def __init__(
        self,
        response: http.client.HTTPResponse,
        connection: _PinnedHTTPSConnection,
        watchdog: _DeadlineWatchdog,
    ):
        self._response = response
        self._connection = connection
        self._watchdog = watchdog
        self.status = response.status
        self.headers = response.headers

    def read(self, amount: int = -1) -> bytes:
        return self._response.read(amount)

    def set_timeout(self, timeout: float) -> None:
        if self._connection.sock is None:
            raise OSError("provider connection is closed")
        self._connection.sock.settimeout(timeout)

    def close(self) -> None:
        self._watchdog.cancel()
        try:
            self._response.close()
        finally:
            self._connection.close()


def _open_pinned_https(url: str, pinned_ip: str, deadline: float):
    """Connect to the validated IP while retaining the URL hostname for Host and TLS SNI."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    connection = _PinnedHTTPSConnection(
        host, pinned_ip, port=port, timeout=_remaining_download_time(deadline)
    )
    watchdog = _DeadlineWatchdog(deadline, connection.abort)
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    host_header = host if port == 443 else f"{host}:{port}"
    try:
        connection.request(
            "GET",
            target,
            headers={"Host": host_header, "Accept": "image/*", "User-Agent": "ArkImageFetcher/1"},
        )
        return _ConnectionResponse(connection.getresponse(), connection, watchdog)
    except Exception:
        watchdog.cancel()
        try:
            connection.close()
        except Exception as cleanup_exc:
            message = f"[design-image] provider connection cleanup failed: {cleanup_exc}"
            logger.warning(message)
            print(message, flush=True)
        raise


def _header_value(headers, name: str) -> str | None:
    value = headers.get(name)
    return str(value) if value is not None else None


def _remaining_download_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProviderDownloadError("provider image download deadline exceeded")
    return remaining


def _close_response_best_effort(response) -> None:
    try:
        response.close()
    except Exception as exc:
        message = f"[design-image] provider response cleanup failed: {exc}"
        logger.warning(message)
        print(message, flush=True)


def download_provider_image(url: str, *, allowed_hosts: set[str]) -> bytes:
    """Download a bounded HTTPS body with per-hop SSRF checks and DNS pinning."""
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        parsed, host, port = _validated_url(current_url, allowed_hosts)
        addresses = _resolve_host_ips(host, port, deadline)
        try:
            parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        except ValueError:
            raise ProviderDownloadError("provider DNS returned an invalid address") from None
        if any(_is_forbidden_address(address) for address in parsed_addresses):
            raise ProviderDownloadError("provider DNS returned a forbidden address")

        # The transport receives the already-validated literal IP and never resolves host again.
        try:
            response = _open_pinned_https(
                current_url,
                str(parsed_addresses[0]),
                deadline,
            )
        except (OSError, ssl.SSLError, http.client.HTTPException):
            raise ProviderDownloadError("provider image download failed") from None
        try:
            if response.status in _REDIRECT_STATUSES:
                location = _header_value(response.headers, "Location")
                if not location:
                    raise ProviderDownloadError("provider redirect has no Location")
                if redirect_count >= MAX_REDIRECTS:
                    raise ProviderDownloadError("provider redirect limit exceeded")
                current_url = urljoin(current_url, location)
                continue
            if not 200 <= response.status < 300:
                raise ProviderDownloadError(
                    f"provider image download returned HTTP {response.status}"
                )

            length_header = _header_value(response.headers, "Content-Length")
            if length_header is not None:
                try:
                    content_length = int(length_header)
                except ValueError:
                    raise ProviderDownloadError("provider Content-Length is invalid") from None
                if content_length < 0 or content_length > MAX_IMAGE_BYTES:
                    raise ProviderDownloadError("provider image cannot exceed 20MiB")

            chunks: list[bytes] = []
            total = 0
            while True:
                try:
                    response.set_timeout(_remaining_download_time(deadline))
                    chunk = response.read(
                        min(DOWNLOAD_CHUNK_BYTES, MAX_IMAGE_BYTES - total + 1)
                    )
                except ProviderDownloadError:
                    raise
                except (TimeoutError, socket.timeout):
                    raise ProviderDownloadError(
                        "provider image download timed out"
                    ) from None
                except (OSError, http.client.HTTPException):
                    raise ProviderDownloadError("provider image download failed") from None
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ProviderDownloadError("provider image cannot exceed 20MiB")
                chunks.append(chunk)
            if total == 0:
                raise ProviderDownloadError("provider image response is empty")
            return b"".join(chunks)
        finally:
            _close_response_best_effort(response)
    raise ProviderDownloadError("provider redirect limit exceeded")
