"""内贸订单 — Pydantic schemas"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── 客户 ──────────────────────────────────────────────


class CustomerCreate(BaseModel):
    shop_name: str = Field(..., min_length=1, max_length=120, description="客户店名")
    contact: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=255)
    remark: str | None = Field(None, max_length=500)

    @field_validator("shop_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("客户店名不能为空")
        return v


class CustomerUpdate(BaseModel):
    shop_name: str | None = Field(None, min_length=1, max_length=120)
    contact: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=255)
    remark: str | None = Field(None, max_length=500)
    status: int | None = Field(None, ge=0, le=1)


# ── 产品属性 ──────────────────────────────────────────


class ProductAttrs(BaseModel):
    """产品属性组合 —— 这组值唯一决定一个内贸产品"""

    product_type: Literal["cap", "piece"] = Field(..., description="cap=头套,piece=发片")
    craft: str = Field(..., min_length=1, max_length=64, description="工艺")
    net_color: str | None = Field(None, max_length=64, description="网底颜色（仅头套）")
    size: str = Field(..., min_length=1, max_length=64, description="尺寸")
    length: str = Field(..., min_length=1, max_length=32, description="长度")
    density: str = Field(..., min_length=1, max_length=32, description="发量")

    @field_validator("craft", "net_color", "size", "length", "density")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _net_color_only_for_cap(self):
        # 发片没有网底，带值会污染 attrs_key 让同一产品分裂成两个
        if self.product_type == "piece" and self.net_color:
            self.net_color = None
        return self


class CraftRouteUpsert(BaseModel):
    product_type: Literal["cap", "piece"]
    craft: str = Field(..., min_length=1, max_length=64)
    route_id: int = Field(..., gt=0)


class ProductRouteRebind(BaseModel):
    route_id: int | None = Field(None, description="null = 解绑")


# ── 订单 ──────────────────────────────────────────────

_IMG_FIELD = Field(default_factory=list, description="图片相对路径列表")


class OrderItemInput(BaseModel):
    attrs: ProductAttrs
    order_qty: int = Field(..., gt=0, le=100000, description="下单数量")
    hairstyle: str | None = Field(None, max_length=1000)
    hairstyle_images: list[str] = _IMG_FIELD
    color: str | None = Field(None, max_length=1000)
    color_images: list[str] = _IMG_FIELD
    style_requirement: str | None = Field(None, max_length=2000)
    style_images: list[str] = _IMG_FIELD
    remark: str | None = Field(None, max_length=2000)
    remark_images: list[str] = _IMG_FIELD


class OrderCreate(BaseModel):
    order_no: str = Field(..., min_length=1, max_length=64, description="客户订单号")
    order_date: date
    customer_id: int | None = Field(None, description="已有客户 ID")
    customer_shop_name: str | None = Field(None, max_length=120, description="就地新建客户的店名")
    order_type: Literal["normal", "special"] = "normal"
    remark: str | None = Field(None, max_length=1000)
    items: list[OrderItemInput] = Field(..., min_length=1)

    @field_validator("order_no")
    @classmethod
    def _strip_no(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("订单号不能为空")
        return v

    @model_validator(mode="after")
    def _need_customer(self):
        if not self.customer_id and not (self.customer_shop_name or "").strip():
            raise ValueError("请选择客户或填写客户店名")
        return self


class OrderUpdate(BaseModel):
    """订单头编辑。明细的增删改走各自端点，避免整单覆盖冲掉在制进度。"""

    order_no: str | None = Field(None, min_length=1, max_length=64)
    order_date: date | None = None
    customer_id: int | None = None
    order_type: Literal["normal", "special"] | None = None
    remark: str | None = Field(None, max_length=1000)


class OrderItemUpdate(BaseModel):
    """明细编辑。order_qty 已开始报工后不允许改小到低于已完成数（service 校验）。"""

    order_qty: int | None = Field(None, gt=0, le=100000)
    hairstyle: str | None = Field(None, max_length=1000)
    hairstyle_images: list[str] | None = None
    color: str | None = Field(None, max_length=1000)
    color_images: list[str] | None = None
    style_requirement: str | None = Field(None, max_length=2000)
    style_images: list[str] | None = None
    remark: str | None = Field(None, max_length=2000)
    remark_images: list[str] | None = None


class ItemShipRequest(BaseModel):
    ship_time: datetime = Field(..., description="发货时间")
    ship_weight: Decimal = Field(..., gt=0, le=100000, description="发货克重 g")


class OrderStatusUpdate(BaseModel):
    status: Literal[4] = Field(..., description="目前仅支持置为 4=已终止；完工/发货由业务动作驱动")
    reason: str | None = Field(None, max_length=500)


# ── 报工 ──────────────────────────────────────────────


class ReportSubmit(BaseModel):
    item_id: int = Field(..., gt=0)
    progress_id: int = Field(..., gt=0, description="要报的工序进度行，扫码接口回传")
    qty: int = Field(..., gt=0, description="本次报工数量")


class ReportRevoke(BaseModel):
    log_id: int = Field(..., gt=0, description="要撤销的报工流水 ID")
