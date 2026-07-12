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
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.auth.dependencies import get_current_user, require_any_permission, require_permission
from app.core.config import get_settings

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


# ── 权限依赖：统一委托 auth.dependencies 工厂（治理 B-6：OR 语义 + super_admin 绕过）──
# 2026-07-12 起 insight:write 下架（职责拆入 insight_case:write / insight_minutes:write），
# view 组不再包含它；061 迁移已给旧码持有者补授新码。
# 同日 063 逐页拆分：采集库/日报/AI 工具速递页面码并入 view 组（报告端点三页共用）；
# 内部经营报告仍由 router 内 INTERNAL_REPORT_TYPES 二次校验保护，页面码不放行。
_require_insight_view = require_any_permission(
    "insight:read", "insight:internal_read", "insight:admin",
    "insight_library:read", "insight_daily:read", "insight_ai_tools:read")
_require_insight_internal = require_any_permission("insight:internal_read", "insight:admin")
_require_insight_admin = require_permission("insight:admin")
# 案例库 / 周会纪要独立子域（2026-07-12 功能单元拆分）
_require_case_view = require_any_permission(
    "insight_case:read", "insight_case:write", "insight:admin")
_require_minutes_view = require_any_permission(
    "insight_minutes:read", "insight_minutes:write", "insight:admin")
_require_minutes_write = require_any_permission("insight_minutes:write", "insight:admin")


def _verify_import_api_key(authorization: Optional[str] = Header(None)):
    """ACCIO WORK 等外部系统使用 Bearer API Key 认证。"""
    expected = get_settings().INSIGHT_IMPORT_API_KEY.strip()
    if not expected:
        # 未配置时拒绝所有外部导入,防误用
        raise HTTPException(status_code=503, detail="导入接口未启用(INSIGHT_IMPORT_API_KEY 未配置)")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="API Key 无效")
    return True


# ── 客户机会台 / 客户经营雷达权限（同上，统一工厂）──────────
_require_opportunity_read = require_any_permission(
    "customer_opportunity:read", "customer_opportunity:write", "customer_opportunity:manage")
_require_opportunity_write = require_any_permission(
    "customer_opportunity:write", "customer_opportunity:manage")
_require_opportunity_manage = require_permission("customer_opportunity:manage")

_require_radar_read = require_any_permission(
    "customer_radar:read", "customer_radar:write", "customer_radar:manage")
_require_radar_write = require_any_permission("customer_radar:write", "customer_radar:manage")
_require_radar_manage = require_permission("customer_radar:manage")


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
