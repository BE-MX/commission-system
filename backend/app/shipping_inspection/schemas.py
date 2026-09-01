"""发货检验 — Pydantic schemas

PC 端全是 GET，无请求体；这里只有小程序端的扫码/提交请求体
（mini/router.py 引用，与 mini/schemas.py 里的报工请求体同级别）。
"""

from pydantic import BaseModel, Field


class ShippingScanRequest(BaseModel):
    qr_raw: str = Field(..., description="出库单二维码原文")


class ShippingSubmitRequest(BaseModel):
    outbound_record_id: str = Field(..., description="OKKI 出库单 id")
    request_id: str = Field(..., description="客户端幂等键（靠状态幂等，不落库）")
    remark: str | None = Field(None, description="备注")
