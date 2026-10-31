"""色板库（公库 / 私库）+ 色差仪测量 API。

权限码:
- color_library:read  — 查看公库；查看自己有归属的客户私库
- color_library:write — 私库新建色板、录入/剔除测量、申请纳入公库
- color_library:admin — 维护公库、审核晋升
私库额外受客户实时归属约束（见 swatch_library_service 文件头）。
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth.dependencies import require_any_permission, require_permission
from app.color import swatch_library_service as svc
from app.color.swatch_library_schemas import (
    InclusionUpdate,
    LibrarySwatchCreate,
    LibrarySwatchUpdate,
    MeasurementBatch,
    PromotionReview,
)
from app.core.response import ok

router = APIRouter()

_READ_CODES = (svc.PERM_READ, svc.PERM_WRITE, svc.PERM_ADMIN)
_WRITE_CODES = (svc.PERM_WRITE, svc.PERM_ADMIN)


@router.get("/customers")
def my_customers(keyword: Optional[str] = Query(None, max_length=100),
                 db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_READ_CODES))):
    return ok(svc.list_my_customers(db, user, keyword))


@router.get("/swatches")
def list_swatches(
    scope: Literal["public", "private"] = Query("private"),
    customer_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None, max_length=50),
    verdict: Optional[Literal["ok", "warn", "none"]] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: dict = Depends(require_any_permission(*_READ_CODES)),
):
    return ok(svc.list_swatches(db, user, scope=scope, customer_id=customer_id, keyword=keyword,
                                verdict=verdict, page=page, page_size=page_size))


@router.post("/swatches")
def create_swatch(body: LibrarySwatchCreate, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.create_swatch(db, user, body.model_dump()))


@router.get("/swatches/{swatch_id}")
def get_swatch(swatch_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_READ_CODES))):
    return ok(svc.get_swatch(db, user, swatch_id))


@router.patch("/swatches/{swatch_id}")
def update_swatch(swatch_id: int, body: LibrarySwatchUpdate,
                  db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.update_swatch(db, user, swatch_id, body.model_dump(exclude_unset=True)))


@router.delete("/swatches/{swatch_id}")
def archive_swatch(swatch_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.archive_swatch(db, user, swatch_id))


@router.post("/swatches/{swatch_id}/measurements")
def add_measurements(swatch_id: int, body: MeasurementBatch,
                     db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.add_measurements(db, user, swatch_id, [i.model_dump() for i in body.items]))


@router.patch("/swatches/{swatch_id}/measurements/{measurement_id}")
def set_inclusion(swatch_id: int, measurement_id: int, body: InclusionUpdate,
                  db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.set_inclusion(db, user, swatch_id, measurement_id, body.is_included, body.reason))


@router.post("/swatches/{swatch_id}/promote")
def request_promotion(swatch_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_WRITE_CODES))):
    return ok(svc.request_promotion(db, user, swatch_id))


@router.get("/promotions")
def list_promotions(db: Session = Depends(get_db),
                    user: dict = Depends(require_permission(svc.PERM_ADMIN))):
    return ok(svc.list_promotions(db, user))


@router.post("/swatches/{swatch_id}/promotion-review")
def review_promotion(swatch_id: int, body: PromotionReview, db: Session = Depends(get_db),
                     user: dict = Depends(require_permission(svc.PERM_ADMIN))):
    return ok(svc.review_promotion(db, user, swatch_id, body.approve))
