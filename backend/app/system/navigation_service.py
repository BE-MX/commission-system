"""Read/write the authenticated user's navigation row, with insert-race recovery."""
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.system.models import NavigationPreference
from app.system.navigation_schemas import NavigationPrefs
from app.system.navigation_access import validate_additions

logger = logging.getLogger("commission")


def get_preferences(db: Session, user_id: int) -> dict:
    row = db.get(NavigationPreference, user_id)
    return {"items": list(row.items) if row else []}


def save_preferences(db: Session, user_id: int, payload: NavigationPrefs) -> dict:
    row = db.get(NavigationPreference, user_id)
    validate_additions(db, user_id, list(row.items) if row else [], payload.items)
    try:
        if row is None:
            db.add(NavigationPreference(user_id=user_id, items=payload.items))
        else:
            row.items = payload.items
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.warning("navigation preferences insert race for user %s", user_id)
        print(f"[navigation] preferences insert race user={user_id}", flush=True)
        try:
            row = db.get(NavigationPreference, user_id)
            if row is None:
                raise
            row.items = payload.items
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("navigation preferences race recovery failed for user %s", user_id)
            print(f"[navigation] preferences race recovery failed user={user_id}", flush=True)
            raise
    except Exception:
        db.rollback()
        logger.exception("navigation preferences save failed for user %s", user_id)
        print(f"[navigation] preferences save failed user={user_id}", flush=True)
        raise
    return payload.model_dump()
