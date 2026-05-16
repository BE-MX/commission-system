"""AI Preset CRUD + 单条测试"""

import json
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider
from app.ai.keyring import decrypt_key
from app.ai.http_client import build_chat_url, build_headers
from app.ai.provider_service import get_provider


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
    import urllib.request
    import urllib.error

    p = get_preset(db, preset_id)
    provider = get_provider(db, p.provider_id)

    if provider.provider_type == "accio_work":
        raise ValueError("ACCIO WORK 类型 Preset 不支持直接测试，请使用 delegate 接口")

    if not p.model:
        raise ValueError("Preset 未配置模型名称，请先编辑 Preset 填写正确的 model")

    start = time.time()
    api_key = decrypt_key(provider.api_key) if provider.api_key else None

    messages = []
    if p.system_prompt:
        messages.append({"role": "system", "content": p.system_prompt})
    messages.append({"role": "user", "content": test_message})

    headers = build_headers(provider, api_key)

    params = {"model": p.model, "messages": messages, "stream": False}
    if p.parameters:
        params.update(p.parameters)

    req = urllib.request.Request(
        build_chat_url(provider.api_base),
        data=json.dumps(params).encode(),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=provider.timeout_sec) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        resp_body = e.read().decode("utf-8", errors="replace")[:500]
        try:
            err_json = json.loads(resp_body)
            err_msg = err_json.get("error", {}).get("message", resp_body)
        except json.JSONDecodeError:
            err_msg = resp_body
        raise ValueError(f"HTTP {e.code} {e.reason}: {err_msg}")

    duration_ms = int((time.time() - start) * 1000)
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = result.get("usage", {})

    return {
        "status": "ok",
        "response": content,
        "tokens_used": usage.get("total_tokens"),
        "duration_ms": duration_ms,
    }
