"""培训速递 — Pydantic Schemas 与模板分区定义

sections_json 的结构由 DigestSections 定义；★必填分区的发布校验在
digest_service.validate_for_publish（草稿随便存，发布才卡）。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 模板分区（V1 培训模板；将来扩展类型时按 digest_type 挑模板）
# ---------------------------------------------------------------------------

class SectionHighlight(BaseModel):
    """重点条目：一句话标题 + 一段展开"""
    title: str = ""
    detail: str = ""


class SectionApplication(BaseModel):
    """可应用点：内容 + 适用岗位 + 落地第一步（岗位与第一步由人拍板）"""
    point: str = ""
    roles: list[str] = Field(default_factory=list)
    first_step: str = ""


class SectionMethod(BaseModel):
    """方法与技巧：名称 + 可操作步骤"""
    name: str = ""
    steps: str = ""


class DigestSections(BaseModel):
    highlights: list[SectionHighlight] = Field(default_factory=list)
    new_insights: list[str] = Field(default_factory=list)
    applications: list[SectionApplication] = Field(default_factory=list)
    methods: list[SectionMethod] = Field(default_factory=list)
    review: str = ""  # 参训人点评，AI 不代写


# ---------------------------------------------------------------------------
# 请求/响应
# ---------------------------------------------------------------------------

class DigestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    org: Optional[str] = Field(default=None, max_length=120)
    lecturer: Optional[str] = Field(default=None, max_length=120)
    trained_at: date
    attendees: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class DigestUpdate(BaseModel):
    """编辑保存（草稿或已发布均可），全部可选，只更新传入字段"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    org: Optional[str] = Field(default=None, max_length=120)
    lecturer: Optional[str] = Field(default=None, max_length=120)
    trained_at: Optional[date] = None
    attendees: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    summary: Optional[str] = Field(default=None, max_length=200)
    sections: Optional[DigestSections] = None


class DraftRequest(BaseModel):
    """AI 提炼请求：粘贴的文字材料；图片/PDF 从已上传附件读取"""
    text_materials: str = Field(default="", max_length=60000)


class DigestListItem(BaseModel):
    id: int
    digest_type: str
    title: str
    org: Optional[str]
    lecturer: Optional[str]
    trained_at: Optional[date]
    tags: list[str]
    summary: Optional[str]
    status: str
    read_minutes: int
    view_count: int
    useful_count: int
    created_by: int
    creator_name: Optional[str] = None
    published_at: Optional[datetime]
    file_count: int = 0


class DigestDetail(DigestListItem):
    attendees: list[str]
    sections: DigestSections
    files: list[dict]
    my_useful: bool = False
    can_edit: bool = False
