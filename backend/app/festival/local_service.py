"""Festival rules over the shared local commercial facts, without mirrors."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy import text
from app.trade.query_service import load_orders, load_roster


def orders(db, start=None, end=None, user_id=None):
    return load_orders(db, user_id=user_id, date_from=start, date_to=end, active_roster=True)


def source_points(row):
    return 1.5 if row["source_category"] in {"social_owned", "referral"} else 1.0


def new_sign_board(db, start, end):
    from app.festival.service import ATTR_SNAPSHOT_2026, _aggregate_new_sign_rows
    rows = [{**row, "customer_id": row["company_id"], "amt": row["amount_usd"], "source_points": source_points(row)}
            for row in orders(db, start, end) if row["new_deal"] == "是"]
    stats = _aggregate_new_sign_rows(rows)
    attrs = dict(db.execute(text("SELECT employee_id, attribute_type FROM employee_attribute_history WHERE is_current = 1")).all())
    items = []
    for member in load_roster(db):
        stat = stats.get(member["user_id"], {"cnt": 0, "points": 0, "amt": 0})
        legacy = member["legacy_user_id"]
        items.append({**member, "attribute": ATTR_SNAPSHOT_2026.get(legacy) or attrs.get(legacy) or "distribute",
            "new_count": stat["cnt"], "new_points": round(stat["points"], 1), "new_amount": round(stat["amt"], 2),
            "reached": stat["cnt"] >= member["target"] > 0})
    items.sort(key=lambda row: (-row["new_points"], -row["new_amount"], row["name"]))
    return {"items": items}


def company_new_total(db, start, end):
    return len({row["company_id"] for row in orders(db, start, end) if row["new_deal"] == "是"})


def gmv_total(db, start, end):
    return float(sum((row["amount_usd"] for row in orders(db, start, end)), Decimal(0)))


def repurchase_pool(db):
    # Customer history is not restricted to today's roster or current owner.
    return {row["company_id"] for row in load_orders(db, date_from=date(2025, 1, 1)) if row["new_deal"] == "是"}


def repurchase_stats(db, start, end):
    pool = repurchase_pool(db)
    stats, firsts, amounts = {}, defaultdict(set), defaultdict(lambda: Decimal(0))
    for row in orders(db, start, end):
        uid = row["user_id"]
        if row["first_return"] == "是":
            firsts[uid].add(row["company_id"])
        if row["new_deal"] == "否" and row["company_id"] in pool:
            amounts[uid] += row["amount_usd"]
    for uid in firsts.keys() | amounts.keys():
        stats[uid] = {"first_count": len(firsts[uid]), "re_amount": float(amounts[uid])}
    return stats


def daily_orders(db, day):
    grouped = defaultdict(list)
    for row in orders(db, day, day):
        grouped[row["user_id"]].append({"order_id": row["event_order_id"], "amount": float(row["amount_usd"]), "name": row["user_name"]})
    return dict(grouped)


def order_rows(db, order_type, scope):
    from app.festival.service import ACTIVITY_NEW_SIGN_WINDOW, ACTIVITY_GMV_WINDOW
    window = ACTIVITY_NEW_SIGN_WINDOW if order_type == "new_sign" else ACTIVITY_GMV_WINDOW
    pool = repurchase_pool(db) if order_type == "repurchase" else set()
    rows = []
    for row in orders(db, *window, user_id=scope.user_id):
        include = (row["new_deal"] == "是" if order_type == "new_sign" else
            row["first_return"] == "是" if order_type == "first_return" else
            row["new_deal"] == "否" and row["company_id"] in pool)
        if include:
            rows.append({**row, "source_points": source_points(row)})
    return sorted(rows, key=lambda row: (row["account_date"], int(row["order_id"])), reverse=True)
