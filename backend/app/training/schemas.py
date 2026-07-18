"""培训速递 — Pydantic Schemas 与模板分区定义

sections_json 的结构由 DigestSections 定义；★必填分区的发布校验在
digest_service.validate_for_publish（草稿随便存，发布才卡）。
"""

from datetime import date
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


# 列表/详情响应由 service 层手拼 dict（含 creator_name/file_count 等联查字段），
# 不在此重复定义 response_model，避免双份定义漂移（2026-07-17 对抗性审查 P2-10）
