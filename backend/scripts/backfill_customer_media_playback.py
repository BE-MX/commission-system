"""回填客户素材视频的 H.264 播放版与首帧海报（原件保留）。

适用场景：视频在转码功能上线前上传（例如 HEVC 原件），客户浏览器无法播放。

执行方式（在 backend 目录、装有 ffmpeg 的机器上）：
  python -m scripts.backfill_customer_media_playback            # 只列出待处理项
  python -m scripts.backfill_customer_media_playback --apply    # 实际转码并写回存储/数据库

默认 dry-run；每个素材单独提交，失败只影响自身并返回非零退出码。
"""

import argparse
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

import app.auth.models  # noqa: F401 - 注册 ark_users，否则 uploaded_by 外键在首次 flush 时无法解析
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.storage.cos import ObjectMissing
from app.customer_media import storage, transcode
from app.customer_media.models import CustomerMediaAsset


def pending_assets(db, asset_ids, force):
    statement = select(CustomerMediaAsset).where(
        CustomerMediaAsset.deleted_at.is_(None),
        CustomerMediaAsset.media_type == "video",
    ).order_by(CustomerMediaAsset.id)
    if asset_ids:
        statement = statement.where(CustomerMediaAsset.id.in_(asset_ids))
    rows = list(db.scalars(statement))
    if force:
        return rows
    return [row for row in rows if not row.playback_key]


def _download_original(asset, destination: Path) -> None:
    media = storage.storage_for(asset.storage_provider)
    if asset.storage_provider == "local":
        shutil.copy2(media.resolve(asset.object_key), destination)
        return
    media.store.download(asset.object_key, destination,
                         max_bytes=asset.file_size + 1024 * 1024, expected_sha256=asset.sha256)


def _publish(asset, key: str, path: Path, content_type: str) -> int:
    """写入派生对象；键已存在且大小一致时复用，保持幂等（COS 禁止覆盖同名对象）。"""
    media = storage.storage_for(asset.storage_provider)
    expected = path.stat().st_size
    if asset.storage_provider == "local":
        target = media.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        return target.stat().st_size
    try:
        existing = media.store.head(key)
    except ObjectMissing:
        pass
    else:
        remote_size = int(existing.get("Content-Length", 0))
        if remote_size != expected:
            raise RuntimeError(
                f"已存在的派生对象大小不符（{remote_size} != {expected}），可能是上次中断的残留；"
                "请加 --force 重新生成"
            )
        return remote_size
    return media.store.put_file(key, path, content_type).size


def _versioned(key: str) -> str:
    """--force 时改用新键，避免先删旧对象导致数据库短时间指向 404。"""
    path = Path(key)
    return str(path.with_name(f"{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}")).replace("\\", "/")


def process(db, asset, *, apply: bool, force: bool) -> dict:
    playback_key, thumbnail_key = storage.derivative_keys(asset.object_key)
    previous = [key for key in (asset.playback_key, asset.thumbnail_key) if key]
    if force:
        playback_key, thumbnail_key = _versioned(playback_key), _versioned(thumbnail_key)
    outcome = {
        "asset_id": asset.id, "file_name": asset.file_name,
        "playback_key": playback_key, "thumbnail_key": thumbnail_key,
        "playback_size": None, "poster_size": None,
        "duration_seconds": asset.duration_seconds, "applied": False,
    }
    if not apply:
        return outcome
    with tempfile.TemporaryDirectory(prefix="media-playback-", dir=_workdir()) as folder:
        workspace = Path(folder)
        source = workspace / f"source{Path(asset.object_key).suffix}"
        playback = workspace / "playback.mp4"
        poster = workspace / "poster.jpg"
        _download_original(asset, source)
        result = transcode.build_playback(source, playback, poster)
        info = transcode.probe(playback)
        if info.codec != "h264":
            raise RuntimeError(f"转码结果不是 H.264（{info.codec}）")
        if result.poster_path is None:
            raise RuntimeError("未能生成首帧海报")
        published: list[str] = []
        try:
            published.append(playback_key)
            playback_size = _publish(asset, playback_key, playback, transcode.PLAYBACK_CONTENT_TYPE)
            published.append(thumbnail_key)
            poster_size = _publish(asset, thumbnail_key, poster, transcode.POSTER_CONTENT_TYPE)
        except Exception:
            # 数据库尚未指向新对象，失败时回收本次写入，避免永久孤儿。
            for key in published:
                try:
                    storage.storage_for(asset.storage_provider).delete(key)
                except Exception:  # noqa: BLE001 - 清理失败不覆盖原始错误
                    print(f"  [{asset.id}] 待清理孤儿：{key}", flush=True)
            raise
    asset.playback_key = playback_key
    asset.playback_size = playback_size
    asset.thumbnail_key = thumbnail_key
    if asset.duration_seconds is None:
        asset.duration_seconds = info.duration_seconds
    db.commit()
    # 数据库已指向新键，再清理旧派生对象；失败只留下可回收孤儿。
    for key in previous:
        if key in (playback_key, thumbnail_key):
            continue
        try:
            storage.storage_for(asset.storage_provider).delete(key)
        except Exception:  # noqa: BLE001 - 旧对象清理失败不影响新版本可用
            print(f"  [{asset.id}] 旧派生对象待清理：{key}", flush=True)
    outcome.update(
        playback_size=playback_size, poster_size=poster_size,
        duration_seconds=info.duration_seconds, applied=True,
    )
    return outcome


def _workdir() -> str:
    root = Path(get_settings().COS_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="回填客户素材视频播放版与海报")
    parser.add_argument("--apply", action="store_true", help="实际转码并写入存储与数据库（默认只预览）")
    parser.add_argument("--asset-id", type=int, action="append", default=None, help="只处理指定素材 ID，可重复")
    parser.add_argument("--force", action="store_true", help="已有播放版的素材也重新生成")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个素材")
    args = parser.parse_args(argv)

    if args.apply and not transcode.available():
        print("ffmpeg/ffprobe 不可用，无法转码；请先安装后再执行 --apply", flush=True)
        return 2

    db = SessionLocal()
    try:
        rows = pending_assets(db, args.asset_id, args.force)
        if args.limit:
            rows = rows[: args.limit]
        if not rows:
            print("没有需要处理的视频素材", flush=True)
            return 0
        print(f"待处理视频素材 {len(rows)} 个，模式={'apply' if args.apply else 'dry-run'}", flush=True)
        failures = 0
        for asset in rows:
            try:
                outcome = process(db, asset, apply=args.apply, force=args.force)
                if outcome["applied"]:
                    print(
                        f"  [{outcome['asset_id']}] {outcome['file_name']} -> {outcome['playback_key']} "
                        f"({outcome['playback_size']} bytes, {outcome['duration_seconds']}s)",
                        flush=True,
                    )
                else:
                    print(
                        f"  [{outcome['asset_id']}] {outcome['file_name']} 计划写入 "
                        f"{outcome['playback_key']} / {outcome['thumbnail_key']} [dry-run]",
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - 单个失败不阻断其余素材
                db.rollback()
                failures += 1
                print(f"  [{asset.id}] {asset.file_name} 失败：{exc}", flush=True)
        print(f"完成：成功 {len(rows) - failures}，失败 {failures}", flush=True)
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
