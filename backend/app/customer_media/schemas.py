"""客户素材交付 API 输入模型。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 255 or normalized.count("@") != 1:
        raise ValueError("请输入有效邮箱")
    local, domain = normalized.rsplit("@", 1)
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("请输入有效邮箱")
    return normalized


def _password(value: str) -> str:
    if not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("密码至少包含一个字母和一个数字")
    return value


class BatchReviewIn(BaseModel):
    action: Literal["approve", "request_changes"]
    comment: str | None = Field(default=None, max_length=4000)
    lock_version: int = Field(gt=0)

    @field_validator("comment")
    @classmethod
    def require_rejection_comment(cls, value, info):
        if info.data.get("action") == "request_changes" and not (value or "").strip():
            raise ValueError("退回时必须填写修改原因")
        return value.strip() if value else None


class BatchSubmitIn(BaseModel):
    lock_version: int = Field(gt=0)


class PortalAccountCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    login_email: str
    password: str = Field(min_length=10, max_length=128)

    @field_validator("login_email")
    @classmethod
    def validate_email(cls, value):
        return _email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return _password(value)


class PortalAccountUpdate(BaseModel):
    login_email: str | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)
    is_active: bool | None = None

    @field_validator("login_email")
    @classmethod
    def validate_email(cls, value):
        return _email(value) if value is not None else None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return _password(value) if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if self.login_email is None and self.password is None and self.is_active is None:
            raise ValueError("至少提交一项账号变更")
        return self


class PortalLoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return _email(value)
