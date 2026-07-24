"""Pydantic schemas for the expo try-on module."""

from pydantic import BaseModel, Field


class CustomerRegister(BaseModel):
    name: str = Field(..., max_length=64, description="称呼")
    phone: str = Field(..., max_length=32)
    wechat_id: str | None = Field(None, max_length=64)
    primary_need: str = Field("volume", pattern="^(volume|gray_cover|style_change)$")
    style_pref: str | None = Field(None, max_length=32)
    consent: bool = Field(..., description="必须同意拍照存储")
    expo_code: str = Field("", max_length=64)


class GenerateRequest(BaseModel):
    wig_ids: list[int] | None = Field(None, description="不传则取匹配排名第一批（tryon 模式）")
    batch: int = Field(0, ge=0, le=3, description="换一批批次，0=Top3，1=第4~6名（tryon 模式）")
    hair_color_id: int | None = Field(None, description="发色库 ark_expo_hair_colors.id，不传则保持发型原色（tryon 模式）")
    scene_key: str | None = Field(None, max_length=32, description="tryon 生成场景 key（home/office/gathering），不传保持原照片背景")
    scene_keys: list[str] | None = Field(None, max_length=6, description="场景 key 列表，不传则取默认前 3 个（scene 模式）")


class ReactionRequest(BaseModel):
    reaction: str = Field(..., pattern="^(loved|soso)$")


class FeedbackCreate(BaseModel):
    session_id: int | None = None
    intent_level: str = Field(..., pattern="^[ABCD]$")
    notes: str | None = None
    next_action: str | None = Field(None, max_length=64)


class WigUpsert(BaseModel):
    model_no: str = Field(..., max_length=64)
    name: str = Field(..., max_length=128)
    series: str = Field("classic", pattern="^(classic|zhizhen)$")
    product_id: int | None = None
    cover_path: str | None = None
    angle_photos: list[str] | None = None
    wig_description: str | None = None
    composite_prompt: str | None = None
    fit_tags: dict | None = None
    selling_points: str | None = None
    sales_description: str | None = None
    evidence_refs: list | None = None
    priority: int = 0
    must_recommend: int = Field(0, ge=0, le=1, description="1=主推(置顶推荐列表最前,仍按性别过滤)")
    is_active: int = Field(1, ge=0, le=1)


class HairColorUpsert(BaseModel):
    code: str = Field(..., max_length=64, description="色号，如 1B / 613")
    name: str = Field(..., max_length=128)
    hex_code: str | None = Field(None, max_length=16, description="UI 色块，如 #5a3a26")
    swatch_path: str | None = Field(None, max_length=512, description="色板图相对路径")
    color_description: str | None = Field(None, description="喂给合成 prompt 的颜色描述")
    priority: int = 0
    is_active: int = Field(1, ge=0, le=1)


class WigColorImagesUpsert(BaseModel):
    """发型×发色组合的三角度参考图上传（管理端）。路径由 /wigs/upload-photo 先取得。"""

    angle_photos: list[str] = Field(..., min_length=1, max_length=3, description="三角度参考图相对路径（1~3 张）")
    cover_path: str | None = Field(None, max_length=512, description="缩略图相对路径，不传取首张")
    is_active: int = Field(1, ge=0, le=1)


class ScriptUpsert(BaseModel):
    script_type: str = Field(..., pattern="^(opener|demo|objection|closer|faq)$")
    track: str = Field("emotional", pattern="^(emotional|rational|identity)$")
    title: str = Field(..., max_length=128)
    audience_tags: list[str] | None = None
    content: str
    evidence_points: list[str] | None = None
    is_active: int = Field(1, ge=0, le=1)
