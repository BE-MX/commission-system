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
    okki_department_id: Optional[int] = None
    okki_department_name: Optional[str] = Field(None, max_length=100)
    role_ids: list[int] = []


class UserUpdateRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # 部门对按"键是否出现"判断更新（model_fields_set），显式传 null 可清除
    okki_department_id: Optional[int] = None
    okki_department_name: Optional[str] = Field(None, max_length=100)
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
    okki_department_id: Optional[int] = None
    okki_department_name: Optional[str] = None
    dingtalk_id: Optional[str] = None
    is_active: bool
    roles: list[str] = []
    role_ids: list[int] = []
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
    kind: str = "action"       # page=页面可见 / action=操作 / data=数据范围
    sort: int = 0


class PermissionGroupItem(BaseModel):
    module: str
    permissions: list[PermissionItem]


# ── 个人资料 ──────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
