"""Scheduler-owned session factory for the enabled outbound worker."""
from app.core.database import SessionLocal
from app.invoice.outbound_worker import run_once


def process_portal_outbound():
    return run_once(SessionLocal)
