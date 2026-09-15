"""Small-program capabilities, evaluated against current role grants."""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.auth.service import get_live_user_authorization
from app.core.database import get_db
from app.mini.auth import get_current_mini_user

ENTRY_PERMISSIONS = {
    "export": "mini_export:write",
    "domestic": "mini_domestic:write",
    "lookup": "mini_lookup:read",
    "shipping": "mini_shipping:write",
}


def allowed_entries(db, user):
    roles, permissions = get_live_user_authorization(db, user.id)
    return [key for key, code in ENTRY_PERMISSIONS.items()
            if "super_admin" in roles or code in permissions]


def require_mini_entry(*entries):
    def dependency(user=Depends(get_current_mini_user), db: Session = Depends(get_db)):
        if not set(entries).intersection(allowed_entries(db, user)):
            raise HTTPException(status_code=403, detail={
                "code": "FORBIDDEN", "message": "没有此功能权限，请联系管理员"})
        return user
    dependency.mini_entries = entries
    return dependency
