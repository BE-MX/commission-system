"""Single active scheduler entry for pending saved employee sync intents."""
from app.core.database import SessionLocal
from app.invoice.linked_sync_worker import run_once


def process_pending_invoice_syncs():
    return run_once(SessionLocal)
