"""Scope uses the same overlay-aware query as the invoice picker."""

import logging
from fastapi import HTTPException
from sqlalchemy import bindparam, text
from app.invoice.customer_picker_service import _effective_customers, check_availability
from app.invoice.xiaoman_service import resolve_okki_user_id

logger = logging.getLogger(__name__)


def user_id(user):
    return (
        int(user["sub"])
        if isinstance(user, dict)
        else int(user.id) if hasattr(user, "id") else int(user)
    )


def owner_id(db, user):
    owner = resolve_okki_user_id(db, user_id(user))
    if owner is None:
        raise HTTPException(
            409,
            detail={
                "code": "OKKI_BINDING_REQUIRED",
                "message": "请先在系统管理绑定本人OKKI账号",
            },
        )
    return owner


def list_private_companies(db, user):
    sql, params, expanding = _effective_customers(db, owner_id(db, user))
    if db.get_bind().dialect.name == "sqlite":
        sql = sql.replace(
            "ci.owner_user_ids LIKE :owner_like",
            "EXISTS (SELECT 1 FROM json_each(ci.owner_user_ids) owner WHERE CAST(owner.value AS TEXT)=:owner_exact)",
        )
        params["owner_exact"] = str(owner_id(db, user))
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
