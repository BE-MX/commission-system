"""产品风向标 API（P0：历史品名映射管理与月度可信度，仅 admin）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.core.time import beijing_today
from app.product_sales import service
from app.product_sales.models import MAPPING_STATUSES
from app.product_sales.schemas import MappingSaveRequest

router = APIRouter()
ADMIN_PERMISSION = "product_sales:admin"


def _user_id(user: dict) -> int:
    try:
        value = int(user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误") from None
    if value <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token格式错误")
    return value


@router.get("/mappings")
def list_mappings(
    status_filter: str | None = Query(None, alias="status"),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=Depends(require_permission(ADMIN_PERMISSION)),
):
    if status_filter and status_filter not in MAPPING_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "状态无效")
    return ok(service.list_mappings(db, status_filter, keyword, page, page_size))


@router.post("/mappings/refresh")
def refresh_mappings(
    db: Session = Depends(get_db),
    _user=Depends(require_permission(ADMIN_PERMISSION)),
):
    return ok(service.refresh_mappings(db))


@router.put("/mappings")
def save_mappings(
    payload: MappingSaveRequest,
    db: Session = Depends(get_db),
    user=Depends(require_permission(ADMIN_PERMISSION)),
):
    items = [item.model_dump() for item in payload.items]
    return ok(service.save_mappings(db, _user_id(user), items))


@router.get("/models")
def current_models(
    db: Session = Depends(get_db),
    _user=Depends(require_permission(ADMIN_PERMISSION)),
):
    return ok(service.current_models(db))


@router.get("/coverage")
def coverage(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    _user=Depends(require_permission(ADMIN_PERMISSION)),
):
    end = date_to or beijing_today()
    start = date_from or service.HISTORY_START
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "开始日期不能晚于结束日期")
    return ok(service.coverage(db, start, end))
