"""A short serializable request transaction for human qualification decisions."""

import logging

from fastapi import Depends, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import get_db


logger = logging.getLogger(__name__)


def begin_qualification_transaction(db):
    # A SELECT under MySQL's default REPEATABLE READ can retain an obsolete
    # read view even after populate_existing/FOR UPDATE refreshes one row.
    # Set isolation before the first SQL; only this decision request uses it.
    if db.get_bind().dialect.name != "mysql":
        return
    if db.in_transaction():
        raise RuntimeError("QUALIFICATION_TRANSACTION_ALREADY_STARTED")
    db.connection(execution_options={"isolation_level": "SERIALIZABLE"})


def qualification_db(db: Session = Depends(get_db)):
    try:
        begin_qualification_transaction(db)
        yield db
    except OperationalError as error:
        db.rollback()
        code = error.orig.args[0] if getattr(error.orig, "args", ()) else None
        if code not in (1205, 1213):
            raise
        message = "Qualification decision lock conflict; request rolled back"
        logger.warning(message)
        print(message, flush=True)
        raise HTTPException(409, "QUALIFICATION_BUSY_RETRY") from error
