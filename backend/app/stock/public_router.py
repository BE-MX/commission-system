"""公开库存查询路由（/api/public/stock）。

无 JWT 鉴权、无 key 门禁（宪法 3 白名单场景，已登记 scripts/check_conventions.py
AUTH_EXEMPT_FILES）：消费方是 leshine.work/inventory 客户公开查询页与客户外部系统
（Shopify 等），无法持有方舟登录态。只读、只出产品四要素与有货标识，无经营数据。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.stock import public_service

router = APIRouter()


@router.get("/products", summary="公开库存查询（无门禁；客户公开页与客户系统 API 共用）")
def list_public_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=200, description="搜索产品名/型号"),
    in_stock_only: bool = Query(False, description="只显示有库存的产品"),
    db: Session = Depends(get_db),
):
    result = public_service.query_public_inventory(
        db, page=page, page_size=page_size, keyword=keyword, in_stock_only=in_stock_only,
    )
    return ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"],
    })
