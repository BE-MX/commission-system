"""Collector-only ingress and source-isolated receipt queries."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from . import service
from .auth import FeedPrincipal, require_feed_scope
from .errors import FeedError
from .http import FeedRoute
from .transport import read_json_body


def require_enabled():
    if not get_settings().ALIBABA_FEED_ENABLED:
        raise FeedError(503, "FEED_DISABLED")


# M2M exception to JWT RBAC: revocable, source-bound Integration App credentials
# recheck the owner's live permissions; invoice credentials cannot enter this API.
router = APIRouter(route_class=FeedRoute, dependencies=[Depends(require_enabled)])
_write = require_feed_scope("alibaba_feed:write")
_read = require_feed_scope("alibaba_feed:read")
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,96}$")]
BatchId = Annotated[str, Path(pattern=r"^afb_[a-f0-9]{32}$")]


@router.post("/batches", status_code=202)
async def upload_batch(request: Request, response: Response,
                       idempotency_key: Annotated[str | None, Header()] = None,
                       principal: FeedPrincipal = Depends(_write), db: Session = Depends(get_db)):
    # Release preflight locks before upload; acceptance revalidates this credential.
    await run_in_threadpool(db.rollback)
    if idempotency_key is None:
        raise FeedError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key")
    settings = get_settings()
    raw = await read_json_body(request, settings)
    receipt = await run_in_threadpool(service.accept_batch, db, principal, raw, idempotency_key, limits=settings)
    status_code = 200 if receipt["replayed"] else 202
    response.status_code = status_code
    response.headers["Location"] = receipt["status_url"]
    return ok(receipt, message="ok" if receipt["replayed"] else "accepted", code=status_code)


@router.get("/runs/{run_id}")
def get_run(run_id: RunId, principal: FeedPrincipal = Depends(_read), db: Session = Depends(get_db),
            issue_offset: int = Query(0, ge=0), issue_limit: int = Query(100, ge=1, le=100)):
    return ok(service.get_receipt(db, principal.source_account_uid, run_id=run_id,
                                 issue_offset=issue_offset, issue_limit=issue_limit))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: BatchId, principal: FeedPrincipal = Depends(_read), db: Session = Depends(get_db),
              issue_offset: int = Query(0, ge=0), issue_limit: int = Query(100, ge=1, le=100)):
    return ok(service.get_receipt(db, principal.source_account_uid, batch_id=batch_id,
                                 issue_offset=issue_offset, issue_limit=issue_limit))
