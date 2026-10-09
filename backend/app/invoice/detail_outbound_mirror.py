"""Bulk, exact invoice associations from the existing read-only outbound mirror."""
from sqlalchemy import text
from app.shipping_inspection import outbound_service as mirror


def read(db, invoice, scope):
    link, records, items = mirror._link(db)
    columns = mirror._table_columns(db, mirror.ITEMS_TABLE)
    required = {"order_id", "order_record_id", "product_id", "sku_id"}
    if link != "invoice" or not required <= columns or not items["quantity"]:
        raise ValueError("出库镜像缺少精确订单行关联，进度待核验")
    clauses = ["i.order_id=:order_id", mirror.deleted_clause(db, records)]
    params = {"order_id": str(invoice.xiaoman_order_id)}
    if scope is not None:
        clauses.append(mirror._owner_scope_clause(db, records))
        params["scope_okki_user_id"] = scope
    rows = db.execute(text(f"""SELECT {mirror._record_select(records)},
        i.`{items['id']}` AS item_id, i.order_id, i.order_record_id,
        i.product_id, i.sku_id, i.`{items['quantity']}` AS outbound_count
        FROM `{mirror._schema()}`.`{mirror.RECORDS_TABLE}` r
        JOIN `{mirror._schema()}`.`{mirror.ITEMS_TABLE}` i
          ON i.`{items['invoice_id']}`=r.`{records['invoice_id']}`
        WHERE {' AND '.join(clauses)}
        ORDER BY r.`{records['id']}`, i.`{items['id']}`"""), params).mappings().all()
    documents = {}
    for row in rows:
        identity, record_id = str(row["outbound_invoice_id"] or ""), str(row["outbound_record_id"])
        if not identity or str(row["company_id"]) != str(invoice.customer_id):
            raise ValueError("出库镜像客户或单据身份不一致")
        if identity in documents and documents[identity]["record_id"] != record_id:
            raise ValueError("同一出库单存在重复镜像，进度待核验")
        document = documents.setdefault(identity, {
            "outbound_invoice_id": identity, "record_id": record_id,
            "serial_id": row["outbound_no"], "outbound_time": row["outbound_date"],
            "mirror_updated_at": row["mirror_updated_at"], "maker_name": row["owner_name"],
            "record_list": [],
        })
        document["record_list"].append({key: row[key] for key in
            ("order_id", "order_record_id", "product_id", "sku_id", "outbound_count")})
    return list(documents.values())
