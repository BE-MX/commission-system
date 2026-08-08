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
