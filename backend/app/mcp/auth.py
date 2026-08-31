"""MCP 个人 token 鉴权 — 把 opaque token 解析成与登录一致的 current_user dict。

核心:token → ark_mcp_tokens 查活跃行 → 载入 ArkUser → 复用 auth.service 的
claims builder（get_user_roles / get_user_permissions）→ 产出 current_user dict。
下游 tracking service 吃的就是这个 dict，零改动复用 apply_data_scope 归属过滤。
"""

import logging
from datetime import datetime
from app.core.time import beijing_now, utc_now_naive

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_user_roles, get_user_permissions
from app.auth.utils import hash_token
from app.mcp.models import MCPToken
from app.agent_runtime.contracts import RunStatus
from app.agent_runtime.errors import AgentRuntimeError
from app.agent_runtime.models import AgentProfile, AgentRun
from app.agent_runtime.token_service import decode_run_token

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
        row.last_used_at = beijing_now()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("刷新 mcp_token.last_used_at 失败 token_id=%s err=%s", row.id, exc)
        print(f"[mcp.auth] last_used_at update failed id={row.id} err={exc}", flush=True)

    return identity


def resolve_run_token(db: Session, raw_token: str) -> dict:
    """Resolve a short-lived Agent Run JWT into a user plus tool scope."""
    try:
        claims = decode_run_token(raw_token.strip())
        run_id = int(claims["run_id"])
        profile_id = int(claims["profile_id"])
        user_id = int(claims["sub"])
    except (AgentRuntimeError, KeyError, TypeError, ValueError) as exc:
        raise MCPAuthError("Agent Run access token 无效或已过期") from exc

    run = db.query(AgentRun).filter(AgentRun.id == run_id).one_or_none()
    profile = db.query(AgentProfile).filter(AgentProfile.id == profile_id).one_or_none()
    user = db.query(ArkUser).filter(ArkUser.id == user_id).one_or_none()
    if run is None or profile is None or user is None or not user.is_active or user.deleted_at is not None:
        raise MCPAuthError("Agent Run 委托范围不存在")
    if (
        run.profile_id != profile.id
        or run.owner_user_id != user.id
        or claims.get("session_id") != run.session_id
        or claims.get("profile_key") != profile.profile_key
        or claims.get("runtime") != run.source_runtime
        or claims.get("attempt_no") != run.attempt_no
        or claims.get("lease_nonce") != run.lease_token_hash
    ):
        raise MCPAuthError("Agent Run 委托范围与当前任务不匹配")
    if run.status not in {RunStatus.RUNNING.value, RunStatus.WAITING_INPUT.value}:
        raise MCPAuthError("Agent Run 尚未开始或已经结束")
    if run.cancel_requested or profile.status != "active":
        raise MCPAuthError("Agent Run 已取消或 Profile 已停用")
    if run.lease_expires_at is None or run.lease_expires_at <= utc_now_naive():
        raise MCPAuthError("Agent Run 租约已过期")

    current = build_current_user(user)
    delegated_permissions = set(claims.get("permissions") or [])
    delegated_roles = set(claims.get("roles") or [])
    snapshot = run.context_snapshot or {}
    if (
        delegated_permissions != set(snapshot.get("permissions") or [])
        or delegated_roles != set(snapshot.get("roles") or [])
    ):
        raise MCPAuthError("Agent Run 委托身份与任务快照不匹配")
    if "agent_runtime:invoke" not in delegated_permissions:
        raise MCPAuthError("Agent Run 委托令牌缺少 Agent 调用权限")
    if (
        "super_admin" not in set(current.get("roles") or [])
        and "agent_runtime:invoke" not in set(current.get("permissions") or [])
    ):
        raise MCPAuthError("当前账号的 Agent 调用权限已被撤销")
    current["permissions"] = sorted(set(current["permissions"]) & delegated_permissions)
    # A role granted after Run creation must not expand frozen delegated
    # authority (especially the super_admin bypass used by business tools).
    current["roles"] = sorted(set(current["roles"]) & delegated_roles)
    current["_agent_run"] = {
        "run_id": run.id,
        "profile_id": profile.id,
        "tools": list(profile.tool_allowlist or []),
        "business_ref_type": run.business_ref_type,
        "business_ref_id": run.business_ref_id,
        "customer_id": (run.input_json or {}).get("customer_id"),
        "max_data_classification": (profile.policy_json or {}).get(
            "max_data_classification",
            "internal_business",
        ),
        "max_visibility_scope": (profile.policy_json or {}).get(
            "max_visibility_scope",
            "customer_team",
        ),
    }
    if set(claims.get("tools") or []) != set(profile.tool_allowlist or []):
        raise MCPAuthError("Agent Run 工具范围与 Profile 版本不匹配")
    return current


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


def require_identity(ctx, db: Session, *, tool_name: str | None = None) -> dict:
    """工具内统一入口：读请求头 → resolve_token → current_user dict。

    在工具自身的执行上下文里解析（不依赖 contextvar 跨 task 传播），失败抛 MCPAuthError。
    """
    raw = _extract_bearer_from_ctx(ctx)
    # Personal tokens are opaque; Run Tokens are compact JWTs.  Route by
    # credential shape so an invalid/expired delegated token never falls back
    # to the unrelated personal-token error path.
    identity = resolve_run_token(db, raw) if raw.count(".") == 2 else resolve_token(db, raw)
    scope = identity.get("_agent_run")
    if scope is not None:
        if not tool_name:
            raise MCPAuthError("Agent 工具调用缺少服务端工具标识")
        if tool_name not in set(scope.get("tools") or []):
            raise MCPAuthError(f"Agent Run 无权调用工具 {tool_name}")
    return identity
