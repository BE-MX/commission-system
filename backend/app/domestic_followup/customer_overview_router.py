"""Customer overview, profile completion, and audited deal verification API."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import customer_overview, customer_overview_contacts
from app.domestic_followup.collaboration_access import COORDINATE, READ, WRITE

router = APIRouter()
_require_read = require_permission(READ)
_require_write = require_permission(READ, WRITE)
_require_coordinate = require_permission(READ, COORDINATE)
Scope = Literal["mine", "authorized", "collaborating", "available", "incoming"]
DealStatus = Literal["all", "won", "unwon", "unknown", "sample_only"]
CollaborationStatus = Literal["unassigned", "following", "handoff", "open", "stopped"]


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, max_length=40)
    wechat: str | None = Field(None, max_length=120)
    province: str | None = Field(None, max_length=64)
    city: str | None = Field(None, max_length=64)
    duplicate_confirmed: bool = False


class DealVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deal_status: Literal["won", "unwon", "unknown"]
    evidence: str = Field(min_length=1, max_length=500)


@router.get("/customer-overview")
def list_overview(
    db: Session = Depends(get_db), user: dict = Depends(_require_read),
    keyword: str = Query("", max_length=120), province: str | None = Query(None, max_length=64),
    city: str | None = Query(None, max_length=64), deal_status: DealStatus = "all", scope: Scope | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    sort_field: Literal["last_followup_date", "next_date", "shop_name"] = "last_followup_date",
    sort_order: Literal["asc", "desc"] = "desc",
    assignee_user_id: int | None = Query(None, ge=1), collaboration_status: CollaborationStatus | None = None,
    date_from: date | None = None, date_to: date | None = None, never_contacted: bool = False,
    overdue: bool = False, lifecycle_status: str | None = Query(None, max_length=16),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "最近联系起始日期不能晚于结束日期")
    return ok(customer_overview.list_customer_overview(
        db, user, keyword=keyword, province=province, city=city, deal_status=deal_status, scope=scope,
        page=page, page_size=page_size, sort_field=sort_field, sort_order=sort_order, assignee_user_id=assignee_user_id,
        collaboration_status=collaboration_status, date_from=date_from, date_to=date_to, never_contacted=never_contacted,
        overdue=overdue, lifecycle_status=lifecycle_status,
    ))


@router.put("/customers/{customer_id}/contact")
def edit_contact(customer_id: int, payload: ContactUpdate, db: Session = Depends(get_db),
                 user: dict = Depends(_require_write)):
    try:
        changes = payload.model_dump(exclude_unset=True, exclude={"duplicate_confirmed"})
        result = customer_overview_contacts.update_contact(db, user, customer_id, changes, payload.duplicate_confirmed)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    if not result["updated"]:
        raise HTTPException(409, {"message": "可能已有档案，请核实后重试", **result})
    return ok(result)


@router.get("/customers/{customer_id}/overview")
def get_overview(customer_id: int, db: Session = Depends(get_db), user: dict = Depends(_require_read)):
    row = customer_overview.get_customer_overview(db, user, customer_id)
    if row is None:
        raise HTTPException(404, "客户不存在")
    return ok(row)


@router.put("/customers/{customer_id}/deal-verification")
def deal_verification(
    customer_id: int, payload: DealVerification, db: Session = Depends(get_db), user: dict = Depends(_require_coordinate),
):
    try:
        return ok(customer_overview_contacts.verify_deal(db, user, customer_id, payload.deal_status, payload.evidence))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
