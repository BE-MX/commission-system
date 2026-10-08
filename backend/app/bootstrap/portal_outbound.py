"""Confirm durable outbound ownership before schedulers or application readiness."""
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.invoice.outbound_mode import initialize

logger = logging.getLogger(__name__)


def initialize_portal_outbound():
    try:
        return initialize(SessionLocal, portal_enabled=get_settings().PORTAL_ENABLED)
    except Exception as error:
        logger.warning('Outbound bootstrap unavailable (%s)', type(error).__name__)
        print('[outbound-mode] bootstrap unavailable; writers remain paused', flush=True)
        raise RuntimeError('Outbound bootstrap is unavailable; writers remain paused') from None
