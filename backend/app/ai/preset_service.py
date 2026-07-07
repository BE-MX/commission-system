"""AI Preset CRUD + 单条测试"""

import base64
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider
from app.ai.call_service import chat
from app.ai.image_service import edit_image
from app.ai.provider_service import get_provider

MAX_TEST_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_TEST_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
COMPOSITE_PRESET_NAMES = {"expo_wig_composite"}


def _test_error_result(exc: Exception, start: float) -> dict:
    return {
        "status": "error",
        "response": f"{type(exc).__name__}: {str(exc)[:500]}",
        "tokens_used": None,
        "duration_ms": int((time.time() - start) * 1000),
    }


def _image_filename(prefix: str, content_type: str) -> str:
    ext = {
        "image/jpeg": "jpeg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "png")
    return f"{prefix}.{ext}"


def _validate_test_image(image_bytes: bytes, content_type: str) -> Optional[dict]:
    if content_type not in ALLOWED_TEST_IMAGE_TYPES:
        return {
            "status": "error",
            "response": "测试图片仅支持 JPG / PNG / WEBP",
            "tokens_used": None,
            "duration_ms": 0,
        }
    if len(image_bytes) > MAX_TEST_IMAGE_BYTES:
        return {
            "status": "error",
            "response": "测试图片不能超过 10MB",
            "tokens_used": None,
            "duration_ms": 0,
        }
    return None


def list_presets(
    db: Session,
    provider_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[dict]:
    query = (
        db.query(AiPreset, AiProvider.name.label("provider_name"))
        .join(AiProvider, AiPreset.provider_id == AiProvider.id)
        .filter(AiPreset.deleted_at.is_(None))
    )
    if provider_id:
        query = query.filter(AiPreset.provider_id == provider_id)
    if search:
        like = f"%{search}%"
        query = query.filter(
            AiPreset.preset_name.ilike(like) | AiPreset.description.ilike(like)
        )
    rows = query.order_by(AiPreset.id.desc()).all()
    result = []
    for preset, provider_name in rows:
        d = preset.__dict__.copy()
        d["provider_name"] = provider_name
        result.append(d)
    return result


def get_preset(db: Session, preset_id: int) -> AiPreset:
    p = (
        db.query(AiPreset)
        .filter(AiPreset.id == preset_id, AiPreset.deleted_at.is_(None))
        .first()
    )
    if not p:
        raise ValueError("Preset 不存在")
    return p


def create_preset(db: Session, data: dict) -> AiPreset:
    exists = (
        db.query(AiPreset)
        .filter(
            AiPreset.preset_name == data["preset_name"],
            AiPreset.deleted_at.is_(None),
        )
        .first()
    )
    if exists:
        raise ValueError(f"Preset 名称 '{data['preset_name']}' 已存在")

    # 校验 provider 存在
    provider = get_provider(db, data["provider_id"])

    p = AiPreset(
        preset_name=data["preset_name"],
        provider_id=data["provider_id"],
        model=data.get("model") or "",
        system_prompt=data.get("system_prompt"),
        parameters=data.get("parameters"),
        description=data.get("description"),
        is_enabled=data.get("is_enabled", True),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    p.provider_name = provider.name
    return p


def update_preset(db: Session, preset_id: int, data: dict) -> AiPreset:
    p = get_preset(db, preset_id)
    if "preset_name" in data and data["preset_name"] != p.preset_name:
        exists = (
            db.query(AiPreset)
            .filter(
                AiPreset.preset_name == data["preset_name"],
                AiPreset.id != preset_id,
                AiPreset.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            raise ValueError(f"Preset 名称 '{data['preset_name']}' 已存在")
        p.preset_name = data["preset_name"]
    if "provider_id" in data:
        get_provider(db, data["provider_id"])
        p.provider_id = data["provider_id"]
    if "model" in data:
        p.model = data["model"] or ""
    if "system_prompt" in data:
        p.system_prompt = data["system_prompt"]
    if "parameters" in data:
        p.parameters = data["parameters"]
    if "description" in data:
        p.description = data["description"]
    if "is_enabled" in data:
        p.is_enabled = data["is_enabled"]
    db.commit()
    db.refresh(p)
    return p


def delete_preset(db: Session, preset_id: int) -> None:
    p = get_preset(db, preset_id)
    p.deleted_at = datetime.utcnow()
    db.commit()


def test_preset(db: Session, preset_id: int, test_message: str) -> dict:
    """Send a preset test through the same chat path used by business callers."""
    p = get_preset(db, preset_id)
    start = time.time()
    try:
        result = chat(
            db=db,
            preset_name=p.preset_name,
            messages=[{"role": "user", "content": test_message}],
            caller_module="ai_preset_test",
        )
    except Exception as exc:
        return _test_error_result(exc, start)

    return {
        "status": "ok",
        "response": result.get("content", ""),
        "tokens_used": result.get("tokens_used"),
        "duration_ms": result.get("duration_ms"),
    }


def test_preset_with_image(
    db: Session,
    preset_id: int,
    test_message: str,
    image_bytes: bytes,
    content_type: str,
    reference_image_bytes: bytes | None = None,
    reference_content_type: str | None = None,
) -> dict:
    """Send a preset test with one image using the same multimodal shape as expo."""
    invalid = _validate_test_image(image_bytes, content_type)
    if invalid:
        return invalid

    p = get_preset(db, preset_id)
    if p.preset_name in COMPOSITE_PRESET_NAMES:
        if not reference_image_bytes:
            return {
                "status": "error",
                "response": "expo_wig_composite 是换发合成预设，测试需要同时上传客户原图和假发参考图。",
                "tokens_used": None,
                "duration_ms": 0,
            }
        reference_type = reference_content_type or "application/octet-stream"
        invalid_reference = _validate_test_image(reference_image_bytes, reference_type)
        if invalid_reference:
            return invalid_reference

        start = time.time()
        try:
            result = edit_image(
                db=db,
                preset_name=p.preset_name,
                prompt=test_message,
                images=[
                    {
                        "filename": _image_filename("customer_image", content_type),
                        "content": image_bytes,
                        "content_type": content_type,
                    },
                    {
                        "filename": _image_filename("wig_reference", reference_type),
                        "content": reference_image_bytes,
                        "content_type": reference_type,
                    },
                ],
                caller_module="ai_preset_test",
            )
        except Exception as exc:
            return _test_error_result(exc, start)

        return {
            "status": "ok",
            "response": result.get("content", ""),
            "tokens_used": result.get("tokens_used"),
            "duration_ms": result.get("duration_ms"),
        }

    image_b64 = base64.b64encode(image_bytes).decode()
    start = time.time()
    try:
        result = chat(
            db=db,
            preset_name=p.preset_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": test_message},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{content_type};base64,{image_b64}"},
                        },
                    ],
                }
            ],
            caller_module="ai_preset_test",
        )
    except Exception as exc:
        return _test_error_result(exc, start)

    return {
        "status": "ok",
        "response": result.get("content", ""),
        "tokens_used": result.get("tokens_used"),
        "duration_ms": result.get("duration_ms"),
    }
