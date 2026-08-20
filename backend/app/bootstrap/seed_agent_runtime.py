"""Idempotent immutable Agent Profile seed."""

import logging

from app.core.database import SessionLocal


logger = logging.getLogger("commission")


def seed_agent_runtime_profiles() -> None:
    try:
        from app.agent_runtime.seed import seed_default_profiles
        with SessionLocal() as db:
            created = seed_default_profiles(db)
            logger.info("Agent Runtime profiles seeded created=%s", created)
    except Exception as exc:
        logger.warning("Seed Agent Runtime profiles skipped: %s", exc)
        print(f"[bootstrap.seed_agent_runtime] skipped: {type(exc).__name__}", flush=True)
