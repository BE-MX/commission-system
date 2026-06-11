"""AI 调用 — chat (同步) / delegate (异步占位) / get_task_result"""

import json
import logging
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("commission.ai")

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiCallLog
from app.ai.keyring import decrypt_key
from app.ai.http_client import (
    build_chat_url, build_headers,
    build_anthropic_body, extract_anthropic_content, extract_anthropic_usage,
)
from app.ai.provider_service import get_provider


def chat(
    db: Session,
    preset_name: str,
    messages: list,
    caller_module: str,
    caller_user_id: Optional[int] = None,
) -> dict:
    """同步调用直连大模型。"""
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
        raise ValueError(
            f"Preset '{preset_name}' 绑定的是 accio_work 类型 Provider，请使用 delegate 接口"
        )
    if not provider.is_enabled:
        raise ValueError(f"Provider '{provider.name}' 当前不可用")

    # 构造 messages
    full_messages = []
    if preset.system_prompt:
        full_messages.append({"role": "system", "content": preset.system_prompt})
    full_messages.extend(messages)

    # 写入 pending 日志(截断过长的 prompt_snapshot,避免超出 TEXT 列限制)
    snapshot_str = json.dumps(full_messages, ensure_ascii=False)
    if len(snapshot_str) > 60000:
        # 多模态请求含 base64 图片会很大,只记录前后部分
        snapshot_str = (
            snapshot_str[:2000]
            + f"\n... [truncated {len(snapshot_str)} chars, likely contains base64 image] ...\n"
            + snapshot_str[-500:]
        )
    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=snapshot_str,
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    start = time.time()
    try:
        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        api_type = getattr(provider, "api_type", "openai") or "openai"

        # 按协议类型构造请求体
        if api_type == "anthropic":
            params = build_anthropic_body(
                model=preset.model,
                messages=full_messages,
                system_prompt=preset.system_prompt,
                parameters=preset.parameters,
            )
        else:
            params = {"model": preset.model, "messages": full_messages, "stream": False}
            if preset.parameters:
                params.update(preset.parameters)

        url = build_chat_url(provider.api_base, api_type)
        has_image = any(
            isinstance(m.get("content"), list)
            and any(c.get("type") == "image_url" for c in m["content"])
            for m in full_messages
        )
        logger.info(
            "AI request: provider=%s model=%s api_type=%s url=%s msg_count=%d has_image=%s",
            provider.name, preset.model, api_type, url, len(full_messages), has_image,
        )
        if has_image:
            print(f"[AI-DIAG] request with image | provider={provider.name} model={preset.model} "
                  f"api_type={api_type} url={url} msg_count={len(full_messages)}", flush=True)

        req = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=provider.timeout_sec) as resp:
            raw_bytes = resp.read()
            result = json.loads(raw_bytes.decode())

        # 按协议类型解析响应
        if api_type == "anthropic":
            content = extract_anthropic_content(result)
            usage = extract_anthropic_usage(result)
        else:
            # OpenAI 标准格式: choices[0].message.content
            message = result.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "")
            # 某些 API (如 StepFun) 可能返回 list/dict 类型的 content,统一转 str
            if content is not None and not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)

            # 推理模型兼容 (Step-3.7-flash / DeepSeek-R1 等):
            # content 为空但 reasoning/reasoning_content 有内容时,从中提取答案
            if not content:
                reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
                if reasoning and isinstance(reasoning, str) and reasoning.strip():
                    logger.info(
                        "AI content empty, falling back to reasoning. provider=%s model=%s reasoning_len=%d",
                        provider.name, preset.model, len(reasoning),
                    )
                    print(f"[AI-DIAG] content empty, using reasoning ({len(reasoning)} chars) | "
                          f"provider={provider.name} model={preset.model}", flush=True)
                    content = reasoning

            usage = result.get("usage", {})

        # 诊断: content 为空时记录完整响应结构
        if not content and result:
            diag = json.dumps(result, ensure_ascii=False)[:2000]
            logger.warning(
                "AI response has empty content. provider=%s model=%s result_keys=%s full_result=%s",
                provider.name, preset.model, list(result.keys()), diag,
            )
            print(f"[AI-DIAG] empty content | provider={provider.name} model={preset.model} "
                  f"result_keys={list(result.keys())} full_result={diag}", flush=True)
        duration_ms = int((time.time() - start) * 1000)

        log.status = "success"
        log.tokens_prompt = usage.get("prompt_tokens")
        log.tokens_completion = usage.get("completion_tokens")
        log.tokens_used = usage.get("total_tokens")
        log.duration_ms = duration_ms
        log.response_snapshot = json.dumps(result, ensure_ascii=False)
        db.commit()

        return {
            "content": content,
            "tokens_used": usage.get("total_tokens"),
            "duration_ms": duration_ms,
            "log_id": log.id,
        }
    except Exception as e:
        log.status = "error"
        log.error_code = "unknown_error"
        log.error_message = str(e)[:500]
        log.duration_ms = int((time.time() - start) * 1000)
        db.commit()
        raise


def delegate(
    db: Session,
    preset_name: str,
    task: dict,
    caller_module: str,
    caller_user_id: Optional[int] = None,
    callback_url: Optional[str] = None,
) -> dict:
    """异步委托 ACCIO WORK Agent。返回 task_id。"""
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
    if provider.provider_type != "accio_work":
        raise ValueError(
            f"Preset '{preset_name}' 绑定的是 direct 类型 Provider，请使用 chat 接口"
        )
    if not provider.is_enabled:
        raise ValueError(f"Provider '{provider.name}' 当前不可用")

    task_id = f"aw_task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:12]}"

    log = AiCallLog(
        task_id=task_id,
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        prompt_snapshot=json.dumps(task, ensure_ascii=False),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # TODO: 实际应派发到 Celery Worker 异步处理
    # 这里先写入 pending 状态,由外部轮询 get_task_result 获取结果
    return {
        "task_id": task_id,
        "status": "pending",
        "log_id": log.id,
    }


def get_task_result(db: Session, task_id: str) -> dict:
    """查询异步任务结果。"""
    log = (
        db.query(AiCallLog)
        .filter(AiCallLog.task_id == task_id)
        .first()
    )
    if not log:
        raise ValueError(f"Task '{task_id}' 不存在")

    result = None
    if log.response_snapshot:
        try:
            result = json.loads(log.response_snapshot)
        except json.JSONDecodeError:
            result = {"raw": log.response_snapshot}

    return {
        "task_id": task_id,
        "status": log.status,
        "result": result,
        "duration_ms": log.duration_ms,
        "created_at": log.created_at,
        "completed_at": log.updated_at if log.status in ("success", "error", "timeout") else None,
        "error_message": log.error_message,
    }
