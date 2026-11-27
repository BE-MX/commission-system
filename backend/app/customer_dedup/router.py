"""Customer dedup endpoint for colleagues' own prospecting tools.

Callers authenticate with their personal Ark token (the same token issued for MCP,
``Authorization: Bearer <token>``) or a normal Ark login session.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import security
from app.auth.models import ArkUser
from app.auth.utils import decode_access_token
from app.core.database import get_db
from app.core.response import ok
from app.customer_dedup import service
from app.customer_dedup.normalize import PLATFORM_LABELS, DedupInputError, build_lookup
from app.invoice.xiaoman_service import resolve_okki_user_id
from app.mcp.auth import MCPAuthError, build_current_user, resolve_token

router = APIRouter()
PERMISSION = "customer_dedup:read"


class DedupCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account: str = Field(..., min_length=1, max_length=500, description="账号、主页链接、WhatsApp 号码或邮箱")
    platform: str | None = Field(
        None, max_length=32,
        description="平台（instagram/facebook/whatsapp/wechat/linkedin/pinterest/tiktok/x/yelp/youtube/email）；"
                    "提交完整链接或邮箱时可省略",
    )


def require_dedup_caller(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """Personal token or login JWT, then ``customer_dedup:read`` (super_admin bypasses).

    Both paths re-read the user and their current roles from the database, so a
    disabled account or a revoked permission stops working immediately rather than
    when the login JWT expires.
    """
    raw = credentials.credentials.strip()
    if raw.count(".") == 2:  # compact JWT: a login session (personal tokens are opaque)
        try:
            claims = decode_access_token(raw)
        except JWTError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录或改用个人 token") from exc
        # Only main-site login tokens count: Agent Run (aud/run_id), mini-program
        # (source="mini", 7-day life) and other purpose-bound JWTs are rejected.
        is_login = (
            str(claims.get("sub") or "").isdigit()
            and "username" in claims and "permissions" in claims
            and not any(claims.get(k) for k in ("aud", "run_id", "source", "purpose"))
        )
        if not is_login:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "该 token 不能用于客户查重")
        user = db.query(ArkUser).filter(ArkUser.id == int(claims["sub"])).first()
        if not user or not user.is_active or user.deleted_at is not None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已被禁用")
        identity = dict(build_current_user(user))
        identity["_auth_channel"] = "session"
    else:
        try:
            identity = dict(resolve_token(db, raw))
        except MCPAuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        identity["_auth_channel"] = "personal_token"
    if not identity.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误")
    if "super_admin" not in identity.get("roles", []) and PERMISSION not in identity.get("permissions", []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"权限不足，需要: {PERMISSION}")
    return identity


@router.post("/check", summary="按社媒账号或邮箱查重客户归属")
def check_customer(
    payload: DedupCheckRequest,
    db: Session = Depends(get_db),
    caller: dict = Depends(require_dedup_caller),
):
    try:
        lookup = build_lookup(payload.account, payload.platform)
    except DedupInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    user_id = int(caller["sub"])
    okki_id = resolve_okki_user_id(db, user_id)
    try:
        result = service.check(
            db, lookup,
            user_id=user_id,
            auth_channel=caller["_auth_channel"],
            my_okki_id=str(okki_id) if okki_id else None,
        )
    except service.Inconclusive as exc:
        return ok({
            "status": service.STATUS_INCONCLUSIVE, "message": str(exc), "platform": lookup.platform,
            "platform_label": PLATFORM_LABELS[lookup.platform], "normalized_account": lookup.key,
            "matched_count": None, "customers": [],
        }, message=str(exc))
    except service.RateLimited as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except service.AuditUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return ok(result, message=result["message"])
