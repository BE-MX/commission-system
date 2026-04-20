"""员工属性相关 Schema"""

from typing import Optional, Literal
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EmployeeListItem(BaseModel):
    """员工列表项（含当前属性）"""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    full_name: Optional[str] = None
    nickname: Optional[str] = None
    current_attribute: Optional[str] = None


class EmployeeAttributeRequest(BaseModel):
    """设置/变更员工属性请求"""
    employee_id: str
    attribute_type: Literal["develop", "distribute"]


class EmployeeAttributeHistoryItem(BaseModel):
    """员工属性变更历史记录"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: str
    attribute_type: str
    effective_start: date
    effective_end: Optional[date] = None
    is_current: bool
    created_at: Optional[datetime] = None


class EmployeeAttributeResult(BaseModel):
    """设置属性操作结果"""
    employee_id: str
    attribute_type: str
    action: str


class EmployeeImportResult(BaseModel):
    """批量导入结果"""
    total_rows: int
    success: int
    failed: int
    failures: list[str] = []
