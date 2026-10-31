"""Read legacy return effects alongside formal orders without rebooking them.

The frozen legacy seller is mapped through the reviewed roster, never through
the order's current owner. Unknown identities stay namespaced, not guessed.
"""
from sqlalchemy import select

from app.core.config import get_settings
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import CustomerOrder
from app.sales_return.gmv import adjustments
from app.trade.models import SalesRoster


def load_return_adjustments(db, start, end, *, owner_ids=None):
    facts = adjustments(db, start, end)
    if not facts:
        return []
    owners = {str(row.legacy_user_id): str(row.ark_user_id) for row in db.scalars(
        select(SalesRoster).where(SalesRoster.legacy_user_id.is_not(None)))}
    namespace = get_settings().PORTAL_OKKI_NAMESPACE
    orders = {}
    if namespace:
        query = select(CustomerOrder.external_order_id, CustomerOrder.id,
            logical_owner_expression(CustomerOrder, "order")).where(
                CustomerOrder.source_system == "okki",
                CustomerOrder.source_account_key == namespace,
                CustomerOrder.external_order_id.in_({f["order_id"] for f in facts}))
        orders = {str(external): (str(identity), str(customer))
                  for external, identity, customer in db.execute(query)}
    allowed = None if owner_ids is None else {str(uid) for uid in owner_ids}
    result = []
    for fact in facts:
        owner = owners.get(str(fact["owner"]), f"okki:user:{fact['owner']}")
        if allowed is not None and owner not in allowed:
            continue
        identity, customer = orders.get(str(fact["order_id"]),
            (None, f"okki:customer:{fact['company_id']}"))
        result.append({**fact, "legacy_owner_id": fact["owner"],
            "owner": owner, "user_id": owner, "company_id": customer,
            "local_order_id": identity, "event_order_id": fact["order_id"]})
    return result


def filter_return_adjustments(db, facts, *, team=None, filters=None):
    if team:
        owners = {str(uid) for uid in db.scalars(select(SalesRoster.ark_user_id).where(SalesRoster.team == team))}
        facts = [fact for fact in facts if fact["owner"] in owners]
    if filters and not filters.is_empty():
        from app.trade.query_service import load_orders
        identities = {int(fact["local_order_id"]) for fact in facts if fact["local_order_id"] is not None}
        matching = {row["order_id"] for row in load_orders(db, filters=filters, historical_order_ids=identities)}
        facts = [fact for fact in facts if fact["local_order_id"] in matching]
    return facts
