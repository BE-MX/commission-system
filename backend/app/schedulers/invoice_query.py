"""Scheduler-owned session boundary for bounded original-order GET recovery."""
from app.core.database import SessionLocal
from app.invoice.order_query_recovery import run_once


def recover_uncertain_orders():
    return run_once(SessionLocal)
