"""AI image generation/editing calls for OpenAI-compatible providers."""

import json
import logging
import time
from typing import Optional, TypedDict

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger("commission.ai.image")

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
    "input_fidelity",  # gpt-image edits：high 强力保留输入图脸部/细节（治合成脸变形，2026-07-16）
                       # 2026-07-20 起 wlai 中转站不再认 gpt-image-2+此参数（400），靠摘参重试兜底
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

# 只重试**快速失败**的 502/503（网关立即拒绝，2026-07-16 生产实证 ~13% 失败多为 502，重试能救回）。
# **504 不重试**：它是「网关等上游超时」本质就慢，重试会叠加拖长；连同不重试的 ReadTimeout，都是
# 为了守住 expo 看门狗预算——单次超时 300s、看门狗 STALE_GENERATING_SECS(420s)，2 次慢速请求即越界，
# 迟到成功会被看门狗判死后覆写、但前端已 stopPolling 离场，造成 DB 有成品/前端已报错的错位。
_IMAGE_RETRY_STATUS = {502, 503}
_IMAGE_MAX_ATTEMPTS = 3          # 首次 + 2 次重试
_IMAGE_RETRY_BACKOFF_SEC = 1.5   # 线性退避 1.5s / 3s
# 连接/写入超时收紧到 15s（快速失败），只放长 read 给生图本身——否则 ConnectTimeout 也吃满 300s
_IMAGE_CONNECT_TIMEOUT_SEC = 15.0


def _enrich_status_error(exc: httpx.HTTPStatusError) -> httpx.HTTPStatusError:
    """httpx 的 raise_for_status 消息不含响应体，而中转站的真实失败原因全在体内
    error.message（2026-07-20 排障实证：光看 '400 Bad Request' 无从下手）——追加截断片段。"""
    try:
        body = (exc.response.text or "").strip()
    except Exception:
        body = ""
    if not body:
        return exc
    return httpx.HTTPStatusError(
        f"{exc.args[0] if exc.args else exc} | 响应体: {body[:300]}",
        request=exc.request, response=exc.response,
    )


def _unsupported_param(exc: httpx.HTTPStatusError, data: dict) -> Optional[str]:
    """400 响应显式指认某参数不支持（error.param）且该参数确在本次请求里才返回参数名。
    model/prompt 是请求本体不算：摘了它们等于换了个请求。"""
    if exc.response.status_code != 400:
        return None
    try:
        err = (exc.response.json() or {}).get("error") or {}
    except Exception:
        return None
    param = err.get("param")
    if param and param in data and param not in ("model", "prompt"):
        return param
    return None


def _post_image_edits(url, headers, data, files, timeout_sec: int, caller_module: str) -> dict:
    """带摘参兜底的 edits 调用：上游 400 明确指认某可选参数不支持时（2026-07-20 中转站
    突然不认 gpt-image-2 + input_fidelity，preset 配置没变、上游能力漂移），摘掉该参数
    重发而不是硬失败——展位 kiosk 的可用性优先于单个参数带来的增强效果，摘参会大声记日志。
    每个参数只摘一次，防上游反复指认同一参数造成死循环。"""
    data = dict(data)  # 本地副本：摘参不改坏调用方字典
    stripped: set[str] = set()
    while True:
        try:
            return _post_image_edits_once(url, headers, data, files, timeout_sec, caller_module)
        except httpx.HTTPStatusError as exc:
            bad = _unsupported_param(exc, data)
            if not bad or bad in stripped:
                raise
            stripped.add(bad)
            data.pop(bad, None)
            msg = (f"[{caller_module}] 上游拒收参数 {bad}（HTTP 400），已摘除重发。"
                   f"若长期如此请在 AI 后台把该参数从 preset 移除。响应体: "
                   f"{(exc.response.text or '')[:200]}")
            logger.warning(msg)
            print(msg, flush=True)


def _post_image_edits_once(url, headers, data, files, timeout_sec: int, caller_module: str) -> dict:
    """POST 到 /images/edits，对 502/503 与连接瞬断自动重试；504/ReadTimeout 不重试直接抛。"""
    timeout = httpx.Timeout(timeout_sec, connect=_IMAGE_CONNECT_TIMEOUT_SEC, write=30.0)
    last_exc: Exception | None = None
    for attempt in range(1, _IMAGE_MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            return response.json()
        except httpx.ReadTimeout as exc:
            raise TimeoutError(
                f"图片生成超时：上游 {timeout_sec} 秒内未返回。"
                "这通常是生图模型排队或代理池响应慢，请稍后重试或提高 Provider 超时时间。"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _IMAGE_RETRY_STATUS:
                raise _enrich_status_error(exc) from exc
            last_exc = exc
        except httpx.TransportError as exc:  # 连接/网络瞬断（ReadTimeout 已在上面拦掉）
            last_exc = exc
        if attempt < _IMAGE_MAX_ATTEMPTS:
            msg = (f"[{caller_module}] image edit transient error, retry {attempt}/"
                   f"{_IMAGE_MAX_ATTEMPTS - 1}: {type(last_exc).__name__}: {last_exc}")
            logger.warning(msg)
            print(msg, flush=True)
            time.sleep(_IMAGE_RETRY_BACKOFF_SEC * attempt)
    if isinstance(last_exc, httpx.HTTPStatusError):
        raise _enrich_status_error(last_exc) from last_exc
    raise last_exc


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
        result = _post_image_edits(
            url, headers, _image_params(preset, prompt, size), files, timeout_sec, caller_module,
        )

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
