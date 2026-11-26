"""B-track HTTP API, mounted at /api/client-desk/unlinked."""

from datetime import date as Date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok

from . import service

router = APIRouter(tags=["client-desk-unlinked"])


class ProspectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    next_followup_date: Date | None = None
    next_followup_remark: str | None = Field(default=None, max_length=500)


class BindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: str = Field(pattern=r"^[0-9]{1,20}$")


@router.get("/threads")
def list_threads(
    view: str = Query("active", pattern="^(active|prospect)$"),
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:read")),
):
    return ok(service.list_threads(db, user, view))


@router.post("/threads/{thread_id}/handled")
def handled(thread_id: int, db: Session = Depends(get_db), user=Depends(require_permission("client_desk:write"))):
    return ok(service.handled(db, user, thread_id))


@router.post("/threads/{thread_id}/ignore")
def ignore(thread_id: int, db: Session = Depends(get_db), user=Depends(require_permission("client_desk:write"))):
    return ok(service.ignore(db, user, thread_id))


@router.post("/threads/{thread_id}/restore")
def restore(thread_id: int, db: Session = Depends(get_db), user=Depends(require_permission("client_desk:write"))):
    return ok(service.restore(db, user, thread_id))


@router.post("/threads/{thread_id}/prospect")
def prospect(
    thread_id: int,
    body: ProspectBody,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.set_prospect(db, user, thread_id, body.next_followup_date, body.next_followup_remark))


@router.post("/threads/{thread_id}/bind")
def bind(
    thread_id: int,
    body: BindBody,
    db: Session = Depends(get_db),
    user=Depends(require_permission("client_desk:write")),
):
    return ok(service.bind(db, user, thread_id, body.company_id))


@router.post("/threads/{thread_id}/analyze")
def analyze(thread_id: int, db: Session = Depends(get_db), user=Depends(require_permission("client_desk:write"))):
    return ok(service.request_analysis(db, user, thread_id))


@router.get("/weekly-reviews")
def weekly_reviews(db: Session = Depends(get_db), user=Depends(require_permission("client_desk:read"))):
    return ok(service.list_reviews(db, user))


@router.post("/weekly-reviews/generate")
def generate(db: Session = Depends(get_db), user=Depends(require_permission("client_desk:write"))):
    return ok(service.generate_review(db, user))
