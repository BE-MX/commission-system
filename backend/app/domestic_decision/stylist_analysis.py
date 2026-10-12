"""Hairstylist workload at report grain, under the workbench's existing scope."""
from collections import defaultdict
from app.auth.models import ArkUser
from app.domestic_decision.operations import in_period
from app.domestic_decision.schemas import PRODUCT_FIELDS


def totals(rows):
    return {"quantity": sum(row["report_qty"] for row in rows),
            "item_count": len({row["item_id"] for row in rows}),
            "order_count": len({row["order_id"] for row in rows}),
            "report_count": len(rows),
            "active_days": len({row["reported_at"][:10] for row in rows})}


def grouped(rows, fields):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(field) for field in fields)].append(row)
    result = []
    for key, values in groups.items():
        result.append({**dict(zip(fields, key)), **totals(values),
                       "evidence_refs": [{"type": "reports", "id": row["id"]} for row in values]})
    return sorted(result, key=lambda row: (-row["quantity"], str(tuple(row.get(field) for field in fields))))


def build_stylist_analysis(db, operations, payload, comparison):
    all_rows = operations["styling"]
    user_ids = {row["reported_by_user_id"] for row in all_rows}
    names = dict(db.query(ArkUser.id, ArkUser.real_name).filter(ArkUser.id.in_(user_ids)).all()) if user_ids else {}
    details = []
    for report in in_period(all_rows, payload.start_date, payload.end_date):
        item = operations["items"][report["item_id"]]
        order = operations["orders"][report["order_id"]]
        attrs = operations["attrs"][item.id][0]
        details.append({**report, "user_id": report["reported_by_user_id"],
                        "name": names.get(report["reported_by_user_id"]) or report["reported_by_name"] or f"用户 {report['reported_by_user_id']}",
                        "domestic_no": order.domestic_no, "order_kind": order.order_kind,
                        "product_id": item.product_id, "product_name": item.product_name or "未知型号",
                        "attrs": attrs, **attrs})
    people = grouped(details, ("user_id", "name"))
    previous = in_period(all_rows, *comparison) if comparison else []
    previous_by_user = defaultdict(list)
    for row in previous:
        previous_by_user[row["reported_by_user_id"]].append(row)
    for row in people:
        row["previous_quantity"] = totals(previous_by_user[row["user_id"]])["quantity"] if comparison else None
        row["quantity_change"] = row["quantity"] - row["previous_quantity"] if comparison else None
    result = {"summary": {**totals(details), "stylist_count": len(people)},
              "people": people,
              "products": grouped(details, ("user_id", "name", "product_id", "product_name", *PRODUCT_FIELDS)),
              "dimensions": {field: grouped(details, ("user_id", "name", field)) for field in PRODUCT_FIELDS},
              "trend": grouped([{**row, "date": row["reported_at"][:10]} for row in details], ("user_id", "name", "date")),
              "details": details}
    result["trend"].sort(key=lambda row: (row["date"], row["user_id"]))
    return result, names
