"""Read-only, page-scoped display of confirmed receipts in the invoice currency."""

import logging
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import detail_access, detail_receipt_snapshot
from app.invoice.screenshot_source import matched_order_id
from app.models.business import OkkiReceipt
from app.receipt import access, remote
from app.receipt.models import Receipt
from app.sales_return.models import ReturnEffect, ReturnReceipt


logger = logging.getLogger(__name__)


def amounts(db, invoices, user):
    if not invoices or not user or not detail_access.allowed(user, "receipt"):
        return {}
    all_access = access.all_access(user)
    if not all_access:
        owner = access.user_id(user)
        invoices = [inv for inv in invoices if inv.sales_user_id == owner]
    if not invoices:
        return {}

    # Preserve the detail panel's mixed-owner batch boundary even for an aggregate.
    ids = [inv.id for inv in invoices]
    query = db.query(Receipt).filter(Receipt.invoice_id.in_(ids))
    if not all_access:
        counts = dict(query.with_entities(Receipt.invoice_id, func.count()).group_by(Receipt.invoice_id))
        visible = dict(detail_access.receipt_query(db, user).filter(Receipt.invoice_id.in_(ids))
                       .with_entities(Receipt.invoice_id, func.count()).group_by(Receipt.invoice_id))
        invoices = [inv for inv in invoices if counts.get(inv.id, 0) == visible.get(inv.id, 0)]

    result = {inv.id: (inv.internal_received, inv.total_amount)
              for inv in invoices if inv.transaction_mode == "local"}
    # A matched screenshot order can already have receipts before Ark has a sync binding.
    legacy = [
        inv for inv in invoices
        if inv.transaction_mode != "local" and (
            inv.xiaoman_order_id or (
                inv.sync_status not in ("sync_uncertain", "synced")
                and not matched_order_id(inv.source_type, inv.source_order_id)
            )
        )
    ]
    if not legacy:
        return result

    order_ids = {str(inv.xiaoman_order_id) for inv in legacy if inv.xiaoman_order_id}
    remote_by_order = {}
    if order_ids:
        try:
            remote_by_order = detail_receipt_snapshot.page_orders(db, order_ids)
        except ValueError:
            # Missing or expired coverage is unknown, including when no receipt is recorded locally.
            legacy = [inv for inv in legacy if not inv.xiaoman_order_id]
            order_ids.clear()
    if not legacy:
        return result

    refunds = _adjustments(db, ReturnReceipt, ReturnReceipt.amount, order_ids)
    payable_changes = _adjustments(db, ReturnEffect, ReturnEffect.amount + ReturnEffect.freight_amount, order_ids)

    local_by_invoice = defaultdict(list)
    local = query.filter(Receipt.invoice_id.in_([inv.id for inv in legacy]), Receipt.purpose != "freight")
    for receipt in local.with_entities(Receipt.invoice_id, Receipt.customer_id, Receipt.currency,
                                       Receipt.xiaoman_order_id, Receipt.xiaoman_receipt_id,
                                       Receipt.status, Receipt.sync_status, Receipt.send_phase,
                                       Receipt.amount, Receipt.bank_charge):
        local_by_invoice[receipt.invoice_id].append(receipt)

    # For remote-only receipts, require customer identity and no competing
    # Ark binding anywhere, including outside the current page or reader scope.
    unmapped = set()
    for inv in legacy:
        if inv.order_type != "presale":
            bound = {row.xiaoman_receipt_id for row in local_by_invoice[inv.id]}
            unmapped.update(str(row["cash_collection_id"])
                            for row in remote_by_order.get(str(inv.xiaoman_order_id), ())
                            if str(row["cash_collection_id"]) not in bound)
    identities = _external_identities(db, unmapped)

    for invoice in legacy:
        key = str(invoice.xiaoman_order_id)
        refund, payable_change = refunds.get(key, {}), payable_changes.get(key, {})
        party = (invoice.customer_id, invoice.currency)
        if (refund.keys() | payable_change.keys()) - {party}:
            continue
        paid = _confirmed_amount(invoice, remote_by_order.get(key, ()), local_by_invoice[invoice.id], identities)
        if paid is not None:
            result[invoice.id] = (paid + refund.get(party, Decimal(0)),
                                  invoice.total_amount + payable_change.get(party, Decimal(0)))
    return result


def _adjustments(db, model, amount, order_ids):
    groups = defaultdict(dict)
    if order_ids:
        for order_id, customer_id, currency, total in (
            db.query(model.order_id, model.customer_id, model.currency, func.sum(amount))
            .filter(model.order_id.in_(order_ids))
            .group_by(model.order_id, model.customer_id, model.currency)
        ):
            groups[order_id][(customer_id, currency)] = total
    return groups


def _external_identities(db, unmapped):
    if not unmapped:
        return {}
    claimed = set(db.scalars(db.query(Receipt.xiaoman_receipt_id)
                             .filter(Receipt.xiaoman_receipt_id.in_(unmapped)).statement))
    external = unmapped - claimed
    if not external:
        return {}
    try:
        return {identity: (order_id, company_id) for identity, order_id, company_id in
                db.query(OkkiReceipt.cash_collection_id, OkkiReceipt.order_id, OkkiReceipt.company_id)
                  .filter(OkkiReceipt.cash_collection_id.in_(external))}
    except SQLAlchemyError as exc:
        logger.warning("Invoice list receipt mirror unavailable: %s", type(exc).__name__)
        print(f"[invoice_list] receipt mirror unavailable: {type(exc).__name__}", flush=True)
        return {}


def _confirmed_amount(invoice, rows, local, identities):
    by_id = {}
    paid = Decimal(0)
    for row in rows:
        identity = str(row["cash_collection_id"] or "")
        status = str(row["collect_status"])
        if not identity or identity in by_id or row["currency"] != invoice.currency or status not in ("0", "1"):
            return None
        try:
            amount = remote.money(row["amount"])
        except ValueError:
            return None
        by_id[identity] = (amount, status)
        if status == "1":
            paid += amount

    mapped = set()
    for row in local:
        identity = row.xiaoman_receipt_id
        if row.status != "active":
            if identity in by_id:
                return None
            continue
        # An uncertain POST may already be recorded in OKKI even without a remote ID.
        if row.sync_status == "uncertain" or (
            row.sync_status == "syncing" and row.send_phase in ("sending", None)
        ):
            return None
        if (row.customer_id != invoice.customer_id or row.currency != invoice.currency
                or (identity and row.xiaoman_order_id != invoice.xiaoman_order_id)):
            return None
        if identity:
            match = by_id.get(identity)
            if not match:
                return None
            try:
                if match[0] != remote.net_amount(row):
                    return None
            except ValueError:
                return None
            mapped.add(identity)
            if match[1] == "1":
                paid += row.bank_charge
    unmatched = set(by_id) - mapped
    if unmatched and (invoice.order_type == "presale" or any(
            identities.get(identity) != (invoice.xiaoman_order_id, invoice.customer_id)
            for identity in unmatched)):
        return None
    return paid
