"""Internal media endpoints use live role grants, including data scopes."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import dependencies
from app.auth.service import get_live_user_authorization
from app.core.database import get_db


def live_actor(
    payload: dict = Depends(dependencies.get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        user_id = int(payload.get("sub"))
    except (ValueError, TypeError):
        user_id = 0
    roles, permissions = get_live_user_authorization(db, user_id)
    return {**payload, "roles": roles, "permissions": permissions}


def require_any_permission(*codes: str):
    checker = dependencies.require_any_permission(*codes)

    def check(payload: dict = Depends(live_actor)):
        return checker(payload)

    return check


def require_permission(*codes: str):
    checker = dependencies.require_permission(*codes)

    def check(payload: dict = Depends(live_actor)):
        return checker(payload)

    return check
