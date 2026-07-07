"""AI image generation/editing calls for OpenAI-compatible providers."""

import json
import time
from typing import Optional, TypedDict

import httpx
from sqlalchemy.orm import Session

from app.ai.http_client import build_headers, build_image_url
from app.ai.keyring import decrypt_key
from app.ai.log_snapshot import serialize_response_snapshot
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider


class ImageInput(TypedDict):
    filename: str
    content: bytes
    content_type: str


IMAGE_PARAMETER_KEYS = {
    "background",
    "moderation",
    "n",
    "output_compression",
    "output_format",
    "partial_images",
    "quality",
    "response_format",
    "size",
    "stream",
    "user",
}
# 三格模板（expo tryon 16:9 三场景拼接）实测单图 184~200s，180 会掐死正常请求；
# 调此值需联动 expo/service.py 的 STALE_GENERATING_SECS（看门狗必须大于本超时）
MIN_IMAGE_EDIT_TIMEOUT_SEC = 300

def _get_enabled_direct_preset(db: Session, preset_name: str) -> tuple[AiPreset, object]:
    preset = (
        db.query(AiPreset)
        .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
        .first()
    )
    if not preset:
        raise ValueError(f"Preset '{preset_name}' 不存在")
    if not preset.is_enabled:
        raise ValueError(f"Preset '{preset_name}' 已被禁用")

    provider = get_provider(db, preset.provider_id)
    if provider.provider_type != "direct":
        raise ValueError(f"Preset '{preset_name}' 绑定的不是直连 Provider，不能调用图片编辑接口")
    if not provider.is_enabled:
        raise ValueError(f"Provider '{provider.name}' 当前不可用")
    if (getattr(provider, "api_type", "openai") or "openai") != "openai":
        raise ValueError("图片编辑测试只支持 OpenAI-compatible Provider")
    return preset, provider


def _image_prompt_snapshot(prompt: str, images: list[ImageInput]) -> str:
    return json.dumps(
        {
            "prompt": prompt,
            "image_count": len(images),
            "images": [
                {
                    "filename": image["filename"],
                    "content_type": image["content_type"],
                    "size": len(image["content"]),
                }
                for image in images
            ],
        },
        ensure_ascii=False,
    )


def _image_params(preset: AiPreset, prompt: str, size: Optional[str] = None) -> dict:
    params = {
        "model": preset.model,
        "prompt": prompt,
    }
    for key, value in (preset.parameters or {}).items():
        if key in IMAGE_PARAMETER_KEYS:
            params[key] = value
    if size:  # 请求级尺寸覆盖 preset 配置（如 expo 竖版/横版按场景切换）
        params["size"] = size
    return params


def _extract_image_content(result: dict) -> str:
    data = result.get("data")
    if isinstance(data, list) and data:
        first = data[0] or {}
        if first.get("b64_json"):
            return f"data:image/png;base64,{first['b64_json']}"
        if first.get("url"):
            return first["url"]
    if result.get("b64_json"):
        return f"data:image/png;base64,{result['b64_json']}"
    if result.get("url"):
        return result["url"]
    return ""


def _extract_usage(result: dict) -> dict:
    usage = result.get("usage") or {}
    if not usage and isinstance(result.get("data"), list) and result["data"]:
        usage = result["data"][0].get("usage") or {}
    return {
        "prompt_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
        "completion_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _effective_timeout_sec(provider) -> int:
    return max(provider.timeout_sec or 0, MIN_IMAGE_EDIT_TIMEOUT_SEC)


def edit_image(
    db: Session,
    preset_name: str,
    prompt: str,
    images: list[ImageInput],
    caller_module: str,
    caller_user_id: Optional[int] = None,
    size: Optional[str] = None,
) -> dict:
    """Call an OpenAI-compatible image edit endpoint and return an image URL/data URL."""
    preset, provider = _get_enabled_direct_preset(db, preset_name)
    if not images:
        raise ValueError("图片编辑至少需要 1 张输入图片")

    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=_image_prompt_snapshot(prompt, images),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    start = time.time()
    try:
        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        headers.pop("Content-Type", None)

        files = [
            (
                "image",
                (image["filename"], image["content"], image["content_type"]),
            )
            for image in images
        ]
        url = build_image_url(provider.api_base, "edits")

        timeout_sec = _effective_timeout_sec(provider)
        with httpx.Client(timeout=timeout_sec) as client:
            try:
                response = client.post(
                    url,
                    headers=headers,
                    data=_image_params(preset, prompt, size),
                    files=files,
                )
            except httpx.ReadTimeout as exc:
                raise TimeoutError(
                    f"图片生成超时：上游 {timeout_sec} 秒内未返回。"
                    "这通常是生图模型排队或代理池响应慢，请稍后重试或提高 Provider 超时时间。"
                ) from exc
            response.raise_for_status()
            result = response.json()

        content = _extract_image_content(result)
        if not content:
            raise ValueError("图片接口响应中未找到 url 或 b64_json")

        usage = _extract_usage(result)
        duration_ms = int((time.time() - start) * 1000)
        log.status = "success"
        log.tokens_prompt = usage.get("prompt_tokens")
        log.tokens_completion = usage.get("completion_tokens")
        log.tokens_used = usage.get("total_tokens")
        log.duration_ms = duration_ms
        log.response_snapshot = serialize_response_snapshot(result)
        db.commit()

        return {
            "content": content,
            "tokens_used": usage.get("total_tokens"),
            "duration_ms": duration_ms,
            "log_id": log.id,
        }
    except Exception as exc:
        db.rollback()
        try:
            log.status = "error"
            log.error_code = "unknown_error"
            log.error_message = str(exc)[:500]
            log.duration_ms = int((time.time() - start) * 1000)
            db.commit()
        except Exception:
            db.rollback()
        raise
