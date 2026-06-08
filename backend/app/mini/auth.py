"""微信小程序端认证依赖 — JWT 解析 & 微信 jscode2session"""

import httpx
from datetime import timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.utils import create_access_token, decode_access_token
from app.core.config import get_settings
from app.core.database import get_db

settings = get_settings()
_bearer = HTTPBearer()


def get_current_mini_user(
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> ArkUser:
    """解析小程序 Bearer Token，返回 ArkUser ORM 对象"""
    try:
        payload = decode_access_token(cred.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_EXPIRED", "message": "登录已过期"})

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_EXPIRED", "message": "无效 Token"})

    user = db.query(ArkUser).get(int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail={"code": "TOKEN_EXPIRED", "message": "用户不存在或已禁用"})

    return user


def create_mini_token(user_id: int, wx_id: str) -> str:
    """生成小程序专用 JWT（7 天有效）"""
    return create_access_token(
        data={"sub": str(user_id), "user_id": user_id, "wx_id": wx_id, "source": "mini"},
        expires_delta=timedelta(days=7),
    )


async def jscode2session(code: str) -> dict:
    """调用微信 jscode2session 接口，返回 {openid, session_key, ...}"""
    url = (
        f"https://api.weixin.qq.com/sns/jscode2session"
        f"?appid={settings.WX_MINI_APPID}"
        f"&secret={settings.WX_MINI_SECRET}"
        f"&js_code={code}"
        f"&grant_type=authorization_code"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        data = resp.json()

    if "errcode" in data and data["errcode"] != 0:
        raise ValueError(f"微信接口错误: {data.get('errmsg', 'unknown')}")

    return data
