"""AI Provider CRUD + 连通性测试"""

import json
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiProvider, AiPreset
from app.ai.keyring import encrypt_key, decrypt_key
from app.ai.http_client import build_chat_url, build_headers


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
        api_key=encrypt_key(data.get("api_key")),
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
        p.api_key = encrypt_key(data["api_key"])
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
        api_key = decrypt_key(p.api_key) if p.api_key else None
        if not api_key:
            return {
                "latency_ms": _elapsed(),
                "status": "error",
                "detail": "API Key 未配置，无法测试连通性",
            }

        headers = build_headers(p, api_key)

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
            "max_completion_tokens": 10,
        }
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            build_chat_url(p.api_base),
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
