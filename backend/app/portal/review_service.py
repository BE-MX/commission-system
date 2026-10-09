"""Employee review context, authorized independently from read-all order access.

Actions are UI hints only. Every command repeats authorization and validation.
No stock/price checks here: an unavailable mirror must not hide a prior receipt.
"""
from types import SimpleNamespace
from pydantic import ValidationError
from app.customer.models import CustomerAccount

from app.portal import admin_service, order_commands, order_queries, proposal_service, quote_service
from app.portal.errors import reject
from app.portal.schemas import SitePolicy


def context(db, actor_id, public_id):
    actor, site, access, order = proposal_service.managed_request(db, actor_id, public_id)
    admin_service.employee_principal(db, actor_id, "portal_order:read")
    detail = order_queries.detail_view(db, order, show_price=True)
    customer = db.get(CustomerAccount, access.customer_id, populate_existing=True)
    _, records = order_queries.load_revision(db, order)
    customer_view = {"customer_id": str(access.customer_id), "okki_company_id": access.okki_company_id,
                     "company_name": customer.canonical_company_name or customer.display_name,
                     "sales_user_id": str(access.sales_user_id)}
    standards = [{"line_key": line.line_key, "product_kind": line.product_kind,
                  "product_id": str(line.product_id), "sku_id": str(line.sku_id),
                  "standard": {key: line.standard_json.get(key) for key in
                               ("model", "color", "length", "weight", "product_display")}}
                 for line in records]

    line_item_ids = {line.catalog_item_id for line in records}
    quantity_rules = [{"item_id": item.public_id, "min_order_qty": item.min_qty, "step_qty": item.step_qty}
        for item in quote_service.catalog_service.authorized_items(db, SimpleNamespace(access=access, site=site))
        if item.id in line_item_ids]
    actions = []
    enabled = quote_service.get_settings().PORTAL_WRITES_ENABLED
    trading = site.status == "enabled" and access.status == "enabled" and access.can_order and access.can_view_price
    unconverted = order.status in {"submitted", "awaiting_customer", "ready_for_review"} and not order_commands.has_invoice_lineage(db, order)
    if enabled and unconverted:
        actions.append("reject")
        proposal = detail.get("proposal")
        if trading:
            if order.status != "awaiting_customer" or proposal and proposal["expired"]:
                actions.append("propose")
            if (order.status == "ready_for_review" and proposal and proposal["accepted"] and not proposal["expired"]
                    and quote_service.get_settings().PORTAL_INVOICE_ENABLED
                    and ("super_admin" in actor["roles"] or "invoice:write" in actor["permissions"])):
                actions.append("approve")
    try:
        policy = SitePolicy.model_validate(site.policy_json)
    except ValidationError:
        reject("POLICY_UNAVAILABLE", "站点交易政策需要复核。", 503)
    return {"order": detail, "customer": customer_view, "standard_lines": standards, "quantity_rules": quantity_rules, "available_actions": actions,
            "policy": {"payment_terms": [term.model_dump(mode="json") for term in policy.payment_terms],
                       "proposal_valid_hours": policy.proposal_valid_hours,
                       "default_payment_term_code": policy.default_payment_term_code}}
