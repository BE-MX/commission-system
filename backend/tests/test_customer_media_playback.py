"""客户素材视频：播放版/海报对象键、变体读取与上传转码联动。"""

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.customer_media import service, storage, transcode
from app.customer_media.models import CustomerMediaAsset
from app.customer_media.router import _asset


def _fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2" + b"\x00" * 64


def _fake_result(target, poster, *, codec="hevc", duration=16):
    target.write_bytes(b"h264-playback")
    poster.write_bytes(b"jpeg-poster")
    return transcode.PlaybackResult(
        path=target, size=target.stat().st_size,
        poster_path=poster, poster_size=poster.stat().st_size,
        info=transcode.VideoInfo(codec=codec, width=1080, height=1920, duration_seconds=duration),
    )


def test_derivative_keys_sit_next_to_the_original_batch():
    playback, poster = storage.derivative_keys("customers/C1/batches/11/originals/abc.mp4")
    assert playback == "customers/C1/batches/11/playback/abc.mp4"
    assert poster == "customers/C1/batches/11/thumbnails/abc.jpg"


def test_variant_falls_back_to_original_and_poster_requires_a_key():
    asset = SimpleNamespace(object_key="originals/a.mp4", content_type="video/mp4",
                            playback_key=None, thumbnail_key=None)
    assert storage._variant_object(asset, None) == ("originals/a.mp4", "video/mp4")
    assert storage._variant_object(asset, "playback") == ("originals/a.mp4", "video/mp4")
    with pytest.raises(HTTPException) as raised:
        storage._variant_object(asset, "poster")
    assert raised.value.status_code == 404

    ready = SimpleNamespace(object_key="originals/a.mp4", content_type="video/quicktime",
                            playback_key="playback/a.mp4", thumbnail_key="thumbnails/a.jpg")
    assert storage._variant_object(ready, "playback") == ("playback/a.mp4", "video/mp4")
    assert storage._variant_object(ready, "poster") == ("thumbnails/a.jpg", "image/jpeg")


def test_video_upload_builds_playback_and_poster(tmp_path, monkeypatch):
    def fake_build(source, target, poster):
        assert source.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
        return _fake_result(target, poster)

    monkeypatch.setattr(transcode, "build_playback", fake_build)
    local = storage.LocalMediaStorage(tmp_path)
    stored = asyncio.run(local.save_upload(
        UploadFile(BytesIO(_fake_mp4()), filename="clip.mp4"),
        customer_id="C1", batch_id=2, max_bytes=1024 * 1024,
    ))
    stem = stored.object_key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    assert stored.playback_key == f"customers/C1/batches/2/playback/{stem}.mp4"
    assert stored.thumbnail_key == f"customers/C1/batches/2/thumbnails/{stem}.jpg"
    assert stored.playback_size == len(b"h264-playback")
    assert stored.duration_seconds == 16
    assert local.resolve(stored.playback_key).read_bytes() == b"h264-playback"
    assert local.resolve(stored.thumbnail_key).read_bytes() == b"jpeg-poster"


def test_transcode_failure_rejects_the_upload_and_removes_partial_file(tmp_path, monkeypatch):
    def failing(source, target, poster):
        raise transcode.TranscodeError("视频转码失败，请确认文件可正常播放后重试")

    monkeypatch.setattr(transcode, "build_playback", failing)
    local = storage.LocalMediaStorage(tmp_path)
    with pytest.raises(storage.MediaStorageError, match="转码失败"):
        asyncio.run(local.save_upload(
            UploadFile(BytesIO(_fake_mp4()), filename="clip.mp4"),
            customer_id="C1", batch_id=2, max_bytes=1024 * 1024,
        ))
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_cloud_upload_publishes_original_playback_and_poster(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(COS_CACHE_ROOT=str(tmp_path)))
    published = []

    class Store:
        def put_file(self, key, path, content_type):
            from app.core.storage.cos import file_digest, StoredObject
            size, digest = file_digest(path)
            published.append((key, content_type, size))
            return StoredObject(key, size, digest, content_type)

    monkeypatch.setattr(transcode, "build_playback", lambda source, target, poster: _fake_result(target, poster))
    result = asyncio.run(storage.CosMediaStorage(Store()).save_upload(
        UploadFile(BytesIO(_fake_mp4()), filename="clip.mp4"),
        customer_id="C1", batch_id=2, max_bytes=1024 * 1024,
    ))
    assert [item[1] for item in published] == ["video/mp4", "video/mp4", "image/jpeg"]
    assert published[1][0] == result.playback_key
    assert published[2][0] == result.thumbnail_key
    assert result.provider == "cos"
    assert result.playback_path is None and result.thumbnail_path is None


def test_failed_derivative_upload_reclaims_published_objects(tmp_path, monkeypatch):
    from app.core.storage.cos import StorageError, StoredObject

    monkeypatch.setattr(storage, "get_settings", lambda: SimpleNamespace(COS_CACHE_ROOT=str(tmp_path)))
    calls = {"put": 0, "deleted": []}

    class Store:
        def put_file(self, key, path, content_type):
            from app.core.storage.cos import file_digest
            calls["put"] += 1
            if calls["put"] == 2:
                raise StorageError("unavailable")
            size, digest = file_digest(path)
            return StoredObject(key, size, digest, content_type)

        def delete(self, key):
            calls["deleted"].append(key)

    monkeypatch.setattr(transcode, "build_playback", lambda source, target, poster: _fake_result(target, poster))
    with pytest.raises(StorageError):
        asyncio.run(storage.CosMediaStorage(Store()).save_upload(
            UploadFile(BytesIO(_fake_mp4()), filename="clip.mp4"),
            customer_id="C1", batch_id=2, max_bytes=1024 * 1024,
        ))
    # 失败时还没有数据库行：原创对象和试探写入的播放版键都要回收。
    assert len(calls["deleted"]) == 2
    assert "/originals/" in calls["deleted"][0] and "/playback/" in calls["deleted"][1]


def test_missing_playback_file_falls_back_to_original(tmp_path):
    local = storage.LocalMediaStorage(tmp_path)
    key = "customers/C1/batches/2/originals/a.mp4"
    target = local.resolve(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original")
    asset = SimpleNamespace(
        object_key=key, playback_key="customers/C1/batches/2/playback/a.mp4",
        thumbnail_key=None, content_type="video/mp4", file_name="a.mp4",
    )
    response = local.response(asset, variant="playback")
    assert response.media_type == "video/mp4"
    assert str(response.path) == str(target)


def test_missing_cloud_playback_object_serves_original():
    from app.core.storage.cos import ObjectMissing

    class Store:
        def head(self, key):
            if "/playback/" in key:
                raise ObjectMissing("missing")
            return {}

        def download_url(self, key, **kwargs):
            assert "/originals/" in key
            return "https://example.invalid/original"

    asset = SimpleNamespace(
        object_key="customers/C1/batches/2/originals/a.mp4",
        playback_key="customers/C1/batches/2/playback/a.mp4",
        thumbnail_key=None, content_type="video/mp4", file_name="a.mp4",
    )
    response = storage.CosMediaStorage(Store()).response(asset, variant="playback")
    assert response.status_code == 303


def test_asset_payload_exposes_playback_and_poster_urls():
    row = CustomerMediaAsset(
        id=9, file_name="clip.mp4", media_type="video", content_type="video/mp4",
        file_size=10, sha256="a" * 64, storage_provider="cos",
        object_key="customers/C1/batches/2/originals/a.mp4",
        playback_key="customers/C1/batches/2/playback/a.mp4",
        thumbnail_key="customers/C1/batches/2/thumbnails/a.jpg",
        created_at=service.beijing_now(),
    )
    payload = _asset(row)
    assert payload["content_url"].startswith("/api/customer-media/assets/9/content?")
    assert "variant=playback" in payload["playback_url"]
    assert "variant=poster" in payload["poster_url"]

    plain = CustomerMediaAsset(
        id=10, file_name="old.mp4", media_type="video", content_type="video/mp4",
        file_size=10, sha256="b" * 64, storage_provider="cos",
        object_key="customers/C1/batches/2/originals/b.mp4",
        created_at=service.beijing_now(),
    )
    legacy = _asset(plain)
    assert legacy["playback_url"] is None and legacy["poster_url"] is None


def test_preview_urls_carry_signed_variant_without_changing_the_signature():
    url = service.internal_preview_url(9, variant="playback")
    expires = int(url.split("expires=")[1].split("&")[0])
    token = url.split("token=")[1].split("&")[0]
    assert "variant=playback" in url
    assert service.verify_internal_preview(9, expires, token)
    assert not service.verify_internal_preview(10, expires, token)


@pytest.mark.skipif(not transcode.available(), reason="ffmpeg/ffprobe not installed")
def test_video_upload_pipeline_outputs_playable_h264_and_poster(tmp_path):
    """走真实 save_upload：HEVC 输入必须产出 H.264 播放版和可解码海报（临时文件名不能丢扩展名）。"""
    import subprocess

    source = tmp_path / "source.mp4"
    subprocess.run([
        transcode.ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", str(source),
    ], check=True)
    upload = UploadFile(BytesIO(source.read_bytes()), filename="clip.mp4")
    stored = asyncio.run(storage.LocalMediaStorage(tmp_path / "media").save_upload(
        upload, customer_id="C1", batch_id=2, max_bytes=8 * 1024 * 1024,
    ))
    local = storage.LocalMediaStorage(tmp_path / "media")
    playback = local.resolve(stored.playback_key)
    poster = local.resolve(stored.thumbnail_key)
    info = transcode.probe(playback)
    assert info.codec == "h264"
    assert info.width == 320
    assert stored.duration_seconds == 2
    assert poster.read_bytes()[:2] == b"\xff\xd8"
    assert stored.playback_path is None or stored.playback_path.exists()


@pytest.mark.skipif(not transcode.available(), reason="ffmpeg/ffprobe not installed")
def test_real_transcode_outputs_playable_h264_and_poster(tmp_path):
    import subprocess

    source = tmp_path / "source.mp4"
    subprocess.run([
        transcode.ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
    ], check=True)
    target = tmp_path / "playback.mp4"
    poster = tmp_path / "poster.jpg"
    result = transcode.build_playback(source, target, poster)
    info = transcode.probe(target)
    assert info.codec == "h264"
    assert info.width == 320
    assert result.poster_path is not None and result.poster_size > 0
    assert target.read_bytes()[4:8] == b"ftyp"
