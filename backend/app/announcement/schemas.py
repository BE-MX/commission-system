from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class AnnouncementInput(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    content: dict
    category_id: int = Field(gt=0)
    base_revision_id: int | None = None
    important: bool = False
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    change_note: str = Field(default='', max_length=500)


class CategoryInput(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    active: bool = True


class ReviewInput(BaseModel):
    approve: bool
    remark: str = Field(default='', max_length=500)


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class PinInput(BaseModel):
    pinned: bool


class ConfigInput(BaseModel):
    version: int = Field(ge=1)
    group_name: str = Field(max_length=120)
    conversation_id: str = Field(max_length=256)
    robot_code: str = Field(max_length=128)
    delivery_enabled: bool = False
    weekly_enabled: bool = False
    weekly_hour: int = Field(default=9, ge=0, le=23)
    weekly_minute: int = Field(default=0, ge=0, le=59)
    preset_name: str = Field(default='', max_length=100)
    executor_id: int = Field(gt=0)


class RetryInput(BaseModel):
    confirm_uncertain: bool = False
    mark_delivered: bool = False
    cancel: bool = False


class WeeklyInput(BaseModel):
    regenerate: bool = False


class VerifyInput(BaseModel):
    test_key: str = Field(min_length=1, max_length=80)
    images_visible: Literal[True]
