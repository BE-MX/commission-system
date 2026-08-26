"""Integration App credential lifecycle and owner eligibility services."""

from datetime import datetime
import secrets

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.auth.utils import hash_token
from app.core.time import beijing_now
from app.integration.models import IntegrationApp
from app.integration.schemas import IntegrationAppCreate


INVOICE_SCOPE = "invoice:write"


def user_has_invoice_write(user: ArkUser) -> bool:
    return (
        "super_admin" in set(get_user_roles(user))
        or INVOICE_SCOPE in set(get_user_permissions(user))
    )


def _active_owner(db: Session, user_id: int) -> ArkUser:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.deleted_at.is_(None),
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="目标账号不存在")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="目标账号已停用，不能绑定接入应用")
    if not user_has_invoice_write(user):
        raise HTTPException(status_code=400, detail="目标账号当前缺少 invoice:write 权限")
    return user


def _plain_token() -> str:
    return f"ark_live_{secrets.token_urlsafe(32)}"


def _public_id() -> str:
    return f"app_{secrets.token_urlsafe(18)}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _app_payload(row: IntegrationApp, owner: ArkUser | None = None) -> dict:
    return {
        "id": row.id,
        "public_id": row.public_id,
        "name": row.name,
        "owner_user_id": row.owner_user_id,
        "owner_username": owner.username if owner is not None else None,
        "owner_real_name": owner.real_name if owner is not None else None,
        "token_suffix": row.token_suffix,
        "scopes": list(row.scopes or []),
        "is_active": bool(row.is_active),
        "expires_at": _iso(row.expires_at),
        "last_used_at": _iso(row.last_used_at),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def list_user_candidates(db: Session, *, q: str, limit: int) -> list[dict]:
    query = db.query(ArkUser).filter(
        ArkUser.deleted_at.is_(None),
        ArkUser.is_active.is_(True),
    )
    keyword = q.strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(
            ArkUser.username.ilike(pattern),
            ArkUser.real_name.ilike(pattern),
        ))
    users = query.order_by(ArkUser.real_name, ArkUser.username).limit(limit).all()
    return [
        {
            "user_id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "has_invoice_write": user_has_invoice_write(user),
        }
        for user in users
    ]


def list_apps(db: Session) -> list[dict]:
    rows = (
        db.query(IntegrationApp, ArkUser)
        .outerjoin(ArkUser, ArkUser.id == IntegrationApp.owner_user_id)
        .order_by(IntegrationApp.created_at.desc(), IntegrationApp.id.desc())
        .all()
    )
    return [_app_payload(row, owner) for row, owner in rows]


def create_app(
    db: Session,
    request: IntegrationAppCreate,
    *,
    created_by: int,
) -> dict:
    owner = _active_owner(db, request.owner_user_id)
    if request.expires_at is not None and request.expires_at <= beijing_now():
        raise HTTPException(status_code=400, detail="过期时间必须晚于当前北京时间")

    token = _plain_token()
    row = IntegrationApp(
        public_id=_public_id(),
        name=request.name,
        owner_user_id=owner.id,
        token_hash=hash_token(token),
        token_suffix=token[-6:],
        scopes=[INVOICE_SCOPE],
        expires_at=request.expires_at,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        **_app_payload(row, owner),
        "token": token,
        "note": "明文 Token 仅本次返回，关闭后无法再次查看",
    }


def rotate_app_token(db: Session, app_id: int) -> dict:
    row = db.query(IntegrationApp).filter(
        IntegrationApp.id == app_id
    ).with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="接入应用不存在")
    if not row.is_active:
        raise HTTPException(status_code=409, detail="接入应用已吊销，不能轮换凭证")
    owner = _active_owner(db, row.owner_user_id)

    token = _plain_token()
    row.token_hash = hash_token(token)
    row.token_suffix = token[-6:]
    row.last_used_at = None
    db.commit()
    db.refresh(row)
    return {
        **_app_payload(row, owner),
        "token": token,
        "note": "旧 Token 已立即失效；新明文 Token 仅本次返回",
    }


def revoke_app(db: Session, app_id: int) -> dict:
    row = db.query(IntegrationApp).filter(IntegrationApp.id == app_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="接入应用不存在")
    row.is_active = False
    db.commit()
    return {"id": row.id, "is_active": False}
