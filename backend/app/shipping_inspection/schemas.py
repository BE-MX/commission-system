"""发货检验 — Pydantic schemas

PC 撤回编辑及小程序扫码、提交的请求体。
（mini/router.py 引用，与 mini/schemas.py 里的报工请求体同级别）。
"""

from pydantic import BaseModel, Field


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
