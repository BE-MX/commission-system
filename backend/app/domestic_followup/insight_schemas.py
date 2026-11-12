"""AI 洞见 API 输入与模型输出校验。"""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class InsightRefreshIn(BaseModel):
    user_id: int | None = Field(None, gt=0)


class InsightFeedbackIn(BaseModel):
    feedback: Literal["up", "down"] | None = None


class InsightTaskIn(BaseModel):
    due_date: dt.date
    content: str = Field(min_length=1, max_length=500)


class InsightAdoptIn(BaseModel):
    note: str = Field("", max_length=500)


class InsightItemOut(BaseModel):
    category: Literal["deal", "cold", "rhythm", "method", "common", "single", "practice", "frequency"]
    customer_id: int | None = Field(None, gt=0)
    theme_key: str | None = Field(None, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=8000)
    suggested_action: str | None = Field(None, max_length=2000)
    suggested_date: dt.date | None = None
    signals: list[str] = Field(default_factory=list, max_length=6)
    evidence_followup_ids: list[int] = Field(min_length=1, max_length=5)


class InsightAIOut(BaseModel):
    items: list[InsightItemOut] = Field(default_factory=list, max_length=30)


class PublicInsightOut(BaseModel):
    theme_key: str = Field(max_length=80)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=2000)
    suggested_action: str = Field(min_length=1, max_length=1000)


class PublicInsightsOut(BaseModel):
    items: list[PublicInsightOut] = Field(default_factory=list, max_length=20)
