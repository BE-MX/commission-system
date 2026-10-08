"""Read-only employee PI review with both current customer and invoice-owner scope.

No invoice creation or inventory reads. Action hints never replace command checks.
"""
from copy import deepcopy
from pydantic import ValidationError
from sqlalchemy import select

from app.core.time import beijing_now
from app.customer.models import CustomerAccount
from app.invoice.models import InvoiceItem
from app.portal import admin_service, order_queries, pi_presentation, pi_void_service, quote_service, revision_evidence
from app.portal.errors import PortalError, reject
from app.portal.domain import content_hash
from app.portal.models import PiAmendment, Publication, Revision
from app.portal.schemas import SitePolicy


def live_document(invoice, items):
    return {"commercial_header": pi_presentation.capture(invoice), "currency": invoice.currency,
            "product_amount": revision_evidence.fixed(invoice.product_amount),
            "total_amount": revision_evidence.fixed(invoice.total_amount),
            "fees": {"shipping_amount": revision_evidence.fixed(invoice.shipping_fee),
                     "packaging_amount": revision_evidence.fixed(invoice.internal_accessory),
                     "surcharge_amount": revision_evidence.fixed(invoice.surcharge_amount),
                     "surcharge_name": invoice.surcharge_name or ""},
            "payment_terms_snapshot": {"display_text": invoice.payment_term},
            "delivery": {"contact_name": invoice.contact_name, "phone": invoice.contact_phone,
                         "formatted_address": invoice.delivery_address}, "remark": invoice.remark or "",
            "items": [{"line_key": "invoice-item:" + str(row.id),
                       "product_id": str(row.product_id) if row.product_id is not None else None,
                       "sku_id": str(row.sku_id) if row.sku_id is not None else None,
                       "display_snapshot": {"model_name": row.product_display or row.model,
                                            "color_name": row.color, "length": row.length,
                                            "weight": row.net_weight_grams, "unit": ""},
                       "quantity": row.quantity, "unit_price": revision_evidence.fixed(row.price_per_piece, 4),
                       "discount_amount": revision_evidence.fixed(row.discount_amount),
                       "line_amount": revision_evidence.fixed(row.total_price)} for row in items]}


def context(db, actor_id, public_id):
    access, order, conversion, invoice = pi_void_service.context(db, actor_id, public_id)
    admin_service.employee_principal(db, actor_id, "portal_order:read")
    site = admin_service.site_for_admin(db)
    items = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
                      .order_by(InvoiceItem.sort_order, InvoiceItem.id).with_for_update()
                      .execution_options(populate_existing=True)).all()
    amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id)
                          .execution_options(populate_existing=True))
    customer = db.get(CustomerAccount, access.customer_id, populate_existing=True)
    published = order_queries.detail_view(db, order, show_price=True)
    publication = db.scalar(select(Publication).where(Publication.request_id == order.id,
        Publication.invoice_id == invoice.id).order_by(Publication.invoice_document_version.desc()).limit(1)
        .execution_options(populate_existing=True))
    snapshot = {} if publication is None else deepcopy(publication.customer_snapshot_json)
    expected_hash = snapshot.pop("snapshot_hash", None)
    if not expected_hash or content_hash(snapshot) != expected_hash:
        reject("PI_REVISION_PENDING", "最近发布的 PI 证据需要复核。", 409)
    published["commercial_header"] = pi_presentation.project(snapshot.get("commercial_header", {}))
    published["invoice_document_version"] = publication.invoice_document_version
    pi = published.get("pi_amendment") or {"status": "unavailable", "proposal": None}
    actions, reasons = [], []
    policy = None
    try:
        policy = SitePolicy.model_validate(site.policy_json)
    except ValidationError:
        reasons.append({"code": "POLICY_UNAVAILABLE", "message": "交易政策需要复核，当前不能发送或发布 PI 修改。"})
    enabled = quote_service.get_settings().PORTAL_WRITES_ENABLED
    trading = site.status == "enabled" and access.status == "enabled" and access.can_order and access.can_view_price
    if enabled and conversion.status == "created":
        try:
            pi_void_service.require_local_idle(db, invoice)
        except PortalError as error:
            if error.code != "PI_VOID_REQUIRES_REVIEW":
                raise
            reasons.append({"code": error.code, "message": error.message})
        else:
            actions.append("void_pi")
        if trading and policy is not None and amendment is not None and invoice.status not in {"cancelled", "cancel_pending"}:
            prior = db.get(Revision, amendment.active_revision_id) if amendment.active_revision_id else None
            expired = prior is not None and prior.expires_at is not None and prior.expires_at <= beijing_now()
            if amendment.status == "withdrawn" or amendment.status in {"pending_customer", "accepted"} and expired:
                actions.append("propose_pi")
            proposal = pi.get("proposal")
            if (pi["status"] == "accepted" and proposal and not proposal["expired"] and not expired
                    and amendment.accepted_revision_id == amendment.active_revision_id):
                actions.append("publish_pi")
    return {"request_id": order.public_id, "request_no": order.public_no, "row_version": order.row_version,
            "invoice_id": str(invoice.id), "invoice_document_version": invoice.portal_document_version,
            "invoice_status": invoice.status, "amendment_status": pi["status"],
            "customer": {"company_name": customer.canonical_company_name or customer.display_name,
                         "customer_id": str(access.customer_id), "okki_company_id": access.okki_company_id,
                         "sales_user_id": str(access.sales_user_id), "invoice_sales_user_id": str(invoice.sales_user_id)},
            "current_invoice": live_document(invoice, items), "last_published": published,
            "proposal": pi.get("proposal"), "available_actions": actions, "blocked_reasons": reasons,
            "policy": {"proposal_valid_hours": policy.proposal_valid_hours if policy else []}}
