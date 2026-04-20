"""客户归属相关 Schema"""

from typing import Optional, Literal
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CustomerSnapshotListItem(BaseModel):
    """客户归属快照列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: str
    customer_name: Optional[str] = None
    salesperson_id: str
    salesperson_name: Optional[str] = None
    salesperson_attribute: Optional[str] = None
    salesperson_rate: Optional[float] = None
    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    supervisor_attribute: Optional[str] = None
    supervisor_rate: Optional[float] = None
    is_complete: bool
    source: Optional[str] = None
    first_order_id: Optional[str] = None
    first_order_date: Optional[date] = None


class CustomerSnapshotCreateRequest(BaseModel):
    """手工新增客户归属请求"""
    customer_id: str
    salesperson_id: str
    salesperson_attribute: Literal["develop", "distribute"]
    supervisor_id: Optional[str] = None
    supervisor_attribute: Optional[Literal["develop", "distribute"]] = None


class CustomerSnapshotCompleteRequest(BaseModel):
    """补全不完整快照请求"""
    salesperson_attribute: Literal["develop", "distribute"]
    supervisor_attribute: Optional[Literal["develop", "distribute"]] = None


class CustomerSnapshotResetRequest(BaseModel):
    """人工重置客户归属请求"""
    salesperson_id: str
    salesperson_attribute: Literal["develop", "distribute"]
    supervisor_id: Optional[str] = None
    supervisor_attribute: Optional[Literal["develop", "distribute"]] = None
    reset_reason: str


class CustomerImportResult(BaseModel):
    """批量导入结果"""
    total_rows: int
    success: int
    failed: int
    failures: list[str] = []
