"""Combined customer/contact search, paginated after resolving manual overlays."""

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.invoice import product_service
from app.invoice.models import InvoiceCustomerOverlay


def check_availability(db: Session, *, customer_id: str, owner_okki_id: int | None = None) -> dict:
    """Verify one scoped choice without changing customer or invoice business data."""
    from app.invoice import okki_client

    sql, params, expanding = _effective_customers(db, owner_okki_id)
    statement = text(f"SELECT company_id FROM ({sql}) ci WHERE company_id=:customer_id")
    statement = statement.bindparams(*(bindparam(key, expanding=True) for key in expanding))
    if db.execute(statement, {**params, "customer_id": customer_id}).first() is None:
        raise LookupError("客户不在当前可选范围，请重新搜索")
    result = okki_client.get_company_availability(db, int(customer_id))
    owners = result.pop("owner_user_ids", [])
    if result["status"] == "active" and owner_okki_id is not None and str(owner_okki_id) not in owners:
        return {"company_id": customer_id, "status": "out_of_scope"}
    return result


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


def _contact_phone_sql(schema: str, *, mysql: bool) -> str:
    # Invoices store name/email snapshots. Use exact normalized comparisons even
    # when MySQL's column collation normally equates different accented names.
    binary_collation = "utf8mb4_bin" if mysql else "BINARY"
    nonspace_pattern = "[^[:space:]]" if mysql else r"\S"

    def identity(column: str) -> str:
        return f"LOWER(TRIM({column})) COLLATE {binary_collation}"

    def has_phone(column: str) -> str:
        return f"COALESCE({column} REGEXP '{nonspace_pattern}', 0)"

    selected_email = identity("page.email")
    invoice_email = identity("i.contact_email")
    missing_email = "(NULLIF(TRIM(page.email), '') IS NULL OR NULLIF(TRIM(i.contact_email), '') IS NULL)"
    invoice_customer_id = "CAST(page.company_id AS CHAR)" + (" COLLATE utf8mb4_unicode_ci" if mysql else "")
    # When the name is shared, require an email match unique to this contact.
    return f"""CASE WHEN page.kind = 'contact' AND NOT {has_phone('page.tel')} THEN (
        SELECT TRIM(i.contact_phone)
        FROM ark_invoices i
        WHERE i.customer_id = {invoice_customer_id}
            AND i.status != 'deleted'
            AND {has_phone('i.contact_phone')}
            AND NULLIF(TRIM(page.name), '') IS NOT NULL
            AND {identity('i.contact_name')} = {identity('page.name')}
            AND ({missing_email} OR {invoice_email} = {selected_email})
            AND NOT EXISTS (
                SELECT 1 FROM `{schema}`.customer_contacts other
                WHERE other.company_id = page.company_id AND other.id != page.contact_id
                    AND {identity('other.name')} = {identity('page.name')}
                    AND ({missing_email} OR {identity('other.email')} = {selected_email})
            )
        ORDER BY i.created_at DESC, i.id DESC
        LIMIT 1
    ) ELSE page.tel END"""


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
    schema = product_service._schema()
    if keyword:
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
    order = "company_name, company_id, kind DESC, name, contact_id"
    page_sql = f"""
        SELECT * FROM ({options_sql}) options
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    if keyword:
        phone_sql = _contact_phone_sql(schema, mysql=db.get_bind().dialect.name == "mysql")
        page_sql = f"""
            SELECT page.company_id, page.company_name, page.country_name, page.kind,
                page.contact_id, page.name, page.email, {phone_sql} AS tel
            FROM ({page_sql}) page ORDER BY {order}
        """
    rows = db.execute(statement(page_sql), {**params, "limit": limit, "offset": offset}).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        key = item["contact_id"] if item["kind"] == "contact" else item["company_id"]
        item["option_key"] = f"{item['kind']}:{key}"
        items.append(item)
    return {"items": items, "total": total, "has_more": offset + limit < total}
