from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import struct
import subprocess
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


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = headers or {}
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)

    def close(self) -> None:
        self.closed = True


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

    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda host, port: [address])
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

    def resolve(host, port):
        resolutions.append(host)
        return ["93.184.216.34"]

    monkeypatch.setattr(file_service, "_resolve_host_ips", resolve)
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip: next(responses))

    assert file_service.download_provider_image(
        "https://cdn.example.com/start", allowed_hosts={"cdn.example.com", "assets.example.com"}
    ) == b"image-data"
    assert resolutions == ["cdn.example.com", "assets.example.com"]


def test_provider_download_rejects_redirect_to_unlisted_or_private_host(monkeypatch):
    from app.design_image import file_service

    first = _FakeResponse(302, headers={"Location": "https://internal.example/final"})
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip: first)

    with pytest.raises(file_service.ProviderDownloadError):
        file_service.download_provider_image(
            "https://cdn.example.com/start", allowed_hosts={"cdn.example.com"}
        )
    assert first.closed


def test_provider_download_binds_connection_to_the_validated_ip(monkeypatch):
    from app.design_image import file_service

    resolver_calls = 0
    pinned: list[str] = []

    def rebinding_resolver(host, port):
        nonlocal resolver_calls
        resolver_calls += 1
        return ["93.184.216.34"] if resolver_calls == 1 else ["127.0.0.1"]

    def open_pinned(url, validated_ip):
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
        def close(self):
            pass

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

    monkeypatch.setattr(
        file_service.socket,
        "create_connection",
        lambda address, timeout=None: calls.setdefault("address", address) or FakeRawSocket(),
    )
    # Avoid depending on real TLS while asserting the security-relevant connect target/SNI split.
    monkeypatch.setattr(file_service.ssl, "create_default_context", lambda: FakeContext())

    response = file_service._open_pinned_https(
        "https://cdn.example.com:8443/image?q=1", "93.184.216.34"
    )
    response.close()

    assert calls["address"] == ("93.184.216.34", 8443)
    assert calls["server_hostname"] == "cdn.example.com"
    request = calls["request"]
    assert b"Host: cdn.example.com:8443" in request
    assert b"Authorization:" not in request


def test_provider_download_limits_stream_without_content_length(monkeypatch):
    from app.design_image import file_service

    response = _FakeResponse(200, b"x" * (MAX_BYTES + 1))
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip: response)

    with pytest.raises(file_service.ProviderDownloadError, match="20"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.closed


def test_provider_download_rejects_large_content_length_before_read(monkeypatch):
    from app.design_image import file_service

    response = _FakeResponse(200, b"", {"Content-Length": str(MAX_BYTES + 1)})
    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(file_service, "_open_pinned_https", lambda url, ip: response)

    with pytest.raises(file_service.ProviderDownloadError, match="20"):
        file_service.download_provider_image(
            "https://cdn.example.com/image", allowed_hosts={"cdn.example.com"}
        )
    assert response.closed


def test_provider_download_caps_redirect_count(monkeypatch):
    from app.design_image import file_service

    monkeypatch.setattr(file_service, "_resolve_host_ips", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(
        file_service,
        "_open_pinned_https",
        lambda url, ip: _FakeResponse(302, headers={"Location": "/again"}),
    )

    with pytest.raises(file_service.ProviderDownloadError, match="redirect"):
        file_service.download_provider_image(
            "https://cdn.example.com/start", allowed_hosts={"cdn.example.com"}
        )
