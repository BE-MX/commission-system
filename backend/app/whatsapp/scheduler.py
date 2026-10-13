"""Scheduler jobs for WhatsApp Connector projection sync."""

import logging
import asyncio

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.whatsapp.service import auto_sync_accounts

logger = logging.getLogger("commission.whatsapp")


def _sync_accounts(provider: str) -> None:
    settings = get_settings()
    if not settings.WHATSAPP_AUTO_SYNC_ENABLED:
        return

    with SessionLocal() as db:
        stats = auto_sync_accounts(
            db,
            conversation_limit=settings.WHATSAPP_AUTO_SYNC_BATCH_SIZE,
            message_limit_per_chat=settings.WHATSAPP_EVENT_SYNC_BATCH_SIZE if provider == 'baileys' else settings.WHATSAPP_SYNC_MESSAGES_PER_CHAT,
            provider=provider,
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


async def sync_whatsapp_accounts_job() -> None:
    await asyncio.to_thread(_sync_accounts, 'whatsapp-web.js')


async def sync_whatsapp_events_job() -> None:
    # HTTP + SQL are synchronous: isolate them from the API event loop.
    await asyncio.to_thread(_sync_accounts, 'baileys')
