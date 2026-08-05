"""Private image normalization, storage, and provider-download boundaries."""

from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import os
import re
import socket
import ssl
import warnings
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
    return Path(get_settings().DESIGN_IMAGE_STORAGE_ROOT).resolve()


def resolve_private_path(relative_path: str) -> Path:
    """Resolve a non-empty relative path without allowing traversal or symlink escape."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ImageStorageError("非法文件路径")
    candidate_path = Path(relative_path)
    if candidate_path.is_absolute() or candidate_path.drive:
        raise ImageStorageError("非法文件路径")
    root = _storage_root()
    try:
        target = (root / candidate_path).resolve()
    except (OSError, ValueError):
        raise ImageStorageError("非法文件路径") from None
    if target == root or not target.is_relative_to(root):
        raise ImageStorageError("非法文件路径")
    return target


def _write_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


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

    image_id = uuid4().hex
    suffix = _FORMAT_SUFFIX[fmt]
    base = Path(str(owner_user_id)) / kind
    relative = (base / f"{image_id}{suffix}").as_posix()
    thumbnail_relative = (base / f"{image_id}_thumb{suffix}").as_posix()
    target = resolve_private_path(relative)
    thumbnail_target = resolve_private_path(thumbnail_relative)

    _write_atomic(target, image.content)
    try:
        _write_atomic(thumbnail_target, _thumbnail_content(image, fmt))
    except Exception:
        target.unlink(missing_ok=True)
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
    target = resolve_private_path(relative_path)
    # Re-resolve immediately before unlink so an already-changed symlink cannot escape.
    root = _storage_root()
    current = target.resolve()
    if not current.is_relative_to(root):
        raise ImageStorageError("非法文件路径")
    if current.is_file() or current.is_symlink():
        current.unlink()


def _normalize_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ProviderDownloadError("provider URL host is invalid") from None


def _resolve_host_ips(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
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
        port = parsed.port or 443
    except ValueError:
        raise ProviderDownloadError("provider URL is invalid") from None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ProviderDownloadError("provider URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderDownloadError("provider URL must not contain credentials")
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

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port), timeout=self.timeout
        )
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


class _ConnectionResponse:
    def __init__(self, response: http.client.HTTPResponse, connection: _PinnedHTTPSConnection):
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = response.headers

    def read(self, amount: int = -1) -> bytes:
        return self._response.read(amount)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


def _open_pinned_https(url: str, pinned_ip: str):
    """Connect to the validated IP while retaining the URL hostname for Host and TLS SNI."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    connection = _PinnedHTTPSConnection(
        host, pinned_ip, port=port, timeout=DOWNLOAD_TIMEOUT_SECONDS
    )
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
        return _ConnectionResponse(connection.getresponse(), connection)
    except Exception:
        connection.close()
        raise


def _header_value(headers, name: str) -> str | None:
    value = headers.get(name)
    return str(value) if value is not None else None


def download_provider_image(url: str, *, allowed_hosts: set[str]) -> bytes:
    """Download a bounded HTTPS body with per-hop SSRF checks and DNS pinning."""
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        parsed, host, port = _validated_url(current_url, allowed_hosts)
        addresses = _resolve_host_ips(host, port)
        try:
            parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        except ValueError:
            raise ProviderDownloadError("provider DNS returned an invalid address") from None
        if any(_is_forbidden_address(address) for address in parsed_addresses):
            raise ProviderDownloadError("provider DNS returned a forbidden address")

        # The transport receives the already-validated literal IP and never resolves host again.
        try:
            response = _open_pinned_https(current_url, str(parsed_addresses[0]))
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
                chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, MAX_IMAGE_BYTES - total + 1))
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
            response.close()
    raise ProviderDownloadError("provider redirect limit exceeded")
