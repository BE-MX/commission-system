"""Scheduler jobs for WhatsApp Connector projection sync."""

import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.whatsapp.service import auto_sync_accounts

logger = logging.getLogger("commission.whatsapp")


async def sync_whatsapp_accounts_job() -> None:
    settings = get_settings()
    if not settings.WHATSAPP_AUTO_SYNC_ENABLED:
        return

    with SessionLocal() as db:
        stats = auto_sync_accounts(db, limit=settings.WHATSAPP_AUTO_SYNC_BATCH_SIZE)

    logger.info(
        "WhatsApp auto sync finished: accounts=%s ok=%s error=%s conversations=%s messages=%s",
        stats["accounts"],
        stats["ok"],
        stats["error"],
        stats["conversations"],
        stats["messages"],
    )
