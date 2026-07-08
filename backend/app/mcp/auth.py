"""MCP 个人 token 鉴权 — 把 opaque token 解析成与登录一致的 current_user dict。

核心:token → ark_mcp_tokens 查活跃行 → 载入 ArkUser → 复用 auth.service 的
claims builder（get_user_roles / get_user_permissions）→ 产出 current_user dict。
下游 tracking service 吃的就是这个 dict，零改动复用 apply_data_scope 归属过滤。
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_user_roles, get_user_permissions
from app.auth.utils import hash_token
from app.mcp.models import MCPToken

logger = logging.getLogger("commission.mcp.auth")


class MCPAuthError(Exception):
    """token 缺失/无效/停用/用户禁用。message 直接回给 agent。"""


def build_current_user(user: ArkUser) -> dict:
    """产出与 get_current_user（JWT payload）完全一致结构的 dict。"""
    return {
        "sub": str(user.id),
        "username": user.username,
        "roles": get_user_roles(user),
        "permissions": get_user_permissions(user),
    }


def resolve_token(db: Session, raw_token: str) -> dict:
    """校验 token 并返回 current_user dict；失败抛 MCPAuthError。

    成功时顺带刷新 last_used_at（best-effort，失败不阻断）。
    """
    if not raw_token or not raw_token.strip():
        raise MCPAuthError("缺少 access token：请在 Authorization: Bearer <token> 头中携带个人 token")

    token_hash = hash_token(raw_token.strip())
    row = (
        db.query(MCPToken)
        .filter(MCPToken.token_hash == token_hash, MCPToken.is_active == True)  # noqa: E712
        .first()
    )
    if not row:
        raise MCPAuthError("access token 无效或已被撤销，请联系管理员重新发放")

    user = db.query(ArkUser).filter(ArkUser.id == row.user_id).first()
    if not user or not user.is_active or user.deleted_at is not None:
        raise MCPAuthError("token 对应的账号不存在或已被禁用")

    identity = build_current_user(user)

    # best-effort 更新最后使用时间
    try:
        row.last_used_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("刷新 mcp_token.last_used_at 失败 token_id=%s err=%s", row.id, exc)
        print(f"[mcp.auth] last_used_at update failed id={row.id} err={exc}", flush=True)

    return identity


def _extract_bearer_from_ctx(ctx) -> str:
    """从 FastMCP Context 拿 Authorization 头（streamable HTTP 下为 Starlette Request）。"""
    req = getattr(getattr(ctx, "request_context", None), "request", None)
    if req is None:
        raise MCPAuthError("无法获取请求上下文（该工具仅支持 HTTP 传输）")
    auth = req.headers.get("authorization") or req.headers.get("Authorization") or ""
    auth = auth.strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return auth


def require_identity(ctx, db: Session) -> dict:
    """工具内统一入口：读请求头 → resolve_token → current_user dict。

    在工具自身的执行上下文里解析（不依赖 contextvar 跨 task 传播），失败抛 MCPAuthError。
    """
    raw = _extract_bearer_from_ctx(ctx)
    return resolve_token(db, raw)
