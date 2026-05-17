"""方舟洞见 — Router 权限依赖与视图模型 helper

集中 router 的:
- 权限检查 (_is_super_admin / _has_perm / _has_any_perm)
- FastAPI Depends 工厂 (_require_insight_view / _internal / _admin)
- 导入 API key 校验 (_verify_import_api_key)
- 字段序列化 (_serialize_source — 信源 dict view-model)

router 的 endpoint 通过 `from app.insight.dependencies import ...` 引用,
保持 _xxx 前缀(模块内部约定 — 非公开 API)。
"""

import logging
import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.auth.dependencies import get_current_user

logger = logging.getLogger("insight")


def _is_super_admin(user: dict) -> bool:
    return "super_admin" in (user.get("roles") or [])


def _has_perm(user: dict, code: str) -> bool:
    if _is_super_admin(user):
        return True
    return code in (user.get("permissions") or [])


def _has_any_perm(user: dict, codes: list[str]) -> bool:
    if _is_super_admin(user):
        return True
    perms = set(user.get("permissions") or [])
    return any(c in perms for c in codes)


def _require_insight_view(user: dict = Depends(get_current_user)):
    """统一基础查看权限:任意 insight:* 都可读普通报告。"""
    if not _has_any_perm(user, ["insight:read", "insight:write", "insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight 任一权限")
    return user


def _require_insight_internal(user: dict = Depends(get_current_user)):
    """内部经营报告查看:internal_read 或 admin。"""
    if not _has_any_perm(user, ["insight:internal_read", "insight:admin"]):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:internal_read")
    return user


def _require_insight_admin(user: dict = Depends(get_current_user)):
    if not _has_perm(user, "insight:admin"):
        raise HTTPException(status_code=403, detail="权限不足:需要 insight:admin")
    return user


def _verify_import_api_key(authorization: Optional[str] = Header(None)):
    """ACCIO WORK 等外部系统使用 Bearer API Key 认证。"""
    expected = os.environ.get("INSIGHT_IMPORT_API_KEY", "").strip()
    if not expected:
        # 未配置时拒绝所有外部导入,防误用
        raise HTTPException(status_code=503, detail="导入接口未启用(INSIGHT_IMPORT_API_KEY 未配置)")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="API Key 无效")
    return True


def _serialize_source(s):
    return {
        "id": s.id,
        "name": s.name,
        "source_type": s.source_type,
        "url": s.url,
        "keywords": s.keywords,
        "exclude_keywords": s.exclude_keywords,
        "css_selector": s.css_selector,
        "request_headers": s.request_headers,
        "proxy_url": s.proxy_url,
        "fetch_interval_hours": s.fetch_interval_hours,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "last_error": s.last_error,
        "consecutive_failures": s.consecutive_failures,
        "is_active": bool(s.is_active),
        "pipeline": s.pipeline,
        "sort_order": s.sort_order,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
