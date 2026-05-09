"""AI 接入模块 — 业务逻辑层"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiProvider, AiPreset, AiCallLog


# ── 辅助函数 ───────────────────────────────────────────

def _ok(data, message: str = "ok"):
    return {"code": 200, "message": message, "data": data}


def _build_chat_url(api_base: str) -> str:
    """根据 api_base 构造完整的 chat/completions URL。
    如果 api_base 已包含版本号（/v1 /v2 等）或 /api 路径，直接拼接；
    否则自动补全 /v1（主流平台默认）。
    """
    base = api_base.rstrip("/")
    if any(base.endswith(v) for v in ("/v1", "/v2", "/v3", "/v4", "/api")):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _build_headers(provider: AiProvider, api_key: str | None) -> dict:
    """构造请求头。支持通过 extra_headers 自定义认证方式（如 api-key）。
    extra_headers 中填 {\"api-key\": \"\"} 表示使用 api_key 字段的值作为 api-key。
    """
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LeShine-Ark-AI/1.0",
    }
    extra = provider.extra_headers or {}
    for k, v in extra.items():
        if v == "" and k.lower() == "api-key" and api_key:
            headers[k] = api_key
        else:
            headers[k] = v

    has_auth = any(k.lower() in ("authorization", "api-key") for k in headers)
    if api_key and not has_auth:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


# ── Provider ──────────────────────────────────────────

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
        api_key=_encrypt_key(data.get("api_key")),
        extra_headers=data.get("extra_headers"),
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
        p.api_key = _encrypt_key(data["api_key"])
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
    p.deleted_at = datetime.utcnow()
    db.commit()


def test_provider(db: Session, provider_id: int) -> dict:
    """连通性测试。direct 模式发送最小 chat 请求；accio_work 发送握手。"""
    import time
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
                timeout=p.timeout_sec,
                headers={"User-Agent": "LeShine-Ark-AI/1.0"},
            )
            with urllib.request.urlopen(req) as resp:
                status = resp.status
            return {
                "latency_ms": _elapsed(),
                "status": "ok",
                "detail": f"ACCIO SSE 端点可达，HTTP {status}",
            }

        # ── 直连模式 ──────────────────────────────────────
        api_key = _decrypt_key(p.api_key) if p.api_key else None
        if not api_key:
            return {
                "latency_ms": _elapsed(),
                "status": "error",
                "detail": "API Key 未配置，无法测试连通性",
            }

        headers = _build_headers(p, api_key)

        # 使用 Provider 下第一个 Preset 的 model
        first_preset = (
            db.query(AiPreset)
            .filter(AiPreset.provider_id == p.id, AiPreset.deleted_at.is_(None))
            .first()
        )
        if not first_preset or not first_preset.model:
            return {
                "latency_ms": _elapsed(),
                "status": "error",
                "detail": "此 Provider 下没有配置模型名的 Preset，请先创建一个 Preset 并填写正确的模型名称（如 mimo-v2.5-pro）",
            }
        model = first_preset.model

        body = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 10,
            "max_completion_tokens": 10,
            "temperature": 0.7,
            "top_p": 0.95,
            "stream": False,
        }
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            _build_chat_url(p.api_base),
            data=payload,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=p.timeout_sec) as resp:
            result = json.loads(resp.read().decode())

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "latency_ms": _elapsed(),
            "status": "ok",
            "detail": f"Model responded with {len(content)} chars",
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


# ── Preset ────────────────────────────────────────────

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
    """用指定预设发送测试消息。"""
    import time

    p = get_preset(db, preset_id)
    provider = get_provider(db, p.provider_id)

    if provider.provider_type == "accio_work":
        raise ValueError("ACCIO WORK 类型 Preset 不支持直接测试，请使用 delegate 接口")

    start = time.time()
    api_key = _decrypt_key(provider.api_key) if provider.api_key else None

    messages = []
    if p.system_prompt:
        messages.append({"role": "system", "content": p.system_prompt})
    messages.append({"role": "user", "content": test_message})

    headers = _build_headers(provider, api_key)

    params = {"model": p.model, "messages": messages, "stream": False}
    if p.parameters:
        params.update(p.parameters)

    import urllib.request
    req = urllib.request.Request(
        _build_chat_url(provider.api_base),
        data=json.dumps(params).encode(),
        headers=headers,
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=provider.timeout_sec) as resp:
        result = json.loads(resp.read().decode())

    duration_ms = int((time.time() - start) * 1000)
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = result.get("usage", {})

    return {
        "status": "ok",
        "response": content,
        "tokens_used": usage.get("total_tokens"),
        "duration_ms": duration_ms,
    }


# ── Call Log ──────────────────────────────────────────

def list_logs(
    db: Session,
    caller_module: Optional[str] = None,
    preset_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    query = db.query(AiCallLog)
    if caller_module:
        query = query.filter(AiCallLog.caller_module == caller_module)
    if preset_id:
        query = query.filter(AiCallLog.preset_id == preset_id)
    if status:
        query = query.filter(AiCallLog.status == status)
    if date_from:
        query = query.filter(AiCallLog.created_at >= date_from)
    if date_to:
        query = query.filter(AiCallLog.created_at <= date_to)

    total = query.count()
    items = (
        query.order_by(AiCallLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    summary = {
        "tokens_total": (
            db.query(AiCallLog)
            .filter(AiCallLog.tokens_used.isnot(None))
            .with_entities(AiCallLog.tokens_used)
            .all()
        ),
        "success_count": db.query(AiCallLog).filter(AiCallLog.status == "success").count(),
        "error_count": db.query(AiCallLog).filter(AiCallLog.status == "error").count(),
        "timeout_count": db.query(AiCallLog).filter(AiCallLog.status == "timeout").count(),
    }
    tokens_total = sum(x[0] for x in summary["tokens_total"] if x[0] is not None)
    avg_q = (
        db.query(AiCallLog)
        .filter(AiCallLog.duration_ms.isnot(None))
        .with_entities(AiCallLog.duration_ms)
        .all()
    )
    avg_duration = (
        round(sum(x[0] for x in avg_q) / len(avg_q)) if avg_q else 0
    )

    return {
        "total": total,
        "summary": {
            "tokens_total": tokens_total,
            "success_count": summary["success_count"],
            "error_count": summary["error_count"],
            "timeout_count": summary["timeout_count"],
            "avg_duration_ms": avg_duration,
        },
        "items": items,
    }


def get_log(db: Session, log_id: int) -> AiCallLog:
    log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
    if not log:
        raise ValueError("日志不存在")
    return log


# ── Invoke (chat / delegate) ──────────────────────────

def chat(db: Session, preset_name: str, messages: list, caller_module: str, caller_user_id: Optional[int] = None) -> dict:
    """同步调用直连大模型。"""
    import time
    import urllib.request

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

    # 写入 pending 日志
    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=json.dumps(full_messages, ensure_ascii=False),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    start = time.time()
    try:
        api_key = _decrypt_key(provider.api_key) if provider.api_key else None
        headers = _build_headers(provider, api_key)

        params = {"model": preset.model, "messages": full_messages, "stream": False}
        if preset.parameters:
            params.update(preset.parameters)

        req = urllib.request.Request(
            _build_chat_url(provider.api_base),
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
    import time

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
    # 这里先写入 pending 状态，由外部轮询 get_task_result 获取结果
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


# ── 加密 / 解密（占位实现）─────────────────────────────

_ARK_AI_ENCRYPTION_KEY: Optional[str] = None


def _get_key() -> str:
    """获取加密密钥（环境变量 ARK_AI_ENCRYPTION_KEY）。"""
    global _ARK_AI_ENCRYPTION_KEY
    if _ARK_AI_ENCRYPTION_KEY is None:
        import os
        key = os.environ.get("ARK_AI_ENCRYPTION_KEY", "")
        if not key:
            # 开发环境使用默认密钥
            import base64
            _ARK_AI_ENCRYPTION_KEY = base64.b64encode(b"ark_ai_default_key_32_bytes_").decode()
        else:
            _ARK_AI_ENCRYPTION_KEY = key
    return _ARK_AI_ENCRYPTION_KEY


def _encrypt_key(plaintext: Optional[str]) -> Optional[str]:
    """加密 api_key。实际使用 AES-256-GCM，这里先做 base64 占位。"""
    if not plaintext:
        return None
    try:
        import os
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key_b64 = _get_key()
        key = base64.b64decode(key_b64)
        iv = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
        raw = iv + ciphertext
        return base64.b64encode(raw).decode("ascii")
    except ImportError:
        # cryptography 未安装时使用简单 base64 占位
        import base64
        return base64.b64encode(plaintext.encode()).decode()
    except Exception:
        return base64.b64encode(plaintext.encode()).decode()


def _decrypt_key(encrypted: Optional[str]) -> Optional[str]:
    """解密 api_key。"""
    if not encrypted:
        return None
    try:
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key_b64 = _get_key()
        key = base64.b64decode(key_b64)
        raw = base64.b64decode(encrypted)
        iv = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return plaintext.decode("utf-8")
    except ImportError:
        import base64
        return base64.b64decode(encrypted).decode()
    except Exception:
        # 解密失败可能是 base64 占位格式
        try:
            import base64
            return base64.b64decode(encrypted).decode()
        except Exception:
            return encrypted
