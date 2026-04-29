"""用户/角色管理 Pydantic 模型"""

from pydantic import BaseModel, Field
from typing import Optional


# ── 用户 ──────────────────────────────────────────────

class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    real_name: str = Field(..., min_length=1, max_length=50)
    email: Optional[str] = None
    phone: Optional[str] = None
    role_ids: list[int] = []


class UserUpdateRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    role_ids: Optional[list[int]] = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=6)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


class UserListItem(BaseModel):
    id: int
    username: str
    real_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    roles: list[str] = []
    last_login_at: Optional[str] = None
    created_at: str


# ── 角色 ──────────────────────────────────────────────

class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    permission_ids: list[int] = []


class RoleUpdateRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[list[int]] = None


class RoleListItem(BaseModel):
    id: int
    name: str
    label: str
    description: Optional[str] = None
    is_system: bool
    user_count: int
    permission_count: int
    permission_ids: list[int] = []
    created_at: str


# ── 权限 ──────────────────────────────────────────────

class PermissionItem(BaseModel):
    id: int
    code: str
    label: str
    action: str


class PermissionGroupItem(BaseModel):
    module: str
    permissions: list[PermissionItem]


# ── 个人资料 ──────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
