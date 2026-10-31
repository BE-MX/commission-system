"""Explicit, network-free domain adapters. No generic API/HTTP fallback.

Only input is read here. Formal result evidence is deliberately not an argument.
Candidate row identities are private references, not compared to source IDs.
"""
from decimal import Decimal
from datetime import date, datetime
import hashlib
from sqlalchemy import select
from app.commerce_shadow.models import ShadowExecution


class UnsupportedCommand(ValueError):
    pass


def require_permissions(actor, *codes):
    """Match formal HTTP command authority using its frozen ORIGINAL actor."""
    from fastapi import HTTPException
    if "super_admin" in actor.get("roles", []):
        return
    if not actor.get("roles") or any(code not in actor.get("permissions", []) for code in codes):
        raise HTTPException(403, "原始操作人无权执行该候选命令")


def action_permissions(action):
    if action.startswith("contract."):
        return ("invoice:write",)
    if action == "shipment.create":
        return ("shipment:write", "invoice:write")
    if action == "shipment.dispatch":
        return ("shipment:write", "invoice:write", "inventory:write")
    if action.startswith("shipment."):
        return ("shipment:write",)
    if action in {"payment.confirm", "payment.refund", "allocation.reverse", "receivable.adjust", "receivable.terms"}:
        return ("receipt:admin",)
    return ("receipt:write",)


def _resolve(db, dataset_id, value, *, identity_map=None, key=None, action=None):
    if isinstance(value, dict) and "$ref" in value:
        if set(value) - {"$ref", "field"}:
            raise UnsupportedCommand("invalid_reference")
        row = db.scalar(select(ShadowExecution).where(ShadowExecution.dataset_id == dataset_id,
                                                     ShadowExecution.source_event_id == value["$ref"]))
        if row is None or row.outcome != "accepted":
            raise UnsupportedCommand("missing_candidate_reference")
        field = value.get("field", "id")
        identity = row.actual.get("identities", {}).get(field)
        if identity is None:
            raise UnsupportedCommand("missing_candidate_identity")
        return identity
    if isinstance(value, dict):
        return {name: _resolve(db, dataset_id, child, identity_map=identity_map, key=name, action=action)
                for name, child in value.items()}
    if isinstance(value, list):
        return [_resolve(db, dataset_id, child, identity_map=identity_map, key=key, action=action) for child in value]
    kinds = {"invoice_id": "invoice", "receivable_id": "receivable", "settlement_id": "shipment",
             "invoice_item_id": "invoice_item"}
    if key == "target_id":
        kinds[key] = ("invoice" if action.startswith("contract.") or action == "shipment.create" else
                      "payment" if action.startswith("payment.") or action == "allocation.create" else
                      "allocation" if action == "allocation.reverse" else "receivable" if action.startswith("receivable.") else "shipment")
    if key == "id" and action in {"contract.amend", "contract.update_draft"}:
        kinds[key] = "invoice_item"
    if key in kinds and value is not None:
        mapped = (identity_map or {}).get(f"{kinds[key]}:{value}")
        if not isinstance(mapped, int) or mapped < 1:
            raise UnsupportedCommand("unmapped_source_business_identity")
        return mapped
    return value


def execute(db, *, dataset_id, execution_event_id, action, command, actor_id, checkpoint=None):
    if command.get("unavailable_evidence"):
        raise UnsupportedCommand("unavailable_proof_or_media_validation")
    if action in {"legacy.order.push", "legacy.receipt.remote", "legacy.outbound.remote"}:
        from app.commerce_shadow.legacy_adapter import execute_order, execute_receipt, execute_outbound
        operation = {"legacy.order.push": execute_order, "legacy.receipt.remote": execute_receipt,
            "legacy.outbound.remote": execute_outbound}[action]
        return operation(db, dataset_id=dataset_id, command=command, actor_id=actor_id, checkpoint=checkpoint or {})
    from app.finance import service as finance
    from app.finance.schemas import PaymentCreate, FinanceAction, AllocationCreate, AdjustmentCreate, ReceivableTerms
    from app.invoice import commerce_service as commerce, local_fulfillment as shipments
    from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalInvoiceAction, LocalInvoiceAmend
    from app.invoice.local_fulfillment_schemas import LocalShipmentCreate, LocalShipmentAction, LocalShipmentQuote
    from app.invoice.settlement_models import Receivable

    supported = {"contract.create", "contract.confirm", "contract.cancel", "contract.update_draft", "contract.amend", "payment.register", "payment.confirm", "payment.void",
                 "payment.refund", "allocation.create", "allocation.reverse", "shipment.create", "shipment.ready",
                 "shipment.dispatch", "shipment.cancel", "shipment.release_funding", "receivable.adjust", "receivable.terms"}
    if action not in supported:
        raise UnsupportedCommand("unsupported_action")
    if command.get("unavailable_evidence"):
        raise UnsupportedCommand("unavailable_proof_or_media_validation")
    if set(command) - {"body", "target_id", "actor", "unavailable_evidence"} or not isinstance(command.get("body"), dict):
        raise UnsupportedCommand("unsupported_command_envelope")
    resolved = _resolve(db, dataset_id, command, identity_map=(checkpoint or {}).get("identity_map", {}), action=action)
    body = dict(resolved["body"])
    # Stable logical command identity across observed rejection/retry attempts.
    # Each delivery has its own execution UUID, but must not create a second
    # economic effect when the original source request key is retried later.
    original_key = body.get("request_key")
    if not isinstance(original_key, str) or not original_key:
        raise UnsupportedCommand("missing_original_request_identity")
    body["request_key"] = "shadow:" + hashlib.sha256((dataset_id + "\0" + original_key).encode()).hexdigest()[:56]
    actor = resolved.get("actor", {"sub": str(actor_id), "roles": [], "permissions": []})
    if set(actor) - {"sub", "roles", "permissions"} or str(actor.get("sub")) != str(actor_id):
        raise UnsupportedCommand("invalid_actor_snapshot")
    require_permissions(actor, *action_permissions(action))
    target = resolved.get("target_id")
    if action != "contract.create" and action != "payment.register" and not isinstance(target, int):
        raise UnsupportedCommand("missing_target_identity")
    if "expected_authority_epoch" in body:
        # Source epoch was checked against immutable observation metadata by
        # the worker. Candidate identities/epochs belong to its own database.
        if action == "contract.create":
            body["expected_authority_epoch"] = 1
        elif action.startswith(("contract.", "shipment.")):
            from app.commerce_transition.models import InvoiceAuthority
            from app.invoice.settlement_models import ShipmentSettlement
            invoice_id = target
            if action.startswith("shipment.") and action != "shipment.create":
                settlement = db.get(ShipmentSettlement, target)
                if settlement is None:
                    raise UnsupportedCommand("missing_candidate_settlement")
                invoice_id = settlement.invoice_id
            authority = db.get(InvoiceAuthority, invoice_id)
            if authority is None:
                raise UnsupportedCommand("missing_candidate_authority")
            body["expected_authority_epoch"] = authority.epoch
    if action == "contract.create":
        row = commerce.create_draft(db, LocalInvoiceDraft.model_validate(body), actor)
        from app.commerce_transition.service import ensure_authority
        ensure_authority(db, row, route="local", source_evidence={"dataset_id": dataset_id,
            "execution_event_id": execution_event_id}, confirmed=False)
    elif action in {"contract.confirm", "contract.cancel"}:
        row = getattr(commerce, action.split(".")[1])(db, target, LocalInvoiceAction.model_validate(body), actor)
    elif action == "contract.update_draft":
        row = commerce.update_draft(db, target, LocalInvoiceDraft.model_validate(body), actor)
    elif action == "contract.amend":
        row = commerce.amend(db, target, LocalInvoiceAmend.model_validate(body), actor)
    elif action == "payment.register":
        # Proof/media binding writes to shared uploads are unavailable in shadow.
        if body.get("attachment_ids"):
            raise UnsupportedCommand("media_binding_forbidden")
        row = finance.register(db, PaymentCreate.model_validate(body), actor)
    elif action in {"payment.confirm", "payment.refund", "payment.void", "allocation.reverse"}:
        operation = {"payment.confirm": finance.confirm, "payment.refund": finance.refund,
                     "payment.void": finance.void_registration, "allocation.reverse": finance.reverse_allocation}[action]
        row = operation(db, target, FinanceAction.model_validate(body), actor)
    elif action == "allocation.create":
        row = finance.allocate(db, target, AllocationCreate.model_validate(body), actor)
    elif action == "receivable.adjust":
        row = finance.adjust_receivable(db, target, AdjustmentCreate.model_validate(body), actor)
    elif action == "receivable.terms":
        row = finance.set_due_date(db, target, ReceivableTerms.model_validate(body), actor)
    elif action == "shipment.create":
        # The source hash contains source-local row identities. Compute the
        # candidate quote independently from original quantities, never install
        # the formal quote or use its hash to short-circuit a domain command.
        quote_body = {key: value for key, value in body.items()
                      if key not in {"request_key", "expected_version", "quote_hash"}}
        calculated = shipments.quote(db, target, LocalShipmentQuote.model_validate(quote_body), actor)
        body["quote_hash"] = calculated["quote_hash"]
        row = shipments.create(db, target, LocalShipmentCreate.model_validate(body), actor)
    else:
        operation = "ship" if action == "shipment.dispatch" else action.split(".")[1]
        row = shipments.act(db, target, LocalShipmentAction.model_validate(body), actor, operation)
    db.flush()
    return snapshot(db, action, row, checkpoint=checkpoint, check_invariants=True)


def snapshot(db, action, row, *, checkpoint=None, check_invariants=False):
    """Shared serialization only; each route computes its own domain result."""
    from app.invoice.settlement_models import Receivable
    from app.finance import service as finance
    identities = {"id": row.id}
    if action.startswith("contract."):
        metrics = {key: getattr(row, key) for key in ("commerce_status", "commerce_version", "currency",
                   "product_amount", "total_amount", "internal_received", "internal_balance")}
        metrics["lines"] = [{"quantity": item.quantity, "unit_price": _json(item.price_per_piece),
            "discount_amount": _json(item.discount_amount), "amount": _json(item.total_price)}
            for item in sorted(row.items, key=lambda item: item.sort_order)]
        target = db.scalar(select(Receivable).where(Receivable.invoice_id == row.id, Receivable.kind == "goods"))
        if target:
            identities["receivable_id"] = target.id
        for index, item in enumerate(sorted(row.items, key=lambda item: item.sort_order)):
            identities[f"item_{index}"] = item.id
    elif action.startswith("payment."):
        metrics = {key: getattr(row, key) for key in ("finance_status", "version", "currency", "gross_amount",
                   "actual_bank_fee", "net_amount", "allocated_amount", "refunded_amount", "rate_to_cny", "rate_to_usd")}
        metrics["available_amount"] = finance.available(row) if row.finance_status == "confirmed" else Decimal("0.00")
    elif action.startswith("allocation."):
        metrics = {key: getattr(row, key) for key in ("status", "version", "currency", "amount", "bank_charge",
                   "reversed_amount", "reversed_bank_charge")}
    elif action.startswith("receivable."):
        metrics = {key: getattr(row, key) for key in ("amount", "paid_amount", "adjustment_amount", "handling_amount", "currency", "version", "due_date")}
    elif action.startswith("shipment."):
        metrics = {"state": row.state, "version": row.version}
        metrics.update({key: row.quote[key] for key in ("goods_amount", "freight_amount", "packaging_amount",
            "handling_amount", "new_payment_due", "deposit_applied", "deposit_charge_applied", "is_final") if key in row.quote})
    else:
        metrics = {key: getattr(row, key) for key in ("status", "sync_status", "amount", "bank_charge", "currency", "collect_status", "version")
                   if hasattr(row, key)}
    result = {"metrics": _json(metrics), "identities": identities, "domain_type": action.split(".", 1)[0]}
    if check_invariants:
        result["invariants"] = verify_conservation(db, checkpoint=checkpoint)
    return result


def verify_conservation(db, *, checkpoint=None):
    """Independent balances/face checks; no reuse of the command calculators."""
    from app.inventory.models import StockBalance, StockLedger
    from app.invoice.settlement_models import ReceiptBatch, Receivable
    from app.receipt.models import Receipt
    errors = []
    receipts = list(db.scalars(select(Receipt).where(Receipt.source == "local")))
    for batch in db.scalars(select(ReceiptBatch).where(ReceiptBatch.transaction_mode == "local")):
        effective = sum((row.effective_amount for row in receipts if row.batch_id == batch.id), Decimal(0))
        if (effective != batch.allocated_amount or batch.gross_amount < batch.allocated_amount + batch.refunded_amount
                or min(batch.gross_amount, batch.allocated_amount, batch.refunded_amount, batch.actual_bank_fee) < 0):
            errors.append(f"payment:{batch.id}")
        if batch.net_amount != batch.gross_amount - batch.actual_bank_fee:
            errors.append(f"net_cash:{batch.id}")
    for target in db.scalars(select(Receivable)):
        effective = sum((row.effective_amount for row in receipts if row.receivable_id == target.id), Decimal(0))
        if effective != target.paid_amount or target.paid_amount < 0 or target.paid_amount > target.amount + target.adjustment_amount:
            errors.append(f"receivable:{target.id}")
    baseline = {(row["warehouse_id"], row["sku_id"], row.get("quality", "sellable")): row
                for row in (checkpoint or {}).get("initial_stock", [])}
    ledger = list(db.scalars(select(StockLedger)))
    balances = list(db.scalars(select(StockBalance)))
    for balance in balances:
        if balance.on_hand < balance.reserved or balance.reserved < 0 or balance.on_hand < 0:
            errors.append(f"stock:{balance.id}")
        key = (balance.warehouse_id, balance.sku_id, balance.quality)
        origin = baseline.get(key, {"on_hand": 0, "reserved": 0})
        movements = [row for row in ledger if (row.warehouse_id, row.sku_id, row.quality) == key]
        if (balance.on_hand != origin["on_hand"] + sum(row.on_hand_delta for row in movements)
                or balance.reserved != origin["reserved"] + sum(row.reserved_delta for row in movements)):
            errors.append(f"stock_ledger:{balance.id}")
    observed_keys = {(row.warehouse_id, row.sku_id, row.quality) for row in balances}
    if set(baseline) - observed_keys:
        errors.append("missing_initial_stock_balance")
    return {"passed": not errors, "errors": errors}


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json(child) for child in value]
    return value
