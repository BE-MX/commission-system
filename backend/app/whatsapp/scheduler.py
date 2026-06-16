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
        stats = auto_sync_accounts(
            db,
            conversation_limit=settings.WHATSAPP_AUTO_SYNC_BATCH_SIZE,
            message_limit_per_chat=settings.WHATSAPP_SYNC_MESSAGES_PER_CHAT,
        )

    logger.info(
        "WhatsApp auto sync finished: accounts=%s ok=%s error=%s conversations=%s message_conversations=%s message_errors=%s messages=%s",
        stats["accounts"],
        stats["ok"],
        stats["error"],
        stats["conversations"],
        stats["message_conversations"],
        stats["message_errors"],
        stats["messages"],
    )
