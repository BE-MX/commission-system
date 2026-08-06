from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import os
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
import zlib
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin


MAX_BYTES = 20 * 1024 * 1024


def _image_bytes(
    fmt: str,
    size: tuple[int, int] = (64, 32),
    *,
    exif: Image.Exif | None = None,
    png_text: bool = False,
) -> bytes:
    image = Image.new("RGB", size, (25, 80, 140))
    output = io.BytesIO()
    kwargs: dict[str, object] = {}
    if exif is not None:
        kwargs["exif"] = exif
    if png_text:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private-note", "must-be-removed")
        kwargs["pnginfo"] = metadata
    image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def _png_with_dimensions(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


@pytest.mark.parametrize(
    ("fmt", "declared_mime", "expected_magic", "expected_mime"),
    [
        ("JPEG", "image/jpeg", b"\xff\xd8\xff", "image/jpeg"),
        ("PNG", "image/png", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("WEBP", "image/webp", b"RIFF", "image/webp"),
    ],
)
def test_normalize_upload_accepts_real_supported_images(
    fmt, declared_mime, expected_magic, expected_mime
):
    from app.design_image.file_service import normalize_upload

    normalized = normalize_upload(_image_bytes(fmt), declared_mime)

    assert normalized.mime_type == expected_mime
    assert normalized.content.startswith(expected_magic)
    if fmt == "WEBP":
        assert normalized.content[8:12] == b"WEBP"
    assert (normalized.width, normalized.height) == (64, 32)
    assert normalized.sha256 == hashlib.sha256(normalized.content).hexdigest()


@pytest.mark.parametrize(
    ("content", "mime"),
    [
        (b"", "image/png"),
        (b"not an image", "image/png"),
        (_image_bytes("PNG"), "image/jpeg"),
        (_image_bytes("JPEG"), "text/plain"),
    ],
)
def test_normalize_upload_rejects_empty_fake_or_mismatched_content(content, mime):
    from app.design_image.file_service import ImageValidationError, normalize_upload

    with pytest.raises(ImageValidationError):
        normalize_upload(content, mime)


def test_normalize_upload_rejects_files_over_twenty_mebibytes():
    from app.design_image.file_service import ImageValidationError, normalize_upload

    with pytest.raises(ImageValidationError, match="20"):
        normalize_upload(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_BYTES, "image/png")


def test_effective_upload_limit_is_shared_with_normalization(monkeypatch):
    from app.design_image import file_service

    monkeypatch.setattr(
        file_service.get_settings(), "DESIGN_IMAGE_MAX_UPLOAD_MB", 2
    )
    assert file_service.effective_max_upload_bytes() == 2 * 1024 * 1024
    with pytest.raises(file_service.ImageValidationError, match="2MiB"):
        file_service.normalize_upload(
            b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024),
            "image/png",
        )


def test_normalize_upload_rejects_pixel_bomb_from_header_before_decode(monkeypatch):
    from app.design_image import file_service

    decoded = False
    original_load = Image.Image.load

    def tracking_load(self, *args, **kwargs):
        nonlocal decoded
        decoded = True
        return original_load(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "load", tracking_load)
    with pytest.raises(file_service.ImageValidationError, match="60"):
        file_service.normalize_upload(_png_with_dimensions(10_000, 7_000), "image/png")
    assert decoded is False


def test_normalize_upload_applies_exif_orientation_and_strips_metadata():
    from app.design_image.file_service import normalize_upload

    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private description"

    normalized = normalize_upload(_image_bytes("JPEG", (40, 20), exif=exif), "image/jpeg")

    assert (normalized.width, normalized.height) == (20, 40)
    with Image.open(io.BytesIO(normalized.content)) as result:
        assert result.getexif().get(274) is None
        assert result.getexif().get(270) is None


def test_normalize_upload_strips_png_text_and_downscales_longest_edge():
    from app.design_image.file_service import normalize_upload

    normalized = normalize_upload(
        _image_bytes("PNG", (4096, 1024), png_text=True), "image/png"
    )

    assert (normalized.width, normalized.height) == (2048, 512)
    with Image.open(io.BytesIO(normalized.content)) as result:
        assert "private-note" not in result.info


def test_save_private_image_uses_uuid_paths_thumbnail_and_atomic_replace(
    monkeypatch, tmp_path
):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    normalized = file_service.normalize_upload(_image_bytes("PNG", (800, 400)), "image/png")
    actual_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def tracking_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        actual_replace(source, destination)

    monkeypatch.setattr(file_service.os, "replace", tracking_replace)
    stored = file_service.save_private_image(
        normalized, owner_user_id=42, kind="upload"
    )

    assert stored.relative_path.startswith("42/upload/")
    assert stored.thumbnail_relative_path.startswith("42/upload/")
    assert Path(stored.relative_path).is_absolute() is False
    assert Path(stored.relative_path).stem.endswith("_thumb") is False
    assert Path(stored.thumbnail_relative_path).stem.endswith("_thumb")
    assert len(Path(stored.relative_path).stem) == 32
    int(Path(stored.relative_path).stem, 16)
    assert stored.mime_type == "image/png"
    assert stored.file_size == len(normalized.content)
    assert stored.sha256 == normalized.sha256
    assert file_service.resolve_private_path(stored.relative_path).read_bytes() == normalized.content
    with Image.open(file_service.resolve_private_path(stored.thumbnail_relative_path)) as thumb:
        assert max(thumb.size) <= 320
    assert len(replacements) == 2
    assert all(source.parent == destination.parent for source, destination in replacements)
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("relative_path", ["../secret.txt", "/absolute.txt", "C:/escape.txt", ""])
def test_resolve_and_delete_reject_unsafe_paths(monkeypatch, tmp_path, relative_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path / "private"))
    with pytest.raises(file_service.ImageStorageError):
        file_service.resolve_private_path(relative_path)
    with pytest.raises(file_service.ImageStorageError):
        file_service.delete_private_file(relative_path)


def test_resolve_and_delete_reject_symlink_escape(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    root = tmp_path / "private"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"symlink creation unavailable: {exc}")
        # Windows directory junctions exercise Path.resolve's reparse-point boundary
        # without requiring the Developer Mode privilege needed by os.symlink.
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as junction_exc:
            pytest.skip(f"symlink/junction creation unavailable: {junction_exc}")
    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(root))

    with pytest.raises(file_service.ImageStorageError):
        file_service.resolve_private_path("link/secret.txt")
    with pytest.raises(file_service.ImageStorageError):
        file_service.delete_private_file("link/secret.txt")
    assert (outside / "secret.txt").exists()


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )


def test_storage_boundary_validation_rejects_reparse_root_and_existing_component(
    monkeypatch, tmp_path
):
    from app.core.config import get_settings
    from app.design_image import file_service

    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-root"
    _make_directory_link(linked_root, outside)
    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(linked_root))
    with pytest.raises(file_service.ImageStorageError, match="reparse"):
        file_service.validate_storage_boundary()

    real_root = tmp_path / "private"
    real_root.mkdir()
    _make_directory_link(real_root / "linked-child", outside)
    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(real_root))
    with pytest.raises(file_service.ImageStorageError, match="reparse"):
        file_service.validate_storage_boundary("linked-child/image.png")


def test_storage_boundary_validation_checks_existing_anchor_and_parent(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    root = tmp_path / "private"
    root.mkdir()
    checked: list[Path] = []
    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(root))
    monkeypatch.setattr(
        file_service,
        "_is_reparse_point",
        lambda path: checked.append(path) or False,
    )
    file_service.validate_storage_boundary()
    assert Path(root.anchor) in checked
    assert root.parent in checked
    assert root in checked


def test_storage_operations_hold_one_lock_across_validation_and_write(
    monkeypatch, tmp_path
):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    normalized = file_service.normalize_upload(_image_bytes("PNG"), "image/png")
    victim = tmp_path / "42" / "upload" / "victim.png"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"victim")
    entered_write = threading.Event()
    release_write = threading.Event()
    delete_started = threading.Event()
    delete_finished = threading.Event()
    actual_write = file_service._write_atomic
    calls = 0

    def blocking_write(target, content):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered_write.set()
            assert release_write.wait(2)
        return actual_write(target, content)

    monkeypatch.setattr(file_service, "_write_atomic", blocking_write)
    writer = threading.Thread(
        target=file_service.save_private_image,
        args=(normalized,),
        kwargs={"owner_user_id": 42, "kind": "upload"},
    )

    def delete_victim():
        delete_started.set()
        file_service.delete_private_file("42/upload/victim.png")
        delete_finished.set()

    deleter = threading.Thread(target=delete_victim)
    writer.start()
    assert entered_write.wait(2)
    deleter.start()
    assert delete_started.wait(2)
    assert not delete_finished.wait(0.1)
    release_write.set()
    writer.join(2)
    deleter.join(2)
    assert delete_finished.is_set()
    assert not victim.exists()


def test_write_failure_is_not_masked_by_temporary_cleanup_failure(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    normalized = file_service.normalize_upload(_image_bytes("PNG"), "image/png")

    class FailingHandle:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def write(self, content):
            raise OSError("write failed")

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: FailingHandle())
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")))
    with pytest.raises(OSError, match="write failed"):
        file_service.save_private_image(normalized, owner_user_id=42, kind="upload")


def test_replace_failure_is_not_masked_by_temporary_cleanup_failure(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    normalized = file_service.normalize_upload(_image_bytes("PNG"), "image/png")
    monkeypatch.setattr(file_service.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("replace failed")))
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")))
    with pytest.raises(OSError, match="replace failed"):
        file_service.save_private_image(normalized, owner_user_id=42, kind="upload")


def test_thumbnail_failure_is_not_masked_by_original_rollback_failure(monkeypatch, tmp_path):
    from app.core.config import get_settings
    from app.design_image import file_service

    monkeypatch.setattr(get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    normalized = file_service.normalize_upload(_image_bytes("PNG"), "image/png")
    monkeypatch.setattr(file_service, "_thumbnail_content", lambda *args: (_ for _ in ()).throw(OSError("thumbnail failed")))
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("rollback failed")))
    with pytest.raises(OSError, match="thumbnail failed"):
        file_service.save_private_image(normalized, owner_user_id=42, kind="upload")


def test_successful_replace_ignores_stale_temp_cleanup_failure(monkeypatch, tmp_path):
    from app.design_image import file_service

    source = tmp_path / "source.tmp"
    target = tmp_path / "target.png"
    source.write_bytes(b"content")
    monkeypatch.setattr(file_service.os, "replace", shutil.copyfile)
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed")))
    file_service._write_atomic(target, b"content")
    assert target.read_bytes() == b"content"


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = headers or {}
        self.closed = False
        self.timeouts: list[float] = []

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)

    def close(self) -> None:
        self.closed = True

    def set_timeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


def test_provider_download_requires_https_explicit_allowlist_and_no_credentials():
    from app.design_image.file_service import ProviderDownloadError, download_provider_image

    for url in (
        "http://cdn.example.com/image.png",
        "https://other.example.com/image.png",
        "https://user:password@cdn.example.com/image.png",
    ):
        with pytest.raises(ProviderDownloadError):
            download_provider_image(url, allowed_hosts={"cdn.example.com"})


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.example.com:8443/image.png",
        "https://cdn.example.com:80/image.png",
        "https://cdn.example.com:0/image.png",
    ],
)
def test_provider_download_rejects_non_443_port_before_dns(monkeypatch, url):
    from app.design_image import file_service

    monkeypatch.setattr(
        file_service,
        "_resolve_host_ips",
        lambda *args: pytest.fail("non-443 URL must fail before DNS"),
    )
    with pytest.raises(file_service.ProviderDownloadError, match="443"):
        file_service.download_provider_image(url, allowed_hosts={"cdn.example.com"})


def test_provider_download_rejects_redirect_to_non_443_port(monkeypatch):
    from app.design_image import file_service

    first = _FakeResponse(
        302, headers={"Location": "https://cdn.example.com:8443/final.png"}
    )
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda *args: first)
    with pytest.raises(file_service.ProviderDownloadError, match="443"):
        file_service.download_provider_image(
            "https://cdn.example.com/start", allowed_hosts={"cdn.example.com"}
        )
    assert first.closed


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "192.0.2.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
    ],
)
def test_provider_download_rejects_non_global_dns_results(monkeypatch, address):
    from app.design_image import file_service

    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: [address])
    with pytest.raises(file_service.ProviderDownloadError, match="address"):
        file_service.download_provider_image(
            "https://cdn.example.com/image.png", allowed_hosts={"cdn.example.com"}
        )


def test_provider_download_validates_every_redirect_hop(monkeypatch):
    from app.design_image import file_service

    resolutions: list[str] = []
    responses = iter(
        [
            _FakeResponse(302, headers={"Location": "https://assets.example.com/final.png"}),
            _FakeResponse(200, b"image-data", {"Content-Length": "10"}),
        ]
    )

    def resolve(host, port, deadline):
        resolutions.append(host)
        return ["93.184.216.34"]

    monkeypatch.setattr(file_service, "_resolve_host_ips", resolve)
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip, timeout: next(responses))

    assert file_service.download_provider_image(
        "https://cdn.example.com/start", allowed_hosts={"cdn.example.com", "assets.example.com"}
    ) == b"image-data"
    assert resolutions == ["cdn.example.com", "assets.example.com"]


def test_provider_download_rejects_redirect_to_unlisted_or_private_host(monkeypatch):
    from app.design_image import file_service

    first = _FakeResponse(302, headers={"Location": "https://internal.example/final"})
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip, timeout: first)

    with pytest.raises(file_service.ProviderDownloadError):
        file_service.download_provider_image(
            "https://cdn.example.com/start", allowed_hosts={"cdn.example.com"}
        )
    assert first.closed


def test_provider_download_binds_connection_to_the_validated_ip(monkeypatch):
    from app.design_image import file_service

    resolver_calls = 0
    pinned: list[str] = []

    def rebinding_resolver(host, port, deadline):
        nonlocal resolver_calls
        resolver_calls += 1
        return ["93.184.216.34"] if resolver_calls == 1 else ["127.0.0.1"]

    def open_pinned(url, validated_ip, timeout):
        pinned.append(validated_ip)
        return _FakeResponse(200, b"safe")

    monkeypatch.setattr(file_service, "_resolve_host_ips", rebinding_resolver)
    monkeypatch.setattr(file_service, "_open_pinned_https", open_pinned)

    assert file_service.download_provider_image(
        "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
    ) == b"safe"
    assert resolver_calls == 1
    assert pinned == ["93.184.216.34"]


def test_pinned_transport_connects_to_ip_but_keeps_hostname_for_tls(monkeypatch):
    from app.design_image import file_service

    calls: dict[str, object] = {}

    class FakeRawSocket:
        closed = False

        def close(self):
            self.closed = True

    class FakeTlsSocket:
        def makefile(self, *args, **kwargs):
            return io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

        def sendall(self, data):
            calls["request"] = data

        def close(self):
            pass

    class FakeContext:
        def wrap_socket(self, raw, *, server_hostname):
            calls["server_hostname"] = server_hostname
            return FakeTlsSocket()

    raw_socket = FakeRawSocket()

    def create_connection(address, timeout=None):
        calls["address"] = address
        calls["connect_timeout"] = timeout
        return raw_socket

    context = FakeContext()
    monkeypatch.setattr(file_service.socket, "create_connection", create_connection)
    # Avoid depending on real TLS while asserting the security-relevant connect target/SNI split.
    monkeypatch.setattr(
        file_service.ssl,
        "create_default_context",
        lambda: calls.setdefault("default_context", True) and context,
    )

    response = file_service._open_pinned_https(
        "https://cdn.example.com/image?q=1",
        "93.184.216.34",
        time.monotonic() + 12.5,
    )
    response.close()

    assert calls["default_context"] is True
    assert calls["address"] == ("93.184.216.34", 443)
    assert calls["connect_timeout"] == pytest.approx(12.5, abs=0.1)
    assert calls["server_hostname"] == "cdn.example.com"
    request = calls["request"]
    assert b"Host: cdn.example.com" in request
    assert b"Authorization:" not in request


def test_pinned_transport_closes_raw_socket_when_tls_wrap_fails(monkeypatch):
    from app.design_image import file_service

    class FakeRawSocket:
        closed = False

        def close(self):
            self.closed = True

    class FailingContext:
        def wrap_socket(self, raw, *, server_hostname):
            assert server_hostname == "cdn.example.com"
            raise ssl.SSLError("TLS failed")

    raw_socket = FakeRawSocket()
    monkeypatch.setattr(file_service.socket, "create_connection", lambda *args, **kwargs: raw_socket)
    monkeypatch.setattr(file_service.ssl, "create_default_context", FailingContext)
    with pytest.raises(ssl.SSLError, match="TLS failed"):
        file_service._open_pinned_https(
            "https://cdn.example.com/image", "93.184.216.34", time.monotonic() + 10
        )
    assert raw_socket.closed


def test_pinned_transport_closes_connection_when_request_fails(monkeypatch):
    from app.design_image import file_service

    class FakeConnection:
        closed = False

        def request(self, *args, **kwargs):
            raise OSError("request failed")

        def close(self):
            self.closed = True
            raise OSError("close failed")

        abort = close

    connection = FakeConnection()
    monkeypatch.setattr(file_service, "_PinnedHTTPSConnection", lambda *args, **kwargs: connection)
    with pytest.raises(OSError, match="request failed"):
        file_service._open_pinned_https(
            "https://cdn.example.com/image", "93.184.216.34", time.monotonic() + 10
        )
    assert connection.closed


def test_provider_download_enforces_total_deadline_across_slow_chunks(monkeypatch):
    from app.design_image import file_service

    ticks = iter([100.0, 101.0, 131.0])
    response = _FakeResponse(200, b"first chunk")
    monkeypatch.setattr(file_service.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])

    def open_pinned(url, ip, deadline):
        assert deadline == pytest.approx(130.0)
        return response

    monkeypatch.setattr(file_service, "_open_pinned_https", open_pinned)
    with pytest.raises(file_service.ProviderDownloadError, match="deadline"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.timeouts == [pytest.approx(29.0)]
    assert response.closed


def _fallback_release(event: threading.Event) -> threading.Timer:
    timer = threading.Timer(0.4, event.set)
    timer.daemon = True
    timer.start()
    return timer


def test_provider_download_deadline_bounds_blocked_dns(monkeypatch):
    from app.design_image import file_service

    blocked = threading.Event()
    release = threading.Event()

    def blocked_getaddrinfo(*args, **kwargs):
        blocked.set()
        release.wait(1)
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(file_service, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(file_service.socket, "getaddrinfo", blocked_getaddrinfo)
    fallback = _fallback_release(release)
    started = time.perf_counter()
    try:
        with pytest.raises(file_service.ProviderDownloadError, match="deadline"):
            file_service.download_provider_image(
                "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
            )
        assert blocked.wait(0.1)
        assert time.perf_counter() - started < 0.2
    finally:
        release.set()
        fallback.cancel()


def test_provider_download_watchdog_interrupts_blocked_response_headers(monkeypatch):
    from app.design_image import file_service

    release = threading.Event()

    class BlockingConnection:
        closed = False
        sock = None

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            release.wait(1)
            raise OSError("headers interrupted")

        def close(self):
            self.closed = True
            release.set()

        abort = close

    connection = BlockingConnection()
    monkeypatch.setattr(file_service, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_PinnedHTTPSConnection", lambda *args, **kwargs: connection)
    fallback = _fallback_release(release)
    started = time.perf_counter()
    try:
        with pytest.raises(file_service.ProviderDownloadError):
            file_service.download_provider_image(
                "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
            )
        assert time.perf_counter() - started < 0.2
        assert connection.closed
    finally:
        release.set()
        fallback.cancel()


def test_provider_download_watchdog_interrupts_one_blocked_body_read(monkeypatch):
    from app.design_image import file_service

    release = threading.Event()

    class FakeSocket:
        def settimeout(self, timeout):
            pass

    class BlockingResponse:
        status = 200
        headers = {}

        def read(self, amount=-1):
            release.wait(1)
            raise OSError("body interrupted")

        def close(self):
            pass

    class BlockingConnection:
        closed = False
        sock = FakeSocket()

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return BlockingResponse()

        def close(self):
            self.closed = True
            release.set()

        abort = close

    connection = BlockingConnection()
    monkeypatch.setattr(file_service, "DOWNLOAD_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_PinnedHTTPSConnection", lambda *args, **kwargs: connection)
    fallback = _fallback_release(release)
    started = time.perf_counter()
    try:
        with pytest.raises(file_service.ProviderDownloadError):
            file_service.download_provider_image(
                "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
            )
        assert time.perf_counter() - started < 0.2
        assert connection.closed
    finally:
        release.set()
        fallback.cancel()


def _fallback_close_socket(sock: socket.socket) -> threading.Timer:
    def close_peer():
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    timer = threading.Timer(0.4, close_peer)
    timer.daemon = True
    timer.start()
    return timer


def test_hard_abort_is_idempotent_and_ignores_shutdown_error():
    from app.design_image import file_service

    class CountingSocket:
        shutdowns = 0
        closes = 0

        def shutdown(self, how):
            assert how == socket.SHUT_RDWR
            self.shutdowns += 1
            raise OSError("already disconnected")

        def close(self):
            self.closes += 1

    connection = file_service._PinnedHTTPSConnection(
        "cdn.example.com", "93.184.216.34", port=443, timeout=1
    )
    connection.sock = CountingSocket()
    connection.abort()
    connection.abort()
    assert connection.sock.shutdowns == 1
    assert connection.sock.closes == 1


def test_hard_abort_interrupts_real_http_response_header_read():
    from app.design_image import file_service

    client, peer = socket.socketpair()
    connection = file_service._PinnedHTTPSConnection(
        "cdn.example.com", "93.184.216.34", port=443, timeout=1
    )
    connection.sock = client
    response = http.client.HTTPResponse(client)
    watchdog = file_service._DeadlineWatchdog(
        time.monotonic() + 0.05, connection.abort
    )
    fallback = _fallback_close_socket(peer)
    started = time.perf_counter()
    try:
        with pytest.raises((OSError, http.client.HTTPException)):
            response.begin()
        assert time.perf_counter() - started < 0.2
    finally:
        watchdog.cancel()
        response.close()
        fallback.cancel()
        peer.close()
        connection.abort()


def test_hard_abort_interrupts_real_makefile_body_read():
    from app.design_image import file_service

    client, peer = socket.socketpair()
    connection = file_service._PinnedHTTPSConnection(
        "cdn.example.com", "93.184.216.34", port=443, timeout=1
    )
    connection.sock = client
    reader = client.makefile("rb")
    watchdog = file_service._DeadlineWatchdog(
        time.monotonic() + 0.05, connection.abort
    )
    fallback = _fallback_close_socket(peer)
    started = time.perf_counter()
    try:
        try:
            assert reader.read(1) == b""
        except OSError:
            pass
        assert time.perf_counter() - started < 0.2
    finally:
        watchdog.cancel()
        reader.close()
        fallback.cancel()
        peer.close()
        connection.abort()


def test_dns_future_is_cancelled_when_deadline_expires_after_submit(monkeypatch):
    from app.design_image import file_service

    class PendingFuture:
        cancelled = False

        def result(self, timeout):
            pytest.fail("expired deadline must prevent result wait")

        def cancel(self):
            self.cancelled = True

    future = PendingFuture()

    class Resolver:
        def submit(self, *args, **kwargs):
            return future

    remaining = iter([1.0, file_service.ProviderDownloadError("deadline exceeded")])

    def remaining_time(deadline):
        value = next(remaining)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(file_service, "_DNS_RESOLVER", Resolver())
    monkeypatch.setattr(file_service, "_remaining_download_time", remaining_time)
    with pytest.raises(file_service.ProviderDownloadError, match="deadline"):
        file_service._resolve_host_ips("cdn.example.com", 443, 123.0)
    assert future.cancelled


def test_provider_download_translates_read_timeout_and_closes(monkeypatch):
    from app.design_image import file_service

    class TimeoutResponse(_FakeResponse):
        def read(self, amount=-1):
            raise TimeoutError("slow read")

        def close(self):
            self.closed = True
            raise RuntimeError("close failed")

    response = TimeoutResponse(200)
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda *args: response)
    with pytest.raises(file_service.ProviderDownloadError, match="timed out"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.closed


def test_provider_download_limits_stream_without_content_length(monkeypatch):
    from app.design_image import file_service

    response = _FakeResponse(200, b"x" * (MAX_BYTES + 1))
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip, timeout: response)

    with pytest.raises(file_service.ProviderDownloadError, match="20"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.closed


def test_provider_download_rejects_large_content_length_before_read(monkeypatch):
    from app.design_image import file_service

    response = _FakeResponse(200, b"", {"Content-Length": str(MAX_BYTES + 1)})
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip, timeout: response)

    with pytest.raises(file_service.ProviderDownloadError, match="20"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.closed


def test_provider_download_caps_redirect_count(monkeypatch):
    from app.design_image import file_service

    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(
        file_service,
        "_open_pinned_https",
        lambda url, ip, timeout: _FakeResponse(302, headers={"Location": "/again"}),
    )

    with pytest.raises(file_service.ProviderDownloadError, match="redirect"):
        file_service.download_provider_image(
            "https://cdn.example.com/start", allowed_hosts={"cdn.example.com"}
        )
