"""Authenticated battle-report endpoints."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.battle_report import query_service, service
from app.battle_report.access import bound_accounts
from app.battle_report.schemas import ReportInput, ReportUpdate, StateChange, TargetUpdate
from app.core.database import get_db
from app.core.response import ok

router = APIRouter()
_require_battle_read = require_any_permission("battle_report:read", "battle_report:admin")
_require_battle_write = require_any_permission("battle_report:write", "battle_report:admin")
_require_battle_admin = require_permission("battle_report:admin")


@router.get("")
def reports(archived: bool = False, db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(service.list_reports(db, user, archived))


@router.get("/participants")
def participants(db: Session = Depends(get_db), user=Depends(_require_battle_admin)):
    return ok({"items": bound_accounts(db)})


@router.post("")
def create(payload: ReportInput, db: Session = Depends(get_db), user=Depends(_require_battle_admin)):
    return ok(service.create_report(db, user, payload))


@router.get("/{report_id}")
def detail(report_id: int, db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(service.get_report(db, report_id, user))


@router.put("/{report_id}")
def configure(report_id: int, payload: ReportUpdate, db: Session = Depends(get_db), user=Depends(_require_battle_admin)):
    return ok(service.update_report(db, report_id, user, payload))


@router.post("/{report_id}/state")
def state(report_id: int, payload: StateChange, db: Session = Depends(get_db), user=Depends(_require_battle_admin)):
    return ok(service.change_state(db, report_id, user, payload))


@router.put("/{report_id}/targets")
def targets(report_id: int, payload: TargetUpdate, db: Session = Depends(get_db), user=Depends(_require_battle_write)):
    return ok(service.save_targets(db, report_id, user, payload))


@router.get("/{report_id}/overview")
def overview(report_id: int, team: str | None = Query(None, max_length=100),
             db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(query_service.get_overview(db, report_id, user, team))


@router.get("/{report_id}/daily")
def daily(report_id: int, start: date | None = None, team: str | None = Query(None, max_length=100),
          db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(query_service.get_daily(db, report_id, user, start, team))


@router.get("/{report_id}/orders")
def orders(report_id: int, team: str | None = Query(None, max_length=100), member_id: int | None = None,
           day: date | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
           sort: Literal["date", "amount"] = "date", keyword: str | None = Query(None, max_length=100),
           db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(query_service.list_orders(db, report_id, user, team=team, member_id=member_id, day=day,
                                       page=page, page_size=page_size, sort=sort, keyword=keyword))


@router.get("/{report_id}/orders/{order_id}")
def order(report_id: int, order_id: str, db: Session = Depends(get_db), user=Depends(_require_battle_read)):
    return ok(query_service.order_detail(db, report_id, order_id, user))


@router.get("/{report_id}/audits")
def audits(report_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
           db: Session = Depends(get_db), user=Depends(_require_battle_admin)):
    return ok(query_service.list_audits(db, report_id, user, page, page_size))
