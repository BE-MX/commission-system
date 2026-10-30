"""Paginated source orders using the same cohort facts as award statistics."""
from decimal import Decimal

from fastapi import HTTPException

from app.battle_report.access import load_report, select_members, visible_members
from app.battle_report.award_statistics import cohort_orders, normalize_facts, order_key, source_facts
from app.battle_report.statistics import money
from app.core.list_sort import apply_items_sort
from app.core.time import beijing_now


def list_metric_orders(db, report_id, user, *, metric, customer=None, order_name=None,
                       start_date=None, end_date=None, team=None, member_id=None,
                       page=1, page_size=20, sort_field="", sort_order=""):
    if metric not in {"new_sign", "repeat", "combined"}:
        raise HTTPException(422, "未知统计来源")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "下单日期开始不能晚于结束")
    report, members, own = load_report(db, report_id, user)
    allowed = select_members(visible_members(report, members, own, user, details=True),
                             team=team, member_id=member_id)
    now = beijing_now()
    # Establish original ownership using the full roster BEFORE applying caller scope
    # or filters. A transfer must not turn another person's client into a new cohort.
    raw, synced = source_facts(db, report, members, now)
    orders, issues, _, _, _ = normalize_facts(report, raw, now)
    groups = cohort_orders(orders)
    rows = []
    for member in allowed:
        group = groups.get(str(member.okki_user_id), {})
        selected = (group.get("new_sign", []) + group.get("repeat", []) if metric == "combined"
                    else group.get(metric, []))
        for order in selected:
            if start_date and order["day"] < start_date or end_date and order["day"] > end_date:
                continue
            if customer and customer.strip().casefold() not in order["company_name"].casefold():
                continue
            if order_name and order_name.strip().casefold() not in order["order_name"].casefold():
                continue
            rows.append({"order_id": order["id"], "order_no": order["order_no"],
                         "source_type": order.get("source_type", "okki"), "return_id": order.get("return_id"),
                         "original_order_id": order.get("original_order_id", order["id"]),
                         "order_name": order["order_name"], "company_id": order["cid"],
                         "company_name": order["company_name"], "account_date": order["day"].isoformat(),
                         "amount_usd": format(order["amount"], "f"),
                         "member_id": member.id, "user_name": member.user_name,
                         "role": "new_sign" if order["new"] else "repeat"})
    rows.sort(key=lambda row: order_key({"day": row["account_date"], "id": row["order_id"]}), reverse=True)
    fields = {key: key for key in ("company_name", "order_name", "order_no", "account_date", "user_name")}
    fields["amount_usd"] = lambda row: Decimal(row["amount_usd"])
    rows = apply_items_sort(rows, sort_field, sort_order, fields, tie_breaker="order_id")
    total_amount = sum((Decimal(row["amount_usd"]) for row in rows), Decimal(0))
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": len(rows), "page": page, "page_size": page_size,
            "customer_count": len({row["company_id"] for row in rows if row["source_type"] != "sales_return"}), "total_amount": money(total_amount),
            "currency": "USD", "data_complete": not issues,
            "amount_scope": "original_new_customer_cohort",
            "amount_note": ("按原新签客户归属汇总；PK总览新签金额按订单负责人统计，客户转交后可能不同。"
                            if report.award_kind == "new_sign_pk" else None),
            # Full-roster issues can contain another salesperson's customer/order IDs.
            "warning": "统计源存在待核对记录，以下为已识别明细，合计暂不作为完整业绩。" if issues else None,
            "calculated_at": now.isoformat(), "source_synced_at": synced,
            "basis": "下单日期沿用战报核算日期；USD有效货物订单；复购归原新签人；合计覆盖全部筛选结果"}
