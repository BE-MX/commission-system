"""Human JWT business routes; collector credentials never grant CRM access."""
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from .http import FeedRoute
from .business_schemas import LinkCreate
from . import business_service as service

router = APIRouter(route_class=FeedRoute)


@router.get("/records")
def records(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), linked: Literal["all", "linked", "unlinked"] = "all", keyword: str = Query("", max_length=200), db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:read"))):
    return ok(service.list_records(db, user, page=page, page_size=page_size, linked=linked, keyword=keyword))


@router.get("/records/{item_id}")
def record(item_id: int, db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:read"))):
    return ok(service.get_record(db, user, item_id))


@router.get("/customers")
def customers(keyword: str = Query("", max_length=200), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:read"))):
    return ok(service.list_customers(db, user, keyword, page, page_size))


@router.get("/customers/{company_id}/records")
def customer_records(company_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:read"))):
    return ok(service.list_records(db, user, company_id=company_id, page=page, page_size=page_size))


@router.post("/links")
def create_link(request: LinkCreate, db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:write"))):
    return ok(service.create_link(db, user, request))


@router.delete("/links/{link_id}")
def delete_link(link_id: int, expected_version: int = Query(..., gt=0), db: Session = Depends(get_db), user: dict = Depends(require_permission("client_desk:write"))):
    return ok(service.delete_link(db, user, link_id, expected_version))
