"""Machine-only routes. require_mail_worker authenticates a dedicated bound token."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.mail_outreach import event_service, worker_service
from app.mail_outreach.models import MailMailboxBinding
from app.mail_outreach.worker_auth import require_mail_worker
from app.mail_outreach.worker_schemas import EventsRequest, FenceRequest, HeartbeatRequest, ResultRequest

router = APIRouter(prefix="/worker")


@router.get("/bindings")
def bindings(db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    rows = db.query(MailMailboxBinding).filter_by(worker_identity=identity, status="active").all()
    return ok([{"id": x.id, "sender_email": x.sender_email, "cli_workspace": x.cli_workspace} for x in rows])


@router.post("/{mailbox_id}/heartbeat")
def heartbeat(mailbox_id: int, payload: HeartbeatRequest, db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    return ok(worker_service.heartbeat(db, identity, mailbox_id, payload))


@router.post("/{mailbox_id}/claim")
def claim(mailbox_id: int, db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    return ok(worker_service.claim(db, identity, mailbox_id))


@router.post("/jobs/{job_id}/authorize")
def authorize(job_id: int, payload: FenceRequest, db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    return ok(worker_service.authorize(db, identity, job_id, payload.fencing_token))


@router.post("/jobs/{job_id}/result")
def result(job_id: int, payload: ResultRequest, db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    return ok(worker_service.record_result(db, identity, job_id, payload))


@router.post("/{mailbox_id}/events")
def events(mailbox_id: int, payload: EventsRequest, db: Session = Depends(get_db), identity=Depends(require_mail_worker)):
    return ok(event_service.ingest(db, identity, mailbox_id, payload))
