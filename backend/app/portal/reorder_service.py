"""Repeat a customer's product selection through fresh authoritative quote creation."""
from pydantic import ValidationError
from sqlalchemy import select

from app.portal import auth_service as auth, catalog_service, order_queries, quote_service, revision_comparison
from app.portal.errors import PortalError, reject
from app.portal.models import OrderRequest
from app.portal.schemas import QuoteInput


def create_quote(db, token, csrf, public_id, body):
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    principal.require("reorder")
    quote_service.require_writes()
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(public_id), OrderRequest.access_id == principal.access.id))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    revision, records = order_queries.load_revision(db, order)
    selected = {str(key) for key in body.line_keys} if body.line_keys is not None else {row.line_key for row in records}
    if not selected or selected - {row.line_key for row in records}:
        reject("INVALID_INPUT", "Select products from this order request.", 422)
    records = [row for row in records if row.line_key in selected]
    current = {item.id:item for item in catalog_service.authorized_items(db, principal)}
    unavailable = [{"line_key":row.line_key,"error_code":"PRODUCT_UNAVAILABLE"} for row in records if row.catalog_item_id not in current]
    if unavailable:
        raise PortalError("REORDER_CHANGED", "Some products are no longer available. Review your selection.", 409, issues=unavailable)
    try:
        request = QuoteInput.model_validate({"items":[{"item_id":current[row.catalog_item_id].public_id,"quantity":row.qty} for row in records],
            "delivery":revision.delivery_json, "customer_po":"", "remark":revision.remark})
    except ValidationError:
        reject("REORDER_CHANGED", "The previous delivery details need review. Start a new request from the catalog.", 409)
    result = quote_service.create(db, token, csrf, request)
    fresh = {line["item_id"]:line for line in result["items"]}
    after = {row.line_key:{key:fresh[current[row.catalog_item_id].public_id][key] for key in
        ("display_snapshot","quantity","unit_price","discount_amount","line_amount")} for row in records}
    for line in after.values():
        line["display_snapshot"] = {key:line["display_snapshot"].get(key) for key in revision_comparison.DISPLAY_KEYS}
    result["reorder"] = {"source_request_id":order.public_id,"source_revision_id":revision.public_id,
        "changes":revision_comparison.compare_lines({row.line_key:revision_comparison.line_view(row) for row in records},after)}
    return result
