"""Scope uses the same overlay-aware query as the invoice picker."""

import logging
from fastapi import HTTPException
from sqlalchemy import bindparam, text
from app.invoice.customer_picker_service import _effective_customers, check_availability
from app.invoice.xiaoman_service import resolve_okki_user_id
from app.client_desk import read_scope

logger = logging.getLogger(__name__)


def user_id(user):
    return (
        int(user["sub"])
        if isinstance(user, dict)
        else int(user.id) if hasattr(user, "id") else int(user)
    )


def owner_id(db, user):
    owner = read_scope.once(
        ("owner", db, user_id(user)), lambda: resolve_okki_user_id(db, user_id(user))
    )
    if owner is None:
        raise HTTPException(
            409,
            detail={
                "code": "OKKI_BINDING_REQUIRED",
                "message": "请先在系统管理绑定本人OKKI账号",
            },
        )
    return owner


def list_private_companies(db, user, *, refresh=False):
    owner = owner_id(db, user)
    key = ("companies", db.get_bind(), user_id(user), owner)
    if refresh:
        read_scope.invalidate(key)
        read_scope.forget((key, db))

    def load():
        if read_scope.cache_companies():
            return read_scope.cached(key, 45, lambda: _list_private_companies(db, owner))
        return _list_private_companies(db, owner)

    # Callers may enrich cards; never hand them the shared cached dictionaries.
    return [dict(card) for card in read_scope.once((key, db), load)]


def _list_private_companies(db, owner):
    sql, params, expanding = _effective_customers(db, owner)
    if db.get_bind().dialect.name == "sqlite":
        sql = sql.replace(
            "ci.owner_user_ids LIKE :owner_like",
            "EXISTS (SELECT 1 FROM json_each(ci.owner_user_ids) owner WHERE CAST(owner.value AS TEXT)=:owner_exact)",
        )
        params["owner_exact"] = str(owner)
    stmt = text(f"SELECT * FROM ({sql}) scoped ORDER BY company_id")
    stmt = stmt.bindparams(*(bindparam(k, expanding=True) for k in expanding))
    return [
        {
            "company_id": str(r["company_id"]),
            "name": r["company_name"],
            "country": r["country_name"],
        }
        for r in db.execute(stmt, params).mappings()
    ]


def assert_company_access(db, user, company_id, *, realtime=True):
    owner = owner_id(db, user)
    if not realtime:
        if not any(
            c["company_id"] == str(company_id) for c in list_private_companies(db, user)
        ):
            raise HTTPException(404, "客户不存在或已转出")
        return
    key = ("ownership", db.get_bind(), user_id(user), owner, str(company_id))

    def verify():
        if read_scope.read_only():
            return read_scope.cached(key, 60, lambda: _verify(db, company_id, owner))
        # A fresh action must not leave a previous successful read grant behind.
        try:
            return read_scope.fresh(key, lambda: _verify(db, company_id, owner))
        except HTTPException:
            read_scope.invalidate(("companies", db.get_bind(), user_id(user), owner))
            raise

    read_scope.once((key, db), verify)


def _verify(db, company_id, owner):
    try:
        result = check_availability(
            db, customer_id=str(company_id), owner_okki_id=owner
        )
    except LookupError as exc:
        raise HTTPException(404, "客户不存在或已转出") from exc
    except Exception as exc:
        logger.warning(
            "client_desk scope verification unavailable type=%s", type(exc).__name__
        )
        print("client_desk scope verification unavailable", flush=True)
        raise HTTPException(503, "暂时无法核验客户归属，请重试") from exc
    if result.get("status") != "active":
        raise HTTPException(404, "客户不存在或已转出")
