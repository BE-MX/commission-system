"""Authenticated sales-return API; all money decisions remain in services."""
from datetime import date
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.portal.errors import PortalError
from app.sales_return import access, read_service, receiving_service, schemas, service, sources

router = APIRouter()
logger = logging.getLogger(__name__)


def execute(db, user, permission, function, *, write=False):
    try:
        current = access.authorize(db, user, permission, write=write)
        result = function(current)
        if write:
            db.flush()
            db.commit()
        return ok(result)
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, IntegrityError) as error:
        db.rollback()
        logger.warning("Sales return rejected (%s)", type(error).__name__)
        print(f"[sales-return] rejected ({type(error).__name__})", flush=True)
        raise HTTPException(409, str(error) if isinstance(error, ValueError) else
                            "提交已发生或数据冲突，请使用原提交标识核对，勿重复建单") from None
    except PortalError as error:
        db.rollback()
        logger.warning("Sales return authority unavailable (%s)", type(error).__name__)
        print("[sales-return] authority unavailable", flush=True)
        raise HTTPException(error.status, "退货授权暂不可核验，请稍后重试") from None
    except SQLAlchemyError as error:
        db.rollback()
        logger.warning("Sales return transaction unavailable (%s)", type(error).__name__)
        print(f"[sales-return] transaction unavailable ({type(error).__name__})", flush=True)
        raise HTTPException(503, "退货结果暂不能确认，请保留原提交标识并核对原单") from None


@router.get("/customers", summary="Search customers with verified outbound orders")
def customers(keyword: str = Query("", max_length=100), page: int = Query(1, ge=1),
              page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
              user=Depends(require_permission("sales_return:read"))):
    return execute(db, user, "sales_return:read", lambda current: sources.customers(db, current, keyword, page, page_size))


@router.get("/orders", summary="Search actual shipped foreign-trade orders")
def orders(customer_id: str = "", keyword: str = Query("", max_length=100), page: int = Query(1, ge=1),
           page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
           user=Depends(require_permission("sales_return:read"))):
    return execute(db, user, "sales_return:read", lambda current: sources.orders(db, current, customer_id, keyword, page, page_size))


@router.get("/orders/{order_id}/lines", summary="Verified original lines and remaining return quotas")
def lines(order_id: str, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:read"))):
    return execute(db, user, "sales_return:read", lambda current: read_service.order_lines(db, order_id, current))


@router.post("/preview", summary="Price goods credit, cash refund and outstanding waiver")
def preview(body: schemas.Draft, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:write"))):
    return execute(db, user, "sales_return:write", lambda current: service.preview(db, body, current))


@router.get("", summary="List sales returns within original order ownership")
def list_rows(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              keyword: str = Query("", max_length=100), status: str = "", return_type: str = "",
              customer_id: str = "", order_id: str = "", date_from: date | None = None, date_to: date | None = None,
              db: Session = Depends(get_db), user=Depends(require_permission("sales_return:read"))):
    return execute(db, user, "sales_return:read", lambda current: read_service.list_rows(db, current,
        page=page, page_size=page_size, keyword=keyword, status=status, return_type=return_type,
        customer_id=customer_id, order_id=order_id, date_from=date_from, date_to=date_to))


@router.post("", summary="Save a return draft with a stable submission identity")
def create(body: schemas.Create, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:write"))):
    return execute(db, user, "sales_return:write", lambda current: read_service.describe(db, service.create(db, body, current)), write=True)


@router.get("/{identity}", summary="Read a return and its local financial documents")
def detail(identity: int, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:read"))):
    return execute(db, user, "sales_return:read", lambda current: read_service.describe(db, service.get(db, identity, current)))


@router.put("/{identity}", summary="Edit the current draft version")
def update(identity: int, body: schemas.Update, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:write"))):
    return execute(db, user, "sales_return:write", lambda current: read_service.describe(db, service.update(db, identity, body, current)), write=True)


@router.delete("/{identity}", summary="Delete a draft while retaining its request and audit")
def delete(identity: int, version: int = Query(..., ge=1), db: Session = Depends(get_db),
           user=Depends(require_permission("sales_return:delete"))):
    return execute(db, user, "sales_return:delete", lambda current: read_service.describe(db, service.delete(db, identity, version, current)), write=True)


@router.post("/{identity}/activate", summary="Atomically activate goods credit and local negative receipt")
def activate(identity: int, body: schemas.Activate, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:write"))):
    return execute(db, user, "sales_return:write", lambda current: read_service.describe(db, service.activate(db, identity, body, current)), write=True)


@router.post("/{identity}/reverse", summary="Reverse an effective return with money and inventory safeguards")
def reverse(identity: int, body: schemas.Reverse, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:admin"))):
    return execute(db, user, "sales_return:admin", lambda current: read_service.describe(db, service.reverse(db, identity, body, current)), write=True)


@router.post("/{identity}/cash", summary="Record actual cash refund or recovered-cash evidence")
def cash(identity: int, body: schemas.Cash, db: Session = Depends(get_db), user=Depends(require_permission("sales_return:admin"))):
    return execute(db, user, "sales_return:admin", lambda current: read_service.describe(db, service.cash(db, identity, body, current)), write=True)


@router.post("/{identity}/receivings", summary="Record actual returned goods and inspection quantities")
def receive(identity: int, body: schemas.Receiving, db: Session = Depends(get_db), user=Depends(require_permission("sales_return_receiving:write"))):
    return execute(db, user, "sales_return_receiving:write", lambda current: read_service.describe_receiving(db, receiving_service.receive(db, identity, body, current), current), write=True)


@router.post("/{identity}/receivings/{event_id}/stock", summary="Verify the authoritative warehouse inbound result")
def stock(identity: int, event_id: int, body: schemas.Stock, db: Session = Depends(get_db),
          user=Depends(require_permission("sales_return_receiving:write"))):
    return execute(db, user, "sales_return_receiving:write", lambda current: read_service.describe_receiving(db, receiving_service.stock(db, identity, event_id, body, current), current), write=True)


@router.patch("/{identity}/receivings/{event_id}/inspection", summary="Classify pending items without counting another physical receipt")
def inspect_receiving(identity: int, event_id: int, body: schemas.Inspection, db: Session = Depends(get_db),
                      user=Depends(require_permission("sales_return_receiving:write"))):
    return execute(db, user, "sales_return_receiving:write", lambda current: read_service.describe_receiving(db,
        receiving_service.inspect_receiving(db, identity, event_id, body, current), current), write=True)
