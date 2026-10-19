"""回填脚本：本地存储下的下载/转码/写回与幂等行为。"""

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.customer_media import storage, transcode
from scripts import backfill_customer_media_playback as backfill


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _asset(root: Path, *, source: Path, playback_key=None, thumbnail_key=None):
    relative = "customers/C1/batches/11/originals/abc.mp4"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return SimpleNamespace(
        id=718, file_name="clip.mp4", media_type="video", object_key=relative,
        storage_provider="local", sha256="0" * 64, file_size=target.stat().st_size,
        playback_key=playback_key, thumbnail_key=thumbnail_key, duration_seconds=None,
    )


@pytest.fixture()
def media(tmp_path, monkeypatch):
    root = tmp_path / "media"
    local = storage.LocalMediaStorage(root)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(backfill.storage, "storage_for", lambda provider: local)
    monkeypatch.setattr(backfill, "_workdir", lambda: str(work))
    return local


@pytest.mark.skipif(not transcode.available(), reason="ffmpeg/ffprobe not installed")
def test_dry_run_plans_without_writing(media, tmp_path):
    source = _make_clip(tmp_path)
    asset = _asset(media.root, source=source)
    db = FakeDb()
    outcome = backfill.process(db, asset, apply=False, force=False)
    assert outcome["applied"] is False
    assert outcome["playback_key"].endswith("playback/abc.mp4")
    assert db.commits == 0
    assert not (media.root / "customers/C1/batches/11/playback").exists()


@pytest.mark.skipif(not transcode.available(), reason="ffmpeg/ffprobe not installed")
def test_apply_publishes_playback_and_poster_then_is_idempotent(media, tmp_path):
    source = _make_clip(tmp_path)
    asset = _asset(media.root, source=source)
    db = FakeDb()
    first = backfill.process(db, asset, apply=True, force=False)
    assert first["applied"] is True and first["playback_size"] > 0
    assert asset.playback_key == first["playback_key"]
    assert asset.thumbnail_key == first["thumbnail_key"]
    assert asset.duration_seconds == 2
    assert (media.root / first["playback_key"]).is_file()
    assert (media.root / first["thumbnail_key"]).is_file()
    assert db.commits == 1


@pytest.mark.skipif(not transcode.available(), reason="ffmpeg/ffprobe not installed")
def test_force_uses_new_keys_and_removes_previous_objects(media, tmp_path):
    source = _make_clip(tmp_path)
    asset = _asset(media.root, source=source)
    db = FakeDb()
    first = backfill.process(db, asset, apply=True, force=False)
    old_playback = media.root / first["playback_key"]
    old_poster = media.root / first["thumbnail_key"]
    second = backfill.process(db, asset, apply=True, force=True)
    assert second["playback_key"] != first["playback_key"]
    assert media.root / second["playback_key"] != old_playback
    assert media.root / second["playback_key"] and media.root / second["thumbnail_key"]
    # 数据库先指向新键，旧对象随后清理。
    assert not old_playback.exists() and not old_poster.exists()


def _make_clip(tmp_path: Path) -> Path:
    source = tmp_path / "source.mp4"
    subprocess.run([
        transcode.ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
        "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", str(source),
    ], check=True)
    return source
