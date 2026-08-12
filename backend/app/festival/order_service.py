"""采购节订单明细查询与登录用户数据范围。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.models import ArkUserExternalBinding
from app.festival import service

OrderType = Literal["new_sign", "first_return", "repurchase"]


@dataclass(frozen=True)
class FestivalOrderScope:
    mode: Literal["self", "all", "user"]
    user_id: str | None
    user_name: str | None
    can_read_all: bool
    users: list[dict]


def _roster(db: Session) -> list[dict]:
    return [dict(row) for row in db.execute(text(
        "SELECT t.user_id, t.Name AS user_name, t.Team AS team, t.Camp AS camp, "
        "       t.newclient_t AS target "
        "FROM lsordertest.user_rel_team t WHERE 1=1"
        + service._active_roster_filter("t") + " ORDER BY t.id"
    )).mappings()]


def resolve_scope(db: Session, current_user: dict,
                  requested_user_id: str | None = None) -> FestivalOrderScope:
    roster = _roster(db)
    by_id = {str(row["user_id"]): row for row in roster}
    permissions = set(current_user.get("permissions") or [])
    roles = set(current_user.get("roles") or [])
    can_read_all = "festival_order:read_all" in permissions or "super_admin" in roles
    users = [{"user_id": str(row["user_id"]), "user_name": row["user_name"]}
             for row in roster] if can_read_all else []

    if can_read_all:
        if not requested_user_id:
            return FestivalOrderScope("all", None, None, True, users)
        selected = by_id.get(str(requested_user_id))
        if selected is None:
            raise HTTPException(422, "所选业务员不在采购节有效参赛名册中")
        return FestivalOrderScope(
            "user", str(selected["user_id"]), str(selected["user_name"]), True, users,
        )

    try:
        ark_user_id = int(current_user.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(422, "当前登录账号无法识别，请重新登录") from None
    binding = (
        db.query(ArkUserExternalBinding)
        .filter(
            ArkUserExternalBinding.ark_user_id == ark_user_id,
            ArkUserExternalBinding.provider == "okki",
            ArkUserExternalBinding.binding_status == "active",
            ArkUserExternalBinding.deleted_at.is_(None),
        )
        .order_by(ArkUserExternalBinding.is_primary.desc(), ArkUserExternalBinding.id)
        .first()
    )
    okki_user_id = str(binding.external_account_id).strip() if binding else ""
    if not okki_user_id:
        raise HTTPException(
            422,
            "当前账号尚未绑定 OKKI 业务员，请联系管理员在“系统管理 → 外部账号绑定”中配置",
        )
    selected = by_id.get(okki_user_id)
    if selected is None:
        raise HTTPException(422, "当前绑定的 OKKI 业务员不在采购节有效参赛名册中")
    return FestivalOrderScope(
        "self", okki_user_id, str(selected["user_name"]), False, [],
    )


def _order_rows(db: Session, order_type: OrderType,
                scope: FestivalOrderScope) -> list[dict]:
    if order_type == "new_sign":
        mark, date_from, date_to = (
            service.NEW_SIGN_MARK, *service.ACTIVITY_NEW_SIGN_WINDOW,
        )
        pool = ""
    elif order_type == "first_return":
        mark, date_from, date_to = (
            service.FIRST_RETURN_MARK, *service.ACTIVITY_GMV_WINDOW,
        )
        pool = ""
    else:
        mark, date_from, date_to = service.RE_MARK, *service.ACTIVITY_GMV_WINDOW
        pool = (
            " AND EXISTS (SELECT 1 FROM lsordertest.okki_orders historical"
            "             WHERE historical.company_id = o.company_id"
            "               AND historical.custom_fields LIKE :new_mark"
            "               AND historical.account_date >= '2025-01-01')"
        )
    user_filter = " AND o.user_id = :user_id" if scope.user_id else ""
    sql = (
        "SELECT o.order_id, o.order_no, o.account_date, o.amount_usd,"
        "       o.company_id, COALESCE(ci.company_name, '') AS company_name,"
        "       o.user_id, t.Name AS user_name, t.Team AS team, t.Camp AS camp,"
        "       o.custom_fields "
        "FROM lsordertest.okki_orders o "
        "JOIN lsordertest.user_rel_team t ON t.user_id = o.user_id "
        "LEFT JOIN lsordertest.customer_info ci ON ci.company_id = o.company_id "
        "WHERE o.custom_fields LIKE :mark"
        "  AND o.account_date >= :date_from AND o.account_date <= :date_to"
        + service._active_roster_filter("t")
        + service._common_filter("o") + pool + user_filter
        + " ORDER BY o.account_date DESC, o.order_id DESC"
    )
    params = {
        "mark": mark, "date_from": date_from, "date_to": date_to,
        "new_mark": service.NEW_ANY_MARK, "user_id": scope.user_id,
    }
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def _decorate_new_sign(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((str(row["user_id"]), str(row["company_id"])), []).append(row)
    for customer_rows in grouped.values():
        earliest = min(
            customer_rows,
            key=lambda row: (str(row["account_date"] or ""), str(row["order_id"] or "")),
        )
        points = max(service.new_sign_source_points(row.get("custom_fields"))
                     for row in customer_rows)
        for row in customer_rows:
            row["points"] = points if row is earliest else 0.0
            row["points_note"] = "" if row is earliest else "同客户已计分"
    return rows


def _public_row(row: dict) -> dict:
    result = {
        key: row.get(key) for key in (
            "order_no", "account_date", "amount_usd", "company_name",
            "user_id", "user_name", "team", "camp",
        )
    }
    result["amount_usd"] = float(result["amount_usd"] or 0)
    if "points" in row:
        result["points"] = float(row["points"] or 0)
        result["points_note"] = row.get("points_note") or ""
    return result


def list_orders(db: Session, order_type: OrderType, scope: FestivalOrderScope,
                page: int, page_size: int, keyword: str | None = None) -> dict:
    rows = _order_rows(db, order_type, scope)
    if order_type == "new_sign":
        rows = _decorate_new_sign(rows)
    term = (keyword or "").strip().casefold()
    if term:
        rows = [row for row in rows if term in str(row.get("order_no") or "").casefold()
                or term in str(row.get("company_name") or "").casefold()]
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": [_public_row(row) for row in rows[start:start + page_size]],
        "total": total, "page": page, "page_size": page_size,
    }


def get_summary(db: Session, scope: FestivalOrderScope) -> dict:
    new_rows = _decorate_new_sign(_order_rows(db, "new_sign", scope))
    first_rows = _order_rows(db, "first_return", scope)
    repurchase_rows = _order_rows(db, "repurchase", scope)
    roster = _roster(db)
    if scope.user_id:
        target = next((int(row.get("target") or 0) for row in roster
                       if str(row["user_id"]) == scope.user_id), 0)
        new_count = len({str(row["company_id"]) for row in new_rows})
    else:
        target = service.COMPANY_NEW_SIGN_TARGET
        new_count = len({str(row["company_id"]) for row in new_rows})
    points = sum(float(row.get("points") or 0) for row in new_rows)
    return {
        "scope": scope.mode,
        "selected_user_id": scope.user_id,
        "selected_user_name": scope.user_name,
        "can_read_all": scope.can_read_all,
        "users": scope.users,
        "new_sign": {
            "count": new_count,
            "target": target,
            "progress_percent": round(new_count / target * 100, 1) if target else 0.0,
            "points": points,
        },
        "first_return_count": len({str(row["company_id"]) for row in first_rows}),
        "repurchase_amount": sum(float(row.get("amount_usd") or 0)
                                 for row in repurchase_rows),
        "windows": {
            "new_sign": list(service.ACTIVITY_NEW_SIGN_WINDOW),
            "first_return": list(service.ACTIVITY_GMV_WINDOW),
            "repurchase": list(service.ACTIVITY_GMV_WINDOW),
        },
    }
