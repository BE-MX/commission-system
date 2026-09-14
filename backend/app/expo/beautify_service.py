"""One-time portrait beautify worker for expo sessions."""

import hashlib
import base64
import logging
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.expo import ai_pipeline
from app.expo.models import ExpoSession


logger = logging.getLogger("commission.expo")
BEAUTY_DIR = ai_pipeline.UPLOAD_ROOT / "beautified"
PREVIEW_DIR = ai_pipeline.UPLOAD_ROOT / "beautify_previews"
PREVIEW_TTL_SECONDS = 24 * 3600


def source_hash(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def start(session_id: int) -> None:
    threading.Thread(target=_run, args=(session_id,), daemon=True).start()


def retry(db: Session, session: ExpoSession) -> ExpoSession:
    if session.photo_processing_mode != "beauty":
        raise ValueError("原照片模式无需美颜")
    if session.beautify_status == "ready":
        return session
    if session.beautify_status in ("pending", "processing"):
        return session
    if session.beautify_status != "failed":
        raise ValueError("当前状态不能重试美颜")
    updated = (db.query(ExpoSession)
               .filter(ExpoSession.id == session.id,
                       ExpoSession.photo_processing_mode == "beauty",
                       ExpoSession.beautify_status == "failed")
               .update({
                   "beautify_status": "pending", "beautify_error_message": None,
                   "beautify_token": None, "beautify_queued_at": beijing_now(),
                   "beautify_started_at": None, "updated_at": beijing_now(),
               }, synchronize_session=False))
    if not updated:
        db.rollback()
        db.refresh(session)
        return session
    db.commit()
    db.refresh(session)
    start(session.id)
    return session


def sweep_preview_files(now: float | None = None) -> None:
    """机会式清理后台测试人像，避免预览图长期暴露在静态 uploads 下。"""
    now = time.time() if now is None else now
    if not PREVIEW_DIR.exists():
        return
    for path in PREVIEW_DIR.iterdir():
        try:
            if path.is_file() and now - path.stat().st_mtime > PREVIEW_TTL_SECONDS:
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("[expo] beautify preview cleanup skipped: %s", path)


def preview(db: Session, upload, prompt_text: str, user_id: int | None) -> dict:
    """Run an admin-only preview without creating an ExpoSession or result row."""
    from app.ai.service import edit_image, get_image_config_snapshot

    suffix = Path(upload.filename or "preview.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("仅支持 jpg / jpeg / png / webp 图片")
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    sweep_preview_files()
    source = PREVIEW_DIR / f"source_{uuid.uuid4().hex}{suffix}"
    output = None
    try:
        with open(source, "wb") as handle:
            from app.expo import upload_service
            remaining = upload_service.MAX_UPLOAD_BYTES + 1
            while remaining:
                chunk = upload.file.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)
        if source.stat().st_size > upload_service.MAX_UPLOAD_BYTES:
            raise ValueError(f"图片不能超过 {upload_service.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
        try:
            from PIL import Image
            with Image.open(source) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("仅支持 jpg / jpeg / png / webp 图片")
                if image.width * image.height > upload_service.MAX_UPLOAD_PIXELS:
                    raise ValueError(
                        f"照片分辨率过高，请压缩后重试（上限约 {upload_service.MAX_UPLOAD_PIXELS // 1_000_000}MP）"
                    )
                image.verify()
        except Exception as exc:  # noqa: BLE001
            raise ValueError("上传文件不是有效图片") from exc
        ai_pipeline.downscale_inplace(source)
        preset_name = get_settings().EXPO_BEAUTIFY_PRESET_NAME
        config = get_image_config_snapshot(db, preset_name)
        result = edit_image(
            db=db, preset_name=preset_name, prompt=prompt_text,
            images=[ai_pipeline._prep_image(source)], caller_module="expo_beautify_preview",
            caller_user_id=user_id,
            expected_config_version={"provider_id": config["provider_id"], "fingerprint": config["fingerprint"]},
            transport_max_attempts=1, transport_allow_parameter_fallback=False,
        )
        output = ai_pipeline.save_ai_image(result, PREVIEW_DIR, "preview")
        mime = {".png": "image/png", ".webp": "image/webp"}.get(output.suffix.lower(), "image/jpeg")
        encoded = base64.b64encode(output.read_bytes()).decode("ascii")
        return {"image_url": f"data:{mime};base64,{encoded}"}
    finally:
        source.unlink(missing_ok=True)
        if output:
            output.unlink(missing_ok=True)


def _run(session_id: int) -> None:
    from app.ai.service import edit_image

    db = SessionLocal()
    token = uuid.uuid4().hex
    started = time.monotonic()
    output = None
    try:
        now = beijing_now()
        claimed = (db.query(ExpoSession)
                   .filter(ExpoSession.id == session_id,
                           ExpoSession.photo_processing_mode == "beauty",
                           ExpoSession.beautify_status == "pending")
                   .update({
                       "beautify_status": "processing", "beautify_token": token,
                       "beautify_attempt": ExpoSession.beautify_attempt + 1,
                       "beautify_started_at": now, "beautify_error_message": None,
                       "updated_at": now,
                   }, synchronize_session=False))
        db.commit()
        if not claimed:
            return
        session = db.get(ExpoSession, session_id)
        snapshot = dict(session.beautify_snapshot or {})
        expected = snapshot.get("image_config") or {}
        result = edit_image(
            db=db,
            preset_name=expected.get("preset_name") or get_settings().EXPO_BEAUTIFY_PRESET_NAME,
            prompt=snapshot.get("prompt_text") or "",
            images=[ai_pipeline._prep_image(ai_pipeline.to_abs(session.photo_path))],
            caller_module="expo_beautify",
            caller_user_id=session.operator_user_id,
            expected_config_version={
                "provider_id": expected.get("provider_id"),
                "fingerprint": expected.get("fingerprint"),
            },
            transport_max_attempts=1,
            transport_allow_parameter_fallback=False,
        )
        output = ai_pipeline.save_ai_image(result, BEAUTY_DIR, f"beauty_{session_id}")
        snapshot["output_hash"] = source_hash(output)
        updated = (db.query(ExpoSession)
                   .filter(ExpoSession.id == session_id,
                           ExpoSession.beautify_status == "processing",
                           ExpoSession.beautify_token == token)
                   .update({
                       "beautified_photo_path": ai_pipeline.to_rel(output),
                       "beautify_snapshot": snapshot,
                       "beautify_status": "ready", "beautify_token": None,
                       "beautify_finished_at": beijing_now(), "beautify_error_message": None,
                       "updated_at": beijing_now(),
                   }, synchronize_session=False))
        db.commit()
        if not updated:
            output.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if output:
            output.unlink(missing_ok=True)
        msg = f"[expo] beautify failed session={session_id} after={int((time.monotonic()-started)*1000)}ms: {type(exc).__name__}: {exc}"
        logger.exception(msg)
        print(msg, flush=True)
        (db.query(ExpoSession)
         .filter(ExpoSession.id == session_id, ExpoSession.beautify_token == token)
         .update({
             "beautify_status": "failed", "beautify_token": None,
             "beautify_error_message": f"{type(exc).__name__}: {str(exc)[:400]}",
             "beautify_finished_at": beijing_now(), "updated_at": beijing_now(),
         }, synchronize_session=False))
        db.commit()
    finally:
        db.close()
