"""AI Provider CRUD + 连通性测试"""

import json
import time
from datetime import datetime
from app.core.time import beijing_now
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.ai.models import AiProvider, AiPreset
from app.ai.provider_config import validate_provider_options, validate_extra_headers, provider_options, MASKED_HEADER_VALUE, request_timeout
from app.ai.keyring import encrypt_key, decrypt_key
from app.ai.http_client import (
    build_chat_url, build_headers, post_json,
    build_anthropic_body, extract_anthropic_content,
)


def list_providers(
    db: Session,
    provider_type: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    search: Optional[str] = None,
) -> list[AiProvider]:
    query = db.query(AiProvider).filter(AiProvider.deleted_at.is_(None))
    if provider_type:
        query = query.filter(AiProvider.provider_type == provider_type)
    if is_enabled is not None:
        query = query.filter(AiProvider.is_enabled.is_(is_enabled))
    if search:
        like = f"%{search}%"
        query = query.filter(
            AiProvider.name.ilike(like) | AiProvider.api_base.ilike(like)
        )
    return query.order_by(AiProvider.id.desc()).all()


def get_provider(db: Session, provider_id: int) -> AiProvider:
    p = (
        db.query(AiProvider)
        .filter(AiProvider.id == provider_id, AiProvider.deleted_at.is_(None))
        .first()
    )
    if not p:
        raise ValueError("Provider 不存在")
    return p


def create_provider(db: Session, data: dict) -> AiProvider:
    validate_provider_options(data.get("runtime_config"))
    validate_extra_headers(data.get("extra_headers"), (data.get("runtime_config") or {}).get("auth_header"))
    if MASKED_HEADER_VALUE in (data.get("extra_headers") or {}).values():
        raise ValueError("新提供商不能使用保留旧密钥标记")
    exists = (
        db.query(AiProvider)
        .filter(AiProvider.name == data["name"], AiProvider.deleted_at.is_(None))
        .first()
    )
    if exists:
        raise ValueError(f"Provider 名称 '{data['name']}' 已存在")

    p = AiProvider(
        name=data["name"],
        provider_type=data.get("provider_type", "direct"),
        api_base=data["api_base"],
        api_key=encrypt_key(data.get("api_key")),
        api_type=data.get("api_type", "openai"),
        extra_headers=data.get("extra_headers"),
        runtime_config=validate_provider_options(data.get("runtime_config")),
        is_enabled=data.get("is_enabled", True),
        timeout_sec=data.get("timeout_sec", 60),
        remark=data.get("remark"),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_provider(db: Session, provider_id: int, data: dict) -> AiProvider:
    p = get_provider(db, provider_id)
    if "runtime_config" in data:
        data["runtime_config"] = validate_provider_options(data["runtime_config"])
    auth_header = (data.get("runtime_config", p.runtime_config) or {}).get("auth_header")
    if "extra_headers" in data:
        validate_extra_headers(data["extra_headers"], auth_header)
        merged = dict(data["extra_headers"] or {})
        for key, value in merged.items():
            if value == MASKED_HEADER_VALUE:
                if key not in (p.extra_headers or {}):
                    raise ValueError("该请求头没有可保留的旧值")
                merged[key] = p.extra_headers[key]
        data["extra_headers"] = merged
    if "runtime_config" in data:
        old_auth_header = (p.runtime_config or {}).get("auth_header")
        candidate_headers = data.get("extra_headers", p.extra_headers) or {}
        for key in {auth_header, old_auth_header} - {None, ""}:
            matching = {name: value for name, value in candidate_headers.items() if name.lower() == key.lower()}
            # Custom credential slots always use the encrypted API Key, never literal JSON values.
            validate_extra_headers(matching, key)
    if "name" in data and data["name"] != p.name:
        exists = (
            db.query(AiProvider)
            .filter(
                AiProvider.name == data["name"],
                AiProvider.id != provider_id,
                AiProvider.deleted_at.is_(None),
            )
            .first()
        )
        if exists:
            raise ValueError(f"Provider 名称 '{data['name']}' 已存在")
        p.name = data["name"]
    if "provider_type" in data:
        p.provider_type = data["provider_type"]
    if "api_base" in data:
        p.api_base = data["api_base"]
    if "api_key" in data and data["api_key"]:
        p.api_key = encrypt_key(data["api_key"])
    if "api_type" in data:
        p.api_type = data["api_type"]
    if "runtime_config" in data:
        p.runtime_config = data["runtime_config"]
    if "extra_headers" in data:
        p.extra_headers = data["extra_headers"]
    if "is_enabled" in data:
        p.is_enabled = data["is_enabled"]
    if "timeout_sec" in data:
        p.timeout_sec = data["timeout_sec"]
    if "remark" in data:
        p.remark = data["remark"]
    db.commit()
    db.refresh(p)
    return p


def delete_provider(db: Session, provider_id: int) -> None:
    p = get_provider(db, provider_id)
    active_presets = (
        db.query(AiPreset)
        .filter(
            AiPreset.provider_id == provider_id,
            AiPreset.deleted_at.is_(None),
        )
        .count()
    )
    if active_presets > 0:
        preset_names = (
            db.query(AiPreset.preset_name)
            .filter(
                AiPreset.provider_id == provider_id,
                AiPreset.deleted_at.is_(None),
            )
            .all()
        )
        names = [x[0] for x in preset_names]
        raise ValueError(
            f"Provider 下存在 {active_presets} 个活跃 Preset，无法删除。"
            f"请先删除或迁移 Preset：{names}"
        )
    p.deleted_at = beijing_now()
    db.commit()


def test_provider(db: Session, provider_id: int) -> dict:
    """连通性测试。direct 模式发送最小 chat 请求；accio_work 发送握手。"""
    import urllib.request
    import urllib.error

    p = get_provider(db, provider_id)
    start = time.time()

    def _elapsed():
        return int((time.time() - start) * 1000)

    try:
        if p.provider_type == "accio_work":
            # 简化为 HTTP 可达性检查
            req = urllib.request.Request(
                p.api_base,
                method="GET",
                headers={"User-Agent": "LeShine-Ark-AI/1.0"},
            )
            with urllib.request.urlopen(req, timeout=p.timeout_sec) as resp:
                status = resp.status
            return {
                "latency_ms": _elapsed(),
                "status": "ok",
                "detail": f"ACCIO SSE 端点可达，HTTP {status}",
            }

        # ── 直连模式 ──────────────────────────────────────
        api_key = decrypt_key(p.api_key) if p.api_key else None
        if not api_key:
            return {
                "latency_ms": _elapsed(),
                "status": "error",
                "detail": "API Key 未配置，无法测试连通性",
            }

        headers = build_headers(p, api_key)

        options = provider_options(p)
        # A connectivity probe uses an explicitly selected model or an enabled text preset.
        first_preset = (
            db.query(AiPreset)
            .filter(AiPreset.provider_id == p.id, AiPreset.deleted_at.is_(None), AiPreset.is_enabled.is_(True))
            .order_by(AiPreset.id)
            .all()
        )
        from app.ai.preset_config import is_image_preset
        first_preset = next((item for item in first_preset if not is_image_preset(item)), None)
        model = options.get("test_model") or (first_preset.model if first_preset else None)
        if not model:
            return {
                "latency_ms": _elapsed(),
                "status": "error",
                "detail": "请配置连通性测试模型，或绑定并启用文本预设；图片模型请使用预设测试上传图片/输入提示词",
            }
        message = options.get("test_message", "hi")
        token_limit = options.get("test_max_tokens", 10)
        api_type = getattr(p, "api_type", "openai") or "openai"

        if api_type == "anthropic":
            body = build_anthropic_body(model, [{"role": "user", "content": message}], parameters={"max_tokens": token_limit})
        else:
            body = {
                "model": model,
                "messages": [{"role": "user", "content": message}],
                options.get("token_parameter", "max_tokens"): token_limit,
            }
        url = build_chat_url(p.api_base, api_type, provider=p)
        result = post_json(
            url,
            headers=headers,
            body=body,
            timeout_sec=request_timeout(p),
            **({"transport": options} if options else {}),
        )

        if api_type == "anthropic":
            content = extract_anthropic_content(result)
        else:
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "latency_ms": _elapsed(),
            "status": "ok",
            "detail": f"Model responded with {len(content)} chars",
        }

    except httpx.HTTPStatusError as e:
        resp_body = e.response.text[:500]
        try:
            err_json = json.loads(resp_body)
            error_value = err_json.get("error") if isinstance(err_json, dict) else None
            if isinstance(error_value, dict):
                err_msg = error_value.get("message", resp_body)
            elif error_value is not None:
                err_msg = str(error_value)
            else:
                err_msg = resp_body
        except json.JSONDecodeError:
            err_msg = resp_body
        return {
            "latency_ms": _elapsed(),
            "status": "error",
            "detail": f"HTTP {e.response.status_code} {e.response.reason_phrase}: {err_msg}",
            "request_body": body,
        }
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")[:500]
        try:
            err_json = json.loads(resp_body)
            err_msg = err_json.get("error", {}).get("message", resp_body)
        except json.JSONDecodeError:
            err_msg = resp_body
        return {
            "latency_ms": _elapsed(),
            "status": "error",
            "detail": f"HTTP {e.code} {e.reason}: {err_msg}",
            "request_body": body,
        }
    except Exception as e:
        return {
            "latency_ms": _elapsed(),
            "status": "error",
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }
