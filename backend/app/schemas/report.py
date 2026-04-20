"""报表相关 Schema"""

from typing import Optional, Literal

from pydantic import BaseModel


class ReportExportParams(BaseModel):
    """报表导出参数"""
    group_by: Optional[Literal["salesperson", "supervisor", "customer"]] = None
