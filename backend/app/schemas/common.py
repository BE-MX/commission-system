"""统一响应格式、分页模型"""

from typing import Generic, TypeVar, Optional, List

from pydantic import BaseModel

T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    """统一API响应格式"""
    code: int = 200
    message: str = "success"
    data: Optional[T] = None


class PageResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
