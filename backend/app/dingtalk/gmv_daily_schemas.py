"""钉钉 GMV 日报配置与操作请求。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GmvMemberConfig(BaseModel):
    okki_user_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    exclude_from_total: bool = False
    is_active: bool = True

    @field_validator("okki_user_id", "name", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GmvTeamConfig(BaseModel):
    department_id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1, max_length=128)
    captain_okki_user_id: str = Field(..., min_length=1, max_length=64)
    is_active: bool = True
    members: list[GmvMemberConfig] = Field(..., min_length=1, max_length=200)

    @field_validator("name", "captain_okki_user_id", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GmvDailyConfigUpdate(BaseModel):
    teams: list[GmvTeamConfig] = Field(..., min_length=1, max_length=50)
    admin_recipient_user_ids: list[int] = Field(..., min_length=1, max_length=50)

    @field_validator("admin_recipient_user_ids")
    @classmethod
    def validate_admin_recipients(cls, value: list[int]) -> list[int]:
        if any(user_id <= 0 for user_id in value):
            raise ValueError("管理员接收人 ID 必须为正整数")
        if len(set(value)) != len(value):
            raise ValueError("管理员接收人不能重复")
        return value


class GmvDailyPreviewRequest(BaseModel):
    report_date: date | None = None


class GmvDailySendRequest(BaseModel):
    report_date: date | None = None
    scope: Literal["all", "teams", "admins"] = "all"
