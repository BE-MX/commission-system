"""Read-only, pre-send legacy inputs. Missing mappings never alter business."""
from decimal import Decimal
import json
from sqlalchemy import select


def _wire(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str), parse_float=str)


def _base(db, invoice, payload, actor_id, request_key):
    from app.commerce_shadow.hooks import _actor, source_reference
    from app.core.config import get_settings
    prior = _latest_contract(db, invoice)
    reference = {"$ref": prior.source_event_id, "field": "id"} if prior else source_reference(db, "invoice", invoice.id)
    return dict(request_key=request_key, actor=_actor(db, {"sub": str(actor_id)}),
        source_invoice_id=invoice.id, source_namespace="okki", tenant=get_settings().PORTAL_OKKI_NAMESPACE,
        source_contract_revision=prior.contract_revision if prior else None,
        customer_external_id=str(invoice.customer_id), contract_ref=reference,
        original_payload=_wire(payload))


def _latest_contract(db, invoice):
    from app.commerce_shadow.models import ShadowObservation
    return db.scalar(select(ShadowObservation).where(ShadowObservation.invoice_id == invoice.id,
        ShadowObservation.action == "legacy.order.push", ShadowObservation.outcome == "accepted")
        .order_by(ShadowObservation.contract_revision.desc(), ShadowObservation.id.desc()).limit(1))


def contract_history(db, invoice):
    """The before image is an immutable accepted original command, never UI state."""
    from app.commerce_shadow.hooks import enabled
    if not enabled(db):
        return {}
    prior = _latest_contract(db, invoice)
    if prior is None:
        return {}
    contract = prior.command.get("body", {}).get("contract", {})
    if not contract.get("items"):
        return {}
    return {"previous_source_item_ids": [item["source_item_id"] for item in contract["items"]],
        "previous_contract_ref": {"$ref": prior.source_event_id, "field": "id"}}


def receipt(db, invoice, row, payload):
    from app.commerce_shadow.hooks import enabled
    if not enabled(db):
        return None
    from app.commerce_transition.models import BankIdentity, BankAccountDomain
    from app.invoice.settlement_models import ReceiptBatch
    from app.finance.models import BankAccount
    raw = _base(db, invoice, payload, row.created_by, row.request_key)
    raw["receipt"] = {name: _wire(getattr(row, name)) for name in (
        "id", "batch_id", "purpose", "amount", "currency", "collection_date", "payment_type", "bank_charge")}
    reference = f"legacy-batch:{row.batch_id}" if row.batch_id else f"legacy-receipt:{row.id}"
    raw["bank_reference_key"] = reference
    batch = db.get(ReceiptBatch, row.batch_id) if row.batch_id else None
    raw["payment"] = dict(gross_amount=str(batch.gross_amount if batch else row.amount),
        actual_bank_fee=str(batch.actual_bank_fee if batch else row.bank_charge),
        currency=batch.currency if batch else row.currency,
        collection_date=(batch.collection_date if batch else row.collection_date).isoformat(),
        payment_type=batch.payment_type if batch else row.payment_type,
        rate_to_cny=str(batch.rate_to_cny) if batch and batch.rate_to_cny is not None else payload.get("exchange_rate"),
        rate_to_usd=str(batch.rate_to_usd) if batch and batch.rate_to_usd is not None else payload.get("exchange_rate_usd"))
    identities = list(db.scalars(select(BankIdentity).where(BankIdentity.route == "legacy", BankIdentity.payment_ref == reference)))
    identity = identities[0] if len(identities) == 1 else None
    if identity and (identity.payer_evidence or {}).get("bank_identity_verified"):
        domain = db.get(BankAccountDomain, identity.domain_id)
        accounts = db.scalars(select(BankAccount).where(BankAccount.id.in_(
            (domain.evidence or {}).get("bank_account_ids", [])), BankAccount.currency == row.currency)).all()
        if len(accounts) == 1:
            raw["bank"] = dict(subject_key=domain.subject_key, account_key=domain.account_key, channel=domain.channel,
                bank_account_code=accounts[0].code, transaction_id=identity.transaction_id,
                gross_amount=str(identity.amount), currency=identity.currency,
                statement_reference=(identity.payer_evidence or {}).get("statement_reference"))
    return raw


def outbound(db, invoice, payload, actor_id, *, request_key, operation="create", before=None):
    from app.commerce_shadow.hooks import enabled
    if not enabled(db):
        return None
    from app.core.time import beijing_today
    raw = _base(db, invoice, payload, actor_id, request_key)
    by_id = {str(item.xiaoman_unique_id): item for item in invoice.items if item.xiaoman_unique_id}
    items, missing = [], []
    for line in payload.get("record_list", []):
        if str(line.get("remove", 0)) == "1":
            continue
        item = by_id.get(str(line.get("order_record_id")))
        quantity = Decimal(str(line.get("outbound_count", 0)))
        if (item is None or str(item.product_id) != str(line.get("product_id"))
                or str(item.sku_id) != str(line.get("sku_id")) or quantity <= 0 or quantity != int(quantity)):
            missing.append("legacy_outbound_line_mapping_incomplete")
            continue
        items.append(dict(source_item_id=item.id, quantity=int(quantity)))
    before = before or {}
    raw["shipment"] = dict(operation=operation, business_date=beijing_today().isoformat(),
        currency=payload.get("currency") or before.get("currency"),
        external_warehouse_id=str(payload.get("invoice_warehouse_id") or (before.get("invoice_warehouse_info") or {}).get("id") or ""), items=items,
        source_outbound_id=str(payload.get("outbound_invoice_id") or ""))
    if operation == "update" and payload.get("outbound_invoice_id"):
        from app.commerce_transition.models import SendingClaim
        from app.commerce_shadow.models import ShadowObservation
        claims = list(db.scalars(select(SendingClaim.id).where(SendingClaim.invoice_id == invoice.id,
            SendingClaim.operation == "outbound_create", SendingClaim.external_id == str(payload["outbound_invoice_id"]))))
        ancestors = [observation for observation in db.scalars(select(ShadowObservation).where(
            ShadowObservation.invoice_id == invoice.id, ShadowObservation.action == "legacy.outbound.remote",
            ShadowObservation.outcome == "accepted")) if observation.result.get("original_claim_id") in claims]
        if len(ancestors) == 1:
            raw["shipment"]["target_ref"] = {"$ref": ancestors[0].source_event_id, "field": "id"}
    if missing or not items:
        raw["mapping_gaps"] = sorted(set(missing or ["legacy_outbound_items_missing"]))
    return raw
