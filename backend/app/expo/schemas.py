"""Pydantic schemas for the expo try-on module."""

import re
import unicodedata

from pydantic import BaseModel, Field, field_validator


class CustomerRegister(BaseModel):
    name: str = Field(..., max_length=64, description="称呼")
    phone: str = Field(..., max_length=32, description="11 位手机号，落库前归一为纯数字")
    wechat_id: str | None = Field(None, max_length=64)
    primary_need: str = Field("volume", pattern="^(volume|gray_cover|style_change)$")
    style_pref: str | None = Field(None, max_length=32)
    consent: bool = Field(..., description="必须同意拍照存储")
    expo_code: str = Field("", max_length=64)

    @field_validator("phone")
    @classmethod
    def _normalise_phone(cls, raw: str) -> str:
        """先归一再校验，而不是直接卡格式。

        展位是触屏输入、客户自己填，「138 0013 8000」「138-0013-8000」「+86138…」
        都是常见写法。这些不是错误输入，只是写法差异——系统能推断的就别退回去让
        客户重填（这条是产品原则，不是代码洁癖）。NFKC 顺带把中文输入法的全角
        数字折成半角，否则客户会遇到「明明填了 11 位却说格式不对」的鬼故事。

        归一后的纯数字是**落库值**：phone 同时用于线索台关键词检索与 mask_phone
        脱敏，库里混着「138-0013-8000」和「13800138000」会让检索静默漏命中。
        """
        digits = re.sub(r"\D", "", unicodedata.normalize("NFKC", raw or ""))
        if len(digits) == 13 and digits.startswith("86"):
            digits = digits[2:]          # +86 前缀是写法不是内容
        if len(digits) != 11:
            raise ValueError("手机号需为 11 位数字")
        return digits


class GenerateRequest(BaseModel):
    wig_ids: list[int] | None = Field(None, description="不传则取匹配排名第一批（tryon 模式）")
    batch: int = Field(0, ge=0, le=3, description="换一批批次，0=Top3，1=第4~6名（tryon 模式）")
    hair_color_id: int | None = Field(None, description="发色库 ark_expo_hair_colors.id，不传则保持发型原色（tryon 模式）")
    scene_key: str | None = Field(None, max_length=32, description="tryon 生成场景 key（home/office/gathering），不传保持原照片背景")
    scene_keys: list[str] | None = Field(None, max_length=6, description="场景 key 列表，不传则取默认前 3 个（scene 模式）")
    # 值域收在 pattern 里而不是自由字符串：这个值会直接进上游请求参数，
    # 放开等于把上游 400 的口子留给前端。
    # **2026-07-31 起 kiosk 不再传这个值**：实测云雾中转站不透传 quality，三档耗时
    # (165~180s)、体积、output_tokens、目视画质全无差别，前端选择器已撤（见 module-notes）。
    # 字段保留是为了换到真正支持该参数的通道后能直接复用，届时时长须重新实测。
    # 合成版本（2026-08-01）：客户在甄选页必选，三版差别在皮肤怎么处理（用光一律打好）。
    # 值域收在 pattern 里而不是自由字符串——它决定注入哪段提示词，放开等于把 prompt
    # 注入的口子留给前端。不传时后端回落默认版（老客户端/重试路径仍可用）
    prompt_variant: str | None = Field(
        None, pattern="^(real|soft|beauty)$",
        description="合成版本 real=真实 / soft=柔光 / beauty=美颜；不传回落 real",
    )
    quality: str | None = Field(
        None, pattern="^(high|medium)$",
        description="出图档位 high=精致大片 / medium=形象速览；不传则用 AI preset 配置",
    )


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


# ---------------- 门店/展位配额管理（2026-08-05）----------------


class StoreCreateRequest(BaseModel):
    name: str = Field(..., max_length=128, description="门店/展位名称")
    code: str = Field(..., max_length=64, description="门店/展位编码，全局唯一")
    contact_name: str | None = Field(None, max_length=64, description="联系人")
    contact_phone: str | None = Field(None, max_length=32, description="联系电话")
    status: int = Field(1, ge=0, le=1, description="1=启用,0=停用")


class StoreUpdateRequest(BaseModel):
    name: str | None = Field(None, max_length=128, description="门店/展位名称")
    code: str | None = Field(None, max_length=64, description="门店/展位编码，全局唯一")
    contact_name: str | None = Field(None, max_length=64, description="联系人")
    contact_phone: str | None = Field(None, max_length=32, description="联系电话")
    status: int | None = Field(None, ge=0, le=1, description="1=启用,0=停用")


class StoreUserBindRequest(BaseModel):
    user_id: int = Field(..., description="系统用户 ark_users.id")
    is_primary: bool = Field(False, description="是否主负责人")


class QuotaRechargeRequest(BaseModel):
    amount: int = Field(..., gt=0, description="充值数量，正整数")
    remark: str | None = Field(None, max_length=255, description="备注")
