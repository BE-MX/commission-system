"""发货检验 — Pydantic schemas

PC 撤回编辑及小程序扫码、提交的请求体。
（mini/router.py 引用，与 mini/schemas.py 里的报工请求体同级别）。
"""

from pydantic import BaseModel, Field
from typing import Literal

from app.tracking.schemas import WaybillCreate


class ShippingScanRequest(BaseModel):
    qr_raw: str = Field(..., description="出库单二维码原文")
    request_id: str | None = Field(None, min_length=1, max_length=64)


class ShippingSubmitRequest(BaseModel):
    outbound_record_id: str = Field(..., description="OKKI 出库单 id")
    request_id: str = Field(..., description="客户端幂等键（靠状态幂等，不落库）")
    edit_version: int = Field(0, ge=0, description="扫码获得的编辑版本，撤回后旧版本禁止提交")
    remark: str | None = Field(None, max_length=500, description="备注")


class ShippingRecallRequest(BaseModel):
    edit_version: int = Field(..., ge=0, description="列表中的编辑版本，防止延迟请求撤回新提交")


class MobileShipmentEvidence(BaseModel):
    source: Literal['pc', 'mobile'] = 'pc'
    photo_token: str | None = Field(None, max_length=128)
    number_source: Literal['barcode', 'ocr', 'manual'] = 'manual'
    preview_token: str | None = Field(None, max_length=4096)
    confirmed_warnings: list[str] = Field(default_factory=list, max_length=10)


class InspectionShipmentInput(MobileShipmentEvidence):
    """关联物流跟踪里已有的运单（运单号+承运商精确匹配；PC 录入的承运商可能是"未知"）。"""
    shipment_version: int = Field(..., ge=0)
    edit_version: int = Field(..., ge=0)
    waybill_no: str = Field(..., min_length=1, max_length=50, pattern=r'^\S+$')
    carrier: str = Field(..., min_length=1, max_length=30, pattern=r'^\S+$')
    recipient_country: str = Field('', max_length=100)
    recipient_name: str = Field('', max_length=100)


class InspectionShipmentCreate(WaybillCreate, MobileShipmentEvidence):
    """验货单弹框上传运单：先按物流跟踪原流程入库，再关联本验货单。"""
    shipment_version: int = Field(..., ge=0)
    edit_version: int = Field(..., ge=0)


class InspectionShipmentPreview(BaseModel):
    photo_token: str = Field(..., min_length=1, max_length=128)
    waybill_no: str = Field(..., min_length=1, max_length=50, pattern=r'^\S+$')
    carrier: str = Field(..., min_length=1, max_length=30, pattern=r'^\S+$')
    recipient_country: str = Field(..., min_length=1, max_length=100)
    recipient_name: str = Field('', max_length=100)
    edit_version: int = Field(..., ge=0)
    shipment_version: int = Field(..., ge=0)
