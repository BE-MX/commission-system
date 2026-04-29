"""Auth Pydantic 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)


class UserInfo(BaseModel):
    id: int
    username: str
    real_name: str
    roles: list[str] = []
    permissions: list[str] = []
    must_change_password: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class MeResponse(BaseModel):
    id: int
    username: str
    real_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    roles: list[str] = []
    permissions: list[str] = []
    must_change_password: bool = False
    last_login_at: Optional[str] = None
    created_at: Optional[str] = None
