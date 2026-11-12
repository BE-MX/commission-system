"""Private-sea customer API; source authorization is repeated in services."""

from datetime import date as Date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.client_desk import schemas, service, link_service, timeline
from app.client_desk.access import require_enabled
from app.client_desk.read_scope import scope_request

router = APIRouter(tags=["client-desk"])


@router.get("/today")
def get_today(
    reason: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(service.today(db, user, reason))


@router.get("/customers")
def get_customers(
    filter: str = "all",
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    reason: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(service.customer_list(db, user, filter, keyword, page, page_size, reason))


@router.get("/board")
def get_board(
    keyword: str = Query("", max_length=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(service.board(db, user, keyword))


@router.put("/customers/{company_id}/tags")
def put_tag(
    company_id: int,
    payload: schemas.TagPut,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.set_tag(db, user, company_id, payload))


@router.get("/calendar/sample-followup")
def sample_date(
    date: Date,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    require_enabled(db, user)
    from app.client_desk.calendar import offset_workdays
    from app.core.config import get_settings

    return ok({"date": offset_workdays(date, 10, get_settings().CLIENT_DESK_CALENDAR)})


@router.get("/customers/{company_id}")
def get_customer(
    company_id: int,
    fresh: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    load = service.fresh_detail if fresh else service.detail
    return ok(load(db, user, company_id))


@router.get("/customers/{company_id}/timeline")
def get_timeline(
    company_id: int,
    source: str = "all",
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(timeline.timeline(db, user, company_id, source, cursor, limit))


@router.get("/customers/{company_id}/timeline/events/{event_key:path}")
def get_event(
    company_id: int,
    event_key: str,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(timeline.event(db, user, company_id, event_key))


@router.patch("/customers/{company_id}/state")
def patch_state(
    company_id: int,
    payload: schemas.StatePatch,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.patch_state(db, user, company_id, payload))


@router.put("/customers/{company_id}/grade")
def put_grade(
    company_id: int,
    payload: schemas.GradePut,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.put_grade(db, user, company_id, payload))


@router.post("/customers/{company_id}/followups")
def add_followup(
    company_id: int,
    payload: schemas.FollowupPost,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.add_followup(db, user, company_id, payload))


@router.post("/customers/{company_id}/reanalyze", status_code=202)
@scope_request()
def reanalyze(
    company_id: int,
    payload: schemas.ReanalyzePost,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    service.scoped(db, user, company_id, True)
    from app.client_desk.queue import enqueue_manual

    result = enqueue_manual(
        db, user, company_id, payload.client_request_id, payload.feed_item_ids
    )
    db.commit()
    return ok(result)


@router.post("/suggestions/{suggestion_id}/feedback")
def feedback(
    suggestion_id: int,
    payload: schemas.FeedbackPost,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.feedback(db, user, suggestion_id, payload))


@router.get("/unlinked-conversations")
def unlinked(
    keyword: str = "",
    scope: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(link_service.conversations(db, user, keyword, page, page_size, scope))


@router.post("/wa-links")
def save_link(
    payload: schemas.LinkPost,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(link_service.save_link(db, user, payload))


@router.delete("/wa-links/{link_id}")
def delete_link(
    link_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(link_service.delete_link(db, user, link_id))


@router.post("/customers/{company_id}/wa-open")
def wa_open(
    company_id: int,
    payload: schemas.WaOpenPost,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(service.wa_open(db, user, company_id, payload))
