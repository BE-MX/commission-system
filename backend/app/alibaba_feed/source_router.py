"""JWT-only source administration; collector tokens cannot manage sources."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.alibaba_feed.http import FeedRoute
from app.alibaba_feed.auth import require_current_feed_admin
from app.alibaba_feed import source_service
from app.alibaba_feed.source_service import SourceCreate, SourcePatch
from app.core.database import get_db
from app.core.response import ok

router = APIRouter(route_class=FeedRoute)
# require_current_feed_admin rechecks current JWT subject, active status and
# alibaba_feed:admin in the database; collector credentials are never accepted.


@router.post("/sources")
def create_source(request: SourceCreate, db: Session = Depends(get_db),
                  current_user: dict = Depends(require_current_feed_admin)):
    return ok(source_service.create_source(db, request))


@router.patch("/sources/{source_uid}")
def update_source(source_uid: str, request: SourcePatch, db: Session = Depends(get_db),
                  current_user: dict = Depends(require_current_feed_admin)):
    return ok(source_service.update_source(db, source_uid, request, actor_id=int(current_user["sub"])))


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), current_user: dict = Depends(require_current_feed_admin)):
    return ok(source_service.list_sources(db))


@router.get("/owners")
def list_owners(db: Session = Depends(get_db), current_user: dict = Depends(require_current_feed_admin)):
    return ok(source_service.list_owners(db))
