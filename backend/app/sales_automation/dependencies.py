"""智能获客 Agent 的可撤销 token 鉴权。"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth.dependencies import security
from app.core.database import get_db
from app.mcp.auth import MCPAuthError, resolve_token


def require_sales_agent(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    try:
        identity = resolve_token(db, credentials.credentials)
    except MCPAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    if "sales_automation:invoke" not in identity.get("permissions", []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent token 缺少 sales_automation:invoke")
    return identity


def require_sales_agent_for_identity_write(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """Acquire portal authority before token resolution opens a read snapshot."""
    from app.portal.authority import lock_authority
    from app.portal.errors import PortalError

    try:
        lock_authority(db)
    except PortalError as exc:
        raise HTTPException(503, "授权服务暂不可用") from exc
    try:
        identity = resolve_token(db, credentials.credentials, commit_usage=False)
    except MCPAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    if "sales_automation:invoke" not in identity.get("permissions", []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent token 缺少 sales_automation:invoke")
    return identity
