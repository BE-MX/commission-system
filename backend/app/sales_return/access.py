"""Fresh platform permissions and frozen original-order ownership."""
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.models import ArkUserExternalBinding
from app.portal.authority import lock_authority
from app.receipt.authority import current_user


def actor(user):
    return int(user.get("id") or user.get("sub") or 0)


def all_access(user):
    return "super_admin" in user.get("roles", []) or "sales_return:read_all" in user.get("permissions", [])


def authorize(db, user, permission, *, write=False):
    if write:
        lock_authority(db, force=True)
    return current_user(db, user, permission)


def owner_id(db, user):
    rows = db.scalars(select(ArkUserExternalBinding.external_account_id).where(
        ArkUserExternalBinding.ark_user_id == actor(user), ArkUserExternalBinding.provider == "okki",
        ArkUserExternalBinding.binding_status == "active", ArkUserExternalBinding.deleted_at.is_(None))).all()
    identities = {str(value) for value in rows if value}
    if len(identities) != 1:
        raise HTTPException(422, "当前账号缺少唯一有效的 OKKI 业务员绑定，请联系管理员核对")
    return identities.pop()


def scope(query, db, user, model):
    if all_access(user):
        return query
    return query.where(model.owner_okki_user_id == owner_id(db, user))


def ensure(db, row, user):
    if row is None or not all_access(user) and str(row.owner_okki_user_id) != owner_id(db, user):
        raise HTTPException(404, "退货单不存在或不在当前数据范围内")
    return row
