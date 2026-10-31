"""Atomically replace local weekly color totals, including cleared sales."""
import logging
from datetime import timedelta
from decimal import Decimal
from sqlalchemy import select
from app.color.models import ColorPalette, ColorTrendData
from app.color.trend_service import COLOR_FAMILIES
from app.core.time import beijing_today
from app.trade.query_service import load_orders, load_product_rows
from app.trade.refresh_service import projection_status

logger = logging.getLogger(__name__)
COLOR_TO_FAMILY = {
    "黑色": "black", "自然黑": "black", "乌黑": "black",
    "棕色": "brown", "深棕": "brown", "巧克力棕": "brown", "栗棕": "brown", "灰棕": "brown",
    "金色": "blonde", "脏金": "blonde", "蜜金": "blonde", "白金": "blonde", "极浅金": "blonde",
    "红色": "red", "亮红": "red", "勃艮第": "red", "银色": "silver", "灰色": "silver",
}


def aggregate_sales(db, *, week_start=None):
    today = beijing_today()
    start = week_start or today - timedelta(days=today.weekday())
    if start.weekday() != 0 or start > today:
        raise ValueError("销售色彩统计周期必须为已到达的周一")
    end = min(today, start + timedelta(days=6))
    state = projection_status(db, date_from=start, date_to=end)
    if state["status"] != "current":
        return {"status": "pending", "projection_status": state}
    totals = {family: Decimal(0) for family in COLOR_FAMILIES}
    rows = load_product_rows(db, load_orders(db, date_from=start, date_to=end))
    aliases = {}
    for palette in db.scalars(select(ColorPalette)):
        for value in (palette.industry_code, palette.brand_code, palette.display_name, palette.display_name_en):
            if value and value.strip():
                aliases.setdefault(value.strip().casefold(), set()).add(palette.color_family)
    unresolved = {}
    for row in rows:
        color = row["color"].strip()
        candidates = aliases.get(color.casefold(), set())
        family = next(iter(candidates)) if len(candidates) == 1 else COLOR_TO_FAMILY.get(color) if not candidates else None
        if family not in totals:
            unresolved[color] = unresolved.get(color, 0) + row["quantity"]
        else:
            totals[family] += Decimal(str(row["quantity"]))
    if unresolved:
        # Do not publish a false zero or discard prior valid totals when the
        # palette mapping is missing or conflicting across sources.
        return {"status": "needs_review", "week_start": start.isoformat(), "unresolved_colors": unresolved,
            "projection_status": state}
    existing = {row.color_family: row for row in db.scalars(select(ColorTrendData).where(
        ColorTrendData.period_date == start, ColorTrendData.period_type == "weekly", ColorTrendData.data_source == "sales"))}
    low, high = min(totals.values()), max(totals.values())
    try:
        for family, amount in totals.items():
            row = existing.get(family)
            if row is None:
                row = ColorTrendData(color_family=family, data_source="sales", period_date=start, period_type="weekly")
                db.add(row)
            row.raw_value = amount
            row.normalized_score = round((amount - low) / (high - low) * 100, 2) if high > low else 0
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Local color sales aggregation failed", exc_info=True)
        print("Local color sales aggregation failed; transaction rolled back", flush=True)
        raise
    return {"status": "success", "week_start": start.isoformat(), "families": sum(value > 0 for value in totals.values()),
        "family_sales": {key: float(value) for key, value in totals.items()}, "projection_status": state}



def refresh_sales_history(db):
    """Recompute represented weeks, including invalidated orders' old periods.

    This runs daily: Monday includes the entire preceding week, and a late
    cancellation repairs its historical week instead of waiting indefinitely.
    """
    from app.customer.models import CustomerOrder
    today = beijing_today()
    current = today - timedelta(days=today.weekday())
    dates = db.scalars(select(CustomerOrder.account_date).where(
        CustomerOrder.account_date.is_not(None), CustomerOrder.account_date <= today).distinct()).all()
    periods = {day - timedelta(days=day.weekday()) for day in dates} | {current, current - timedelta(days=7)}
    results = []
    for start in sorted(periods):
        result = aggregate_sales(db, week_start=start)
        results.append({"week_start": start.isoformat(), "status": result["status"]})
        if result["status"] == "needs_review":
            logger.warning("Local color sales mapping needs review for week %s", start)
            print(f"Local color sales mapping needs review for week {start}", flush=True)
    return {"periods": results}
