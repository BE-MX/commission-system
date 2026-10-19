"""视频播放版与首帧海报：ffmpeg / ffprobe 封装。

原件始终保留；播放版统一为浏览器可解码的 H.264 + faststart，海报为 JPEG 首帧。
视频上传必须成功生成播放版，避免把客户浏览器无法播放的 HEVC 原件直接交付出去。
本模块只处理本地临时文件，不感知存储 provider。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("commission")

PLAYBACK_CONTENT_TYPE = "video/mp4"
POSTER_CONTENT_TYPE = "image/jpeg"


class TranscodeError(RuntimeError):
    """转码失败。消息可对用户展示，不包含服务器路径或 ffmpeg 原始输出。"""


@dataclass(frozen=True)
class VideoInfo:
    codec: str
    width: int | None
    height: int | None
    duration_seconds: int | None


@dataclass(frozen=True)
class PlaybackResult:
    path: Path
    size: int
    poster_path: Path | None
    poster_size: int | None
    info: VideoInfo


def _binary(setting: str, fallback: str) -> str | None:
    configured = (getattr(get_settings(), setting, "") or fallback).strip()
    if not configured:
        return None
    candidate = Path(configured)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return str(candidate) if candidate.is_file() else None
    return shutil.which(configured)


def ffmpeg_binary() -> str | None:
    return _binary("CUSTOMER_MEDIA_FFMPEG_BIN", "ffmpeg")


def ffprobe_binary() -> str | None:
    return _binary("CUSTOMER_MEDIA_FFPROBE_BIN", "ffprobe")


def available() -> bool:
    return bool(ffmpeg_binary() and ffprobe_binary())


def _run(command: list[str], *, timeout: int | None = None) -> str:
    settings = get_settings()
    try:
        completed = subprocess.run(  # noqa: S603 - 参数由本模块拼装，全部为常量和受控路径
            command,
            capture_output=True,
            text=True,
            timeout=timeout or settings.CUSTOMER_MEDIA_TRANSCODE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError("视频处理超时，请缩短视频后重试") from exc
    except OSError as exc:
        logger.warning("[customer-media] ffmpeg spawn failed: %s", type(exc).__name__)
        print("[customer-media] ffmpeg unavailable", flush=True)
        raise TranscodeError("服务器缺少视频处理组件，请联系管理员") from exc
    if completed.returncode != 0:
        logger.warning("[customer-media] ffmpeg failed code=%s", completed.returncode)
        print(f"[customer-media] ffmpeg failed code={completed.returncode}", flush=True)
        raise TranscodeError("视频转码失败，请确认文件可正常播放后重试")
    return completed.stdout or ""


def probe(path: Path) -> VideoInfo:
    ffprobe = ffprobe_binary()
    if not ffprobe:
        raise TranscodeError("服务器缺少视频处理组件，请联系管理员")
    output = _run([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height:format=duration",
        "-of", "json", str(path),
    ])
    try:
        payload = json.loads(output or "{}")
    except ValueError as exc:
        raise TranscodeError("无法读取视频信息") from exc
    stream = (payload.get("streams") or [{}])[0]
    duration = payload.get("format", {}).get("duration")
    try:
        duration_seconds = int(round(float(duration))) if duration else None
    except (TypeError, ValueError):
        duration_seconds = None
    return VideoInfo(
        codec=str(stream.get("codec_name") or "").strip().lower(),
        width=int(stream["width"]) if stream.get("width") else None,
        height=int(stream["height"]) if stream.get("height") else None,
        duration_seconds=duration_seconds,
    )


def build_playback(source: Path, target: Path, poster: Path) -> PlaybackResult:
    """把 source 转成可播放的 H.264 MP4（已是 H.264 时只重封装），并输出首帧海报。"""
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        raise TranscodeError("服务器缺少视频处理组件，请联系管理员")
    settings = get_settings()
    info = probe(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    poster.parent.mkdir(parents=True, exist_ok=True)
    if info.codec == "h264":
        # 视频流不重编码；音频统一转 AAC，避免 PCM/AC-3 等浏览器不支持的音轨。
        codec_args = ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k"]
    else:
        codec_args = [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(settings.CUSTOMER_MEDIA_PLAYBACK_CRF),
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "128k",
        ]
    try:
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
              *codec_args, "-movflags", "+faststart", str(target)])
        if not target.is_file() or target.stat().st_size <= 0:
            raise TranscodeError("视频转码失败，请确认文件可正常播放后重试")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    poster_size = _build_poster_safely(ffmpeg, target, poster, info.duration_seconds, settings.CUSTOMER_MEDIA_POSTER_MAX_WIDTH)
    return PlaybackResult(
        path=target, size=target.stat().st_size,
        poster_path=poster if poster_size else None,
        poster_size=poster_size,
        info=info,
    )


def _build_poster_safely(ffmpeg: str, target: Path, poster: Path, duration: int | None, max_width: int) -> int:
    """海报只是增强项：失败时保留播放版，不让整个上传失败。"""
    try:
        return _build_poster(ffmpeg, target, poster, duration, max_width)
    except Exception as exc:  # noqa: BLE001 - 任何海报失败都不应阻断视频交付
        logger.warning("[customer-media] poster generation skipped: %s", type(exc).__name__)
        print("[customer-media] poster generation skipped", flush=True)
        poster.unlink(missing_ok=True)
        return 0


def _build_poster(ffmpeg: str, target: Path, poster: Path, duration: int | None, max_width: int) -> int:
    seek = "1" if duration is None or duration > 1 else "0"
    scale = f"scale={max_width}:-2"
    try:
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-ss", seek, "-i", str(target), "-frames:v", "1",
              "-vf", scale, "-q:v", "4", str(poster)])
    except TranscodeError:
        # 时长不足或定位失败时退回第一帧再试一次。
        poster.unlink(missing_ok=True)
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
              "-i", str(target), "-frames:v", "1", "-vf", scale, "-q:v", "4", str(poster)])
    if not poster.is_file() or poster.stat().st_size <= 0:
        poster.unlink(missing_ok=True)
        return 0
    return poster.stat().st_size
