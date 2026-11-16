from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.domestic_followup import jobs, prep_service, strategy_service
from app.domestic_followup.prep_schemas import PrepCloneIn, PrepCreateIn, PrepFeedbackIn, PrepUpdateIn

router = APIRouter()
_require_read = require_permission("domestic_followup:read")
_require_write = require_permission("domestic_followup:write")


@contextmanager
def _errors(db):
    try:
        yield
    except prep_service.PrepConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="准备卡请求发生冲突，请刷新后重试") from exc
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _submit(fn, *args):
    jobs.submit(fn, *args)


@router.get("/customers/{customer_id}/prep-context")
def prep_context(customer_id: int, source_task_id: int | None = None,
                 db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        return ok(prep_service.context(db, user, customer_id, source_task_id))


@router.post("/preps")
def create_prep(payload: PrepCreateIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep = prep_service.create(db, user, payload)
        db.commit()
        return ok(prep_service.serialize(db, user, prep))


@router.get("/customers/{customer_id}/preps")
def prep_history(customer_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        rows = prep_service.list_preps(db, user, customer_id)
        return ok([prep_service.serialize(db, user, row) for row in rows])


@router.get("/preps/{prep_id}")
def prep_detail(prep_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        return ok(prep_service.serialize(db, user, prep_service.detail(db, user, prep_id)))


@router.put("/preps/{prep_id}")
def update_prep(prep_id: int, payload: PrepUpdateIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep = prep_service.update_prep(db, user, prep_id, payload)
        db.commit()
        return ok(prep_service.serialize(db, user, prep))


@router.post("/preps/{prep_id}/strategy")
def generate_strategy(prep_id: int, background: BackgroundTasks,
                      db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep, started = strategy_service.start(db, user, prep_id)
        db.commit()
    if started:
        background.add_task(_submit, strategy_service.run_strategy, prep_id, user, prep.version)
    return ok(prep_service.serialize(db, user, prep))


@router.get("/preps/{prep_id}/strategy")
def get_strategy(prep_id: int, db: Session = Depends(get_db), user=Depends(_require_read)):
    with _errors(db):
        return ok(prep_service.serialize(db, user, prep_service.detail(db, user, prep_id)))


@router.post("/preps/{prep_id}/feedback")
def prep_feedback(prep_id: int, payload: PrepFeedbackIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep = prep_service.feedback(db, user, prep_id, payload.feedback)
        db.commit()
        return ok(prep_service.serialize(db, user, prep), message="反馈已记录")


@router.post("/preps/{prep_id}/abandon")
def abandon_prep(prep_id: int, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep = prep_service.abandon(db, user, prep_id)
        db.commit()
        return ok(prep_service.serialize(db, user, prep), message="准备卡已作废")


@router.post("/preps/{prep_id}/clone")
def clone_prep(prep_id: int, payload: PrepCloneIn, db: Session = Depends(get_db), user=Depends(_require_write)):
    with _errors(db):
        prep = prep_service.clone(db, user, prep_id, payload)
        db.commit()
        return ok(prep_service.serialize(db, user, prep), message="已基于此卡新建")
