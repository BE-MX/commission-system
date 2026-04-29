"""Auth 路由 /api/auth/*"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import get_current_user
from app.auth.schemas import LoginRequest, LoginResponse, UserInfo, MeResponse
from app.auth.service import (
    authenticate_user,
    get_user_by_username,
    get_user_roles,
    get_user_permissions,
    InvalidCredentialsException,
    AccountLockedException,
    AccountDisabledException,
)
from app.core.config import get_settings

settings = get_settings()

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """用户登录"""
    ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    try:
        access_token, refresh_token, user_info = authenticate_user(
            db, body.username, body.password, ip, user_agent,
        )
    except InvalidCredentialsException:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    except AccountLockedException as e:
        raise HTTPException(status_code=423, detail=str(e))
    except AccountDisabledException as e:
        raise HTTPException(status_code=403, detail=str(e))

    # 设置 Refresh Token Cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/api/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )

    return LoginResponse(
        access_token=access_token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user=UserInfo(**user_info),
    )


@router.get("/me", response_model=MeResponse)
def get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前登录用户信息"""
    user_id = int(current_user["sub"])
    from app.auth.models import ArkUser
    user = db.get(ArkUser, user_id)
    if not user or not user.is_active or user.deleted_at:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    roles = get_user_roles(user)
    permissions = get_user_permissions(user)

    return MeResponse(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        email=user.email,
        phone=user.phone,
        avatar_url=user.avatar_url,
        roles=roles,
        permissions=permissions,
        must_change_password=bool(user.must_change_password),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )
