"""Auth 依赖注入：get_current_user / require_permission"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from app.auth.utils import decode_access_token

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    从 Authorization Bearer Token 解析当前用户信息。
    返回 JWT payload dict（不查库，直接用 JWT 中的数据）。
    """
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token格式错误",
        )

    return payload


def require_permission(*permissions: str):
    """
    权限校验 Dependency Factory

    用法:
        @router.get("/some-endpoint")
        def handler(current_user=Depends(require_permission("commission:read_all"))):
            ...
    """
    def permission_checker(current_user: dict = Depends(get_current_user)):
        roles = current_user.get("roles", [])
        # super_admin 跳过权限检查
        if "super_admin" in roles:
            return current_user

        user_perms = current_user.get("permissions", [])
        for perm in permissions:
            if perm not in user_perms:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"权限不足，需要: {perm}",
                )
        return current_user

    return permission_checker
