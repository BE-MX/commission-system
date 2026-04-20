"""主管关系相关 Schema"""

from typing import Optional
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class SupervisorRelationListItem(BaseModel):
    """主管关系列表项"""
    model_config = ConfigDict(from_attributes=True)

    salesperson_id: str
    salesperson_name: Optional[str] = None
    supervisor_id: str
    supervisor_name: Optional[str] = None
    effective_start: date


class SupervisorRelationRequest(BaseModel):
    """设置/变更主管关系请求"""
    salesperson_id: str
    supervisor_id: str


class SupervisorHistoryItem(BaseModel):
    """主管关系变更历史记录"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    salesperson_id: str
    supervisor_id: str
    effective_start: date
    effective_end: Optional[date] = None
    is_current: bool
    created_at: Optional[datetime] = None


class SupervisorRelationResult(BaseModel):
    """设置关系操作结果"""
    salesperson_id: str
    supervisor_id: str
    action: str


class SupervisorImportResult(BaseModel):
    """批量导入结果"""
    total_rows: int
    success: int
    failed: int
    failures: list[str] = []
