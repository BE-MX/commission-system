"""工作台配置 — Pydantic Schema

只校验形状（列表类型 / 条目长度 / 数量上限），不校验卡片 key 合法性——
key 的真相源在前端注册表 cards.js，未知 key 前端渲染时忽略，天然向前兼容。
extra="ignore"：将来 prefs 加新分区时，老后端不拒绝新前端的 payload（共库过渡期约定）。
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CardKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class SectionPrefs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hidden: list[CardKey] = Field(default_factory=list, max_length=100)
    order: list[CardKey] = Field(default_factory=list, max_length=100)


class DashboardPrefs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = Field(1, ge=1, le=100)
    metrics: SectionPrefs = Field(default_factory=SectionPrefs)
    actions: SectionPrefs = Field(default_factory=SectionPrefs)
