"""AI 调用 — chat (同步) / delegate (异步占位) / get_task_result"""

import json
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiCallLog
from app.ai.keyring import decrypt_key
from app.ai.http_client import build_chat_url, build_headers
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

        params = {"model": preset.model, "messages": full_messages, "stream": False}
        if preset.parameters:
            params.update(preset.parameters)

        req = urllib.request.Request(
            build_chat_url(provider.api_base),
            data=json.dumps(params).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=provider.timeout_sec) as resp:
            result = json.loads(resp.read().decode())

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = result.get("usage", {})
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
