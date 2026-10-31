"""Shared commercial facts for local-mode consumers; no transaction mirrors.

Order identity is the customer read-model ID, owner identity is ArkUser ID.
History import must bind these same rows instead of creating a second sale.
"""
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import lazyload
from app.auth.models import ArkUser
from app.customer.logical_customer_service import logical_owner_expression
from app.customer.models import CustomerAccount, CustomerOrder, CustomerOrderItem, CustomerSourceRecord
from app.trade.models import SalesRoster


def formal_order_predicate():
    """A local binding supersedes its legacy projection; shadow has no route."""
    from app.invoice.models import Invoice
    local_binding = select(Invoice.id).where(Invoice.id == CustomerOrder.local_invoice_id,
        Invoice.transaction_mode == "local").exists()
    return or_(and_(CustomerOrder.source_system == "okki",
                    or_(CustomerOrder.local_invoice_id.is_(None), local_binding)),
               and_(CustomerOrder.source_system == "ark", CustomerOrder.source_account_key == "local", local_binding))


def _dimension(column):
    return func.coalesce(func.nullif(func.trim(column), ""), "未知")


def load_roster(db):
    query = (select(SalesRoster, ArkUser).options(lazyload(ArkUser.roles))
        .join(ArkUser, ArkUser.id == SalesRoster.ark_user_id)
        .where(SalesRoster.active.is_(True), ArkUser.is_active.is_(True)).order_by(SalesRoster.ark_user_id))
    return [{"user_id": str(member.ark_user_id), "name": employee.real_name or employee.username,
        "user_name": employee.real_name or employee.username, "en_name": member.english_name,
        "team": member.team, "camp": member.camp, "target": member.new_customer_target,
        "amount_target": member.amount_target, "legacy_user_id": member.legacy_user_id}
        for member, employee in db.execute(query)]


def load_orders(db, *, user_id=None, owner_ids=None, team=None, date_from=None, date_to=None, filters=None, active_roster=False,
                historical_order_ids=None):
    owner = logical_owner_expression(CustomerOrder, "order")
    query = (select(CustomerOrder, CustomerAccount, ArkUser, SalesRoster, CustomerSourceRecord)
        .select_from(CustomerOrder)
        .options(lazyload(ArkUser.roles))
        .join(CustomerAccount, CustomerAccount.id == owner)
        .outerjoin(ArkUser, ArkUser.id == CustomerOrder.owner_user_id)
        .outerjoin(SalesRoster, SalesRoster.ark_user_id == CustomerOrder.owner_user_id)
        .outerjoin(CustomerSourceRecord, CustomerSourceRecord.id == CustomerOrder.source_record_id))
    if historical_order_ids is None:
        query = query.where(CustomerOrder.is_valid_business_order.is_(True), formal_order_predicate())
    else:
        # Exact identities already scoped by an immutable return fact. Used
        # only for dimension matching, never as countable sales or new GMV.
        query = query.where(CustomerOrder.id.in_(historical_order_ids))
    if user_id is not None:
        query = query.where(CustomerOrder.owner_user_id == int(user_id))
    if owner_ids is not None:
        query = query.where(CustomerOrder.owner_user_id.in_(owner_ids))
    if team:
        query = query.where(SalesRoster.team == team)
    if date_from is not None:
        query = query.where(CustomerOrder.account_date >= date_from)
    if date_to is not None:
        query = query.where(CustomerOrder.account_date <= date_to)
    if active_roster:
        query = query.where(SalesRoster.active.is_(True), ArkUser.is_active.is_(True))
    if filters and (filters.models or filters.colors):
        items = select(CustomerOrderItem.id).where(CustomerOrderItem.order_id == CustomerOrder.id,
            CustomerOrderItem.projection_role == 'active')
        if filters.models:
            items = items.where(_dimension(CustomerOrderItem.model).in_(filters.models))
        if filters.colors:
            items = items.where(_dimension(CustomerOrderItem.color).in_(filters.colors))
        query = query.where(items.exists())
    rows = []
    for order, customer, employee, roster, source in db.execute(query.order_by(CustomerOrder.account_date, CustomerOrder.id)):
        payload = source.payload_json if source else {}
        commercial = payload.get("commercial", {}) if isinstance(payload, dict) else {}
        country = (commercial["country"] if "country" in commercial else customer.primary_country_code) or "未知"
        category = order.source_category or "unknown"
        if filters and ((filters.countries and country not in filters.countries) or (filters.sources and category not in filters.sources)):
            continue
        rows.append({"order_key": f"ark:customer_order:{order.id}", "customer_key": f"ark:customer:{customer.id}",
            "event_order_id": order.external_order_id if order.source_system == "okki" else
                commercial.get("legacy_order_id") or f"ark:customer_order:{order.id}",
            "owner_key": f"ark:user:{order.owner_user_id}" if order.owner_user_id else None,
            "order_id": str(order.id), "order_no": order.order_no, "account_date": order.account_date,
            "source": "local" if order.local_invoice_id is not None else "legacy",
            "source_system": order.source_system,
            "amount_usd": order.amount_usd, "company_id": str(customer.id),
            "company_name": commercial.get("customer_name") or customer.display_name,
            "user_id": str(order.owner_user_id) if order.owner_user_id else "",
            "user_name": (employee.real_name or employee.username) if employee else "未归属",
            "team": roster.team if roster else "", "camp": roster.camp if roster else "",
            "new_deal": "是" if order.is_new_deal is True else "否" if order.is_new_deal is False else "",
            "first_return": "是" if order.is_first_return is True else "否" if order.is_first_return is False else "",
            "source_category": category, "source_raw": category, "origin_name": category,
            "departments": commercial.get("departments", []),
            "country": country, "country_name": country, "customer_nature": customer.relationship_stage})
    return rows


def load_product_rows(db, orders, filters=None):
    if not orders:
        return []
    by_id = {int(row["order_id"]): row for row in orders}
    rows = []
    query = select(CustomerOrderItem).where(CustomerOrderItem.order_id.in_(by_id), CustomerOrderItem.projection_role == 'active')
    if filters and filters.models:
        query = query.where(_dimension(CustomerOrderItem.model).in_(filters.models))
    if filters and filters.colors:
        query = query.where(_dimension(CustomerOrderItem.color).in_(filters.colors))
    for item in db.scalars(query.order_by(CustomerOrderItem.id)):
        order = by_id[item.order_id]
        rows.append({**order, "product_name": item.product_name, "product_model": item.model,
            "model": (item.model or "").strip() or "未知", "filter_model": (item.model or "").strip() or "未知",
            "color": (item.color or "").strip() or "未知", "size": (item.length or "").strip() or "未知",
            "quantity": float(item.quantity) if item.quantity is not None else 0})
    return rows
