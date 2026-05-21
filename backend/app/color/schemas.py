"""发色数字化 — Pydantic 请求/响应模型"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ── 通用响应包装 ─────────────────────────────────────────
class ColorCalcResult(BaseModel):
    hex: str
    rgb: List[int]
    lab: List[float]
    hsl: List[float]


class DeltaEResult(BaseModel):
    delta_e_2000: float
    perceptible: bool
    acceptable: bool


class PantoneMatchResult(BaseModel):
    pantone_code: str
    pantone_name: Optional[str]
    delta_e: float


class BlendResult(BaseModel):
    computed_hex: str
    lab: List[float]
    nearest_pantone: Optional[PantoneMatchResult] = None


class DominantColor(BaseModel):
    hex: str
    rgb: List[int]
    percentage: float


class SwatchVerifyResult(BaseModel):
    target_hex: str
    actual_hex: str
    delta_e: float
    pass_check: bool


# ── 色彩计算请求 ─────────────────────────────────────────
class ConvertRequest(BaseModel):
    input: str = Field(..., description="任意色彩值，如 #6B5A52 或 rgb(107,90,82)")
    format: str = Field("hex", description="输入格式: hex/rgb/lab/hsl")


class BlendRequest(BaseModel):
    components: List[dict] = Field(..., description='[{"color_id": int, "weight": float}, ...]')


class DeltaERequest(BaseModel):
    color_a: str
    color_b: str


class PantoneMatchRequest(BaseModel):
    hex: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")


class MatchLeshineRequest(BaseModel):
    hex: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")


class ExtractColorRequest(BaseModel):
    k: int = Field(5, ge=1, le=10, description="提取主色数量")


# ── 色号 CRUD ────────────────────────────────────────────
class PaletteCreate(BaseModel):
    industry_code: str = Field(..., max_length=20)
    brand_code: Optional[str] = Field(None, max_length=50)
    display_name: str = Field(..., max_length=100)
    display_name_en: Optional[str] = Field(None, max_length=100)
    hex_code: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    undertone: Optional[str] = Field(None, pattern=r"^(warm|cool|neutral)$")
    luminance_level: Optional[str] = Field(None, pattern=r"^(low|medium-low|medium|medium-high|high|very-high)$")
    color_family: str = Field(..., pattern=r"^(black|brown|blonde|red|silver|vibrant)$")
    pantone_tcx: Optional[str] = Field(None, max_length=30)
    pantone_delta_e: Optional[float] = None
    source: str = Field("industry", pattern=r"^(industry|bellami|luxy|great_lengths|leshine|organic_hair)$")
    is_leshine_stock: bool = False
    peak_season: Optional[str] = None


class PaletteUpdate(BaseModel):
    industry_code: Optional[str] = Field(None, max_length=20)
    brand_code: Optional[str] = Field(None, max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    display_name_en: Optional[str] = Field(None, max_length=100)
    hex_code: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    undertone: Optional[str] = Field(None, pattern=r"^(warm|cool|neutral)$")
    luminance_level: Optional[str] = Field(None, pattern=r"^(low|medium-low|medium|medium-high|high|very-high)$")
    color_family: Optional[str] = Field(None, pattern=r"^(black|brown|blonde|red|silver|vibrant)$")
    pantone_tcx: Optional[str] = Field(None, max_length=30)
    pantone_delta_e: Optional[float] = None
    source: Optional[str] = Field(None, pattern=r"^(industry|bellami|luxy|great_lengths|leshine|organic_hair)$")
    is_leshine_stock: Optional[bool] = None
    peak_season: Optional[str] = None


class PaletteOut(BaseModel):
    id: int
    industry_code: str
    brand_code: Optional[str]
    display_name: str
    display_name_en: Optional[str]
    hex_code: str
    rgb_r: int
    rgb_g: int
    rgb_b: int
    lab_l: Optional[float]
    lab_a: Optional[float]
    lab_b_val: Optional[float]
    hsl_h: Optional[int]
    hsl_s: Optional[float]
    hsl_l: Optional[float]
    undertone: Optional[str]
    luminance_level: Optional[str]
    color_family: str
    pantone_tcx: Optional[str]
    pantone_delta_e: Optional[float]
    source: str
    is_leshine_stock: bool
    peak_season: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── 混合色 CRUD ──────────────────────────────────────────
class BlendComponentCreate(BaseModel):
    palette_id: int
    position: str = Field("even", pattern=r"^(root|mid|end|highlight|even)$")
    weight: float = Field(0.5, ge=0.0, le=1.0)
    sort_order: int = Field(0, ge=0)


class BlendCreate(BaseModel):
    blend_code: str = Field(..., max_length=30)
    display_name: str = Field(..., max_length=100)
    display_name_en: Optional[str] = Field(None, max_length=100)
    blend_type: str = Field(..., pattern=r"^(piano|ombre|balayage|rooted|tri-blend|multi-blend)$")
    source: str = Field(..., pattern=r"^(bellami|luxy|great_lengths|leshine|organic_hair|custom)$")
    brand_name: Optional[str] = Field(None, max_length=100)
    components: List[BlendComponentCreate]


class BlendUpdate(BaseModel):
    blend_code: Optional[str] = Field(None, max_length=30)
    display_name: Optional[str] = Field(None, max_length=100)
    display_name_en: Optional[str] = Field(None, max_length=100)
    blend_type: Optional[str] = Field(None, pattern=r"^(piano|ombre|balayage|rooted|tri-blend|multi-blend)$")
    source: Optional[str] = Field(None, pattern=r"^(bellami|luxy|great_lengths|leshine|organic_hair|custom)$")
    brand_name: Optional[str] = Field(None, max_length=100)
    components: Optional[List[BlendComponentCreate]] = None


class BlendComponentOut(BaseModel):
    id: int
    palette_id: int
    position: str
    weight: float
    sort_order: int
    palette: Optional[PaletteOut] = None

    class Config:
        from_attributes = True


class BlendOut(BaseModel):
    id: int
    blend_code: str
    display_name: str
    display_name_en: Optional[str]
    blend_type: str
    computed_hex: Optional[str]
    computed_lab_l: Optional[float]
    computed_lab_a: Optional[float]
    computed_lab_b: Optional[float]
    source: str
    brand_name: Optional[str]
    components: List[BlendComponentOut] = []
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── 色板图生成 ───────────────────────────────────────────
class SwatchGenerateRequest(BaseModel):
    color_id: Optional[int] = None
    blend_id: Optional[int] = None
    style: str = Field("swatch_card", pattern=r"^(swatch_card|hair_strand|model_preview)$")
    background: str = Field("white", pattern=r"^(white|grey|transparent)$")


class BatchSwatchRequest(BaseModel):
    color_ids: List[int]
    style: str = Field("swatch_card", pattern=r"^(swatch_card|hair_strand|model_preview)$")


class SwatchOut(BaseModel):
    id: int
    palette_id: Optional[int]
    blend_id: Optional[int]
    model_used: str
    image_url: Optional[str]
    target_hex: str
    actual_hex: Optional[str]
    delta_e: Optional[float]
    pass_check: Optional[bool]
    status: str
    retry_count: int
    created_at: str

    class Config:
        from_attributes = True


# ── 趋势数据 ─────────────────────────────────────────────
class TrendOverviewItem(BaseModel):
    color_family: str
    current_score: float
    trend: str  # rising / stable / falling
    change_pct: float


class TrendPredictionItem(BaseModel):
    color_family: str
    score: float
    trend: str


class TrendHistoryQuery(BaseModel):
    color_family: Optional[str] = None
    data_source: Optional[str] = None
    period_type: str = "weekly"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
