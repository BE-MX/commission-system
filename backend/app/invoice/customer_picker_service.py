"""Combined customer/contact search, paginated after resolving manual overlays."""

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.invoice import product_service
from app.invoice.models import InvoiceCustomerOverlay


def _effective_customers(db: Session, owner_okki_id: int | None) -> tuple[str, dict, list[str]]:
    schema = product_service._schema()
    # Mirror uses utf8mb4_0900_ai_ci; Ark overlays use utf8mb4_unicode_ci.
    # Explicitly align UNION text columns without changing either database.
    collation = " COLLATE utf8mb4_unicode_ci" if db.get_bind().dialect.name == "mysql" else ""
    overlays = db.query(InvoiceCustomerOverlay).all()
    mirror_times = product_service._mirror_update_times(db, [row.company_id for row in overlays])
    overridden, visible = [], []
    for row in overlays:
        mirror_time = product_service._parse_ts(mirror_times.get(str(row.company_id)))
        overlay_time = product_service._parse_ts(row.source_update_time)
        if mirror_time is not None and overlay_time is not None and mirror_time >= overlay_time:
            continue
        overridden.append(str(row.company_id))
        if owner_okki_id is None or str(owner_okki_id) in {str(v) for v in (row.owner_user_ids or [])}:
            visible.append(str(row.company_id))

    clauses, params, expanding = [], {}, []
    if owner_okki_id is not None:
        clause, owner_params = product_service._owner_filter_clause(db, owner_okki_id)
        clauses.append(clause)
        params.update(owner_params)
    if overridden:
        clauses.append("ci.company_id NOT IN :overridden")
        params["overridden"] = overridden
        expanding.append("overridden")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT ci.company_id, ci.company_name{collation} AS company_name, ci.country_name{collation} AS country_name FROM `{schema}`.customer_info ci {where}"
    if visible:
        # Mirror country/name fallback matches the existing manual-sync merge.
        sql += f""" UNION ALL
            SELECT o.company_id, COALESCE(NULLIF(o.company_name, ''), ci.company_name){collation} AS company_name,
                COALESCE(NULLIF(o.country_name, ''), ci.country_name){collation} AS country_name
            FROM ark_invoice_customer_overlays o
            LEFT JOIN `{schema}`.customer_info ci ON ci.company_id = o.company_id
            WHERE o.company_id IN :visible
        """
        params["visible"] = visible
        expanding.append("visible")
    return sql, params, expanding


def search_options(
    db: Session, *, keyword: str | None = None, owner_okki_id: int | None = None,
    offset: int = 0, limit: int = 50,
) -> dict:
    customers_sql, params, expanding = _effective_customers(db, owner_okki_id)
    keyword = (keyword or "").strip().lower()
    where = ""
    if keyword:
        params["keyword"] = "%" + keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        where = "WHERE LOWER(ci.company_name) LIKE :keyword ESCAPE '!' OR ci.company_id LIKE :keyword ESCAPE '!'"
    options_sql = f"""
        SELECT ci.company_id, ci.company_name, ci.country_name, 'customer' AS kind,
            NULL AS contact_id, NULL AS name, NULL AS email, NULL AS tel
        FROM ({customers_sql}) ci {where}
    """
    # Empty input browses customers, without duplicating every contact in the list.
    if keyword:
        schema = product_service._schema()
        options_sql += f""" UNION ALL
            SELECT ci.company_id, ci.company_name, ci.country_name, 'contact' AS kind,
                cc.id AS contact_id, cc.name, cc.email, cc.tel
            FROM `{schema}`.customer_contacts cc
            JOIN ({customers_sql}) ci ON ci.company_id = cc.company_id
            WHERE LOWER(cc.name) LIKE :keyword ESCAPE '!'
        """

    def statement(sql):
        return text(sql).bindparams(*(bindparam(key, expanding=True) for key in expanding))

    total = db.execute(statement(f"SELECT COUNT(*) FROM ({options_sql}) options"), params).scalar_one()
    rows = db.execute(statement(f"""
        SELECT * FROM ({options_sql}) options
        ORDER BY company_name, company_id, kind DESC, name, contact_id
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": limit, "offset": offset}).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        key = item["contact_id"] if item["kind"] == "contact" else item["company_id"]
        item["option_key"] = f"{item['kind']}:{key}"
        items.append(item)
    return {"items": items, "total": total, "has_more": offset + limit < total}
