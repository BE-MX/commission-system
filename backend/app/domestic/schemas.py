"""内贸订单 — Pydantic schemas"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── 客户 ──────────────────────────────────────────────


class CustomerCreate(BaseModel):
    shop_name: str = Field(..., min_length=1, max_length=120, description="客户店名")
    custom_code: str | None = Field(None, max_length=64, description="客户自定义编码")
    membership_level: str | None = Field(None, max_length=32, description="会员等级")
    province: str | None = Field(None, max_length=64)
    city: str | None = Field(None, max_length=64)
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

    @field_validator("custom_code", "membership_level", "province", "city", "contact", "phone", "address", "remark")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        value = v.strip() if isinstance(v, str) else v
        return value or None


class CustomerUpdate(BaseModel):
    shop_name: str | None = Field(None, min_length=1, max_length=120)
    custom_code: str | None = Field(None, max_length=64)
    membership_level: str | None = Field(None, max_length=32)
    province: str | None = Field(None, max_length=64)
    city: str | None = Field(None, max_length=64)
    contact: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, max_length=40)
    address: str | None = Field(None, max_length=255)
    remark: str | None = Field(None, max_length=500)
    status: int | None = Field(None, ge=0, le=1)

    @field_validator("custom_code", "membership_level", "province", "city", "contact", "phone", "address", "remark")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        value = v.strip() if isinstance(v, str) else v
        return value or None


class CustomerRechargeCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, le=999999999999, max_digits=14, decimal_places=2)
    remark: str | None = Field(None, max_length=500)
    request_id: str | None = Field(None, max_length=64, description="客户端幂等键")


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
    order_qty: int = Field(..., gt=0, le=2000, description="下单数量（逐件码物化，单明细最多2000件）")
    unit_price: Decimal = Field(
        Decimal("0.00"), ge=0, le=999999999999,
        max_digits=14, decimal_places=2, description="产品单价",
    )
    hairstyle: str | None = Field(None, max_length=1000)
    hairstyle_images: list[str] = _IMG_FIELD
    color: str | None = Field(None, max_length=1000)
    color_images: list[str] = _IMG_FIELD
    style_requirement: str | None = Field(None, max_length=2000)
    style_images: list[str] = _IMG_FIELD
    remark: str | None = Field(None, max_length=2000)
    remark_images: list[str] = _IMG_FIELD


class OrderItemAppend(OrderItemInput):
    request_id: str = Field(..., min_length=8, max_length=64, description="客户端追加明细幂等键")

    @field_validator("request_id", mode="before")
    @classmethod
    def _strip_request_id(cls, v: str) -> str:
        return v.strip()


class OrderCreate(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64, description="客户端建单幂等键")
    order_no: str = Field(..., min_length=1, max_length=64, description="客户订单号")
    order_date: date
    customer_id: int | None = Field(None, description="已有客户 ID")
    customer_shop_name: str | None = Field(None, max_length=120, description="就地新建客户的店名")
    order_type: Literal["normal", "special"] = "normal"
    is_draft: bool = Field(False, description="true=只存草稿，不扣客户余额")
    remark: str | None = Field(None, max_length=1000)
    items: list[OrderItemInput] = Field(..., min_length=1, max_length=50)

    @field_validator("order_no")
    @classmethod
    def _strip_no(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("订单号不能为空")
        return v

    @field_validator("request_id", mode="before")
    @classmethod
    def _strip_request_id(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _need_customer(self):
        if not self.customer_id and not (self.customer_shop_name or "").strip():
            raise ValueError("请选择客户或填写客户店名")
        if sum(item.order_qty for item in self.items) > 5000:
            raise ValueError("单张订单合计数量不能超过 5000 件")
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

    order_qty: int | None = Field(None, gt=0, le=2000)
    unit_price: Decimal | None = Field(
        None, ge=0, le=999999999999, max_digits=14, decimal_places=2,
    )
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
    request_id: str | None = Field(None, max_length=64, description="幂等键，重试用同一个值")
    on_behalf_user_id: int | None = Field(
        None, gt=0, description="代报工：实际做活的工人，件数记他名下（计件口径）",
    )


class ReportRevoke(BaseModel):
    log_id: int = Field(..., gt=0, description="要撤销的报工流水 ID")
