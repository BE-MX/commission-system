"""备货管理 — Pydantic 请求/响应模型"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SafetyStockSaveItem(BaseModel):
    product_id: int
    safety_stock: int = Field(ge=0)
    # 乐观锁,带上当前 updated_at,服务端校验未变化才接受
    updated_at: Optional[str] = None


class SafetyStockSaveRequest(BaseModel):
    lead_time_days: int = Field(default=30, ge=1, le=365)
    safety_factor: float = Field(default=1.5, ge=0.1, le=10.0)
    items: List[SafetyStockSaveItem]


class AutoGenerateRequest(BaseModel):
    product_ids: Optional[List[int]] = None
    lead_time_days: int = Field(default=30, ge=1, le=365)
    safety_factor: float = Field(default=1.5, ge=0.1, le=10.0)
    history_days: int = Field(default=30, ge=7, le=365)


class TftPredictRequest(BaseModel):
    product_id: int
    history_days: int = Field(default=90, ge=7, le=365)
