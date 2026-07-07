"""公开库存查询路由（/api/public/stock）。

无 JWT 鉴权（宪法 3 白名单场景，已登记 scripts/check_conventions.py AUTH_EXEMPT_FILES）：
消费方是客户官网嵌入页与客户外部系统（Shopify 等），无法持有方舟登录态。
门禁走 `key` 参数（Settings.PUBLIC_STOCK_KEYS，逗号分隔可多客户发放、可单独吊销；
未配置任何 key 时端点整体关闭）。只读、只出产品标识与可用量，无经营数据。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.stock import public_service

router = APIRouter()


def _require_key(key: str | None) -> None:
    if not public_service.is_valid_key(key):
        raise HTTPException(403, "Invalid or missing access key")


@router.get("/products", summary="公开库存查询（key 门禁；客户嵌入页与客户系统 API 共用）")
def list_public_products(
    key: str = Query(..., max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None, max_length=200, description="搜索产品名/型号"),
    db: Session = Depends(get_db),
):
    _require_key(key)
    result = public_service.query_public_inventory(
        db, page=page, page_size=page_size, keyword=keyword,
    )
    return ok({
        "total": result["total"],
        "page": page,
        "page_size": page_size,
        "items": result["items"],
    })
