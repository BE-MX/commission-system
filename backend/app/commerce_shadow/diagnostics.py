"""Bounded diagnostic categories; never stringify SQL/URLs/command bodies."""
import logging

logger = logging.getLogger(__name__)


def report(code, failure):
    category = type(failure).__name__
    logger.warning("Commerce shadow %s (%s)", code, category)
    print(f"Commerce shadow {code} ({category})", flush=True)
