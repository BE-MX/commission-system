"""Old document creation is a candidate batch, never proof of physical ship."""
from datetime import date
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.commerce_shadow.dispatcher import UnsupportedCommand
from app.commerce_shadow.legacy_adapter import _key, invoice_target


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_item_id: int = Field(gt=0)
    quantity: int = Field(strict=True, gt=0)


class ShipmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    business_date: date
    external_warehouse_id: str
    source_outbound_id: str = ""
    currency: str | None = None
    target_ref: dict | None = None
    items: list[Line] = Field(min_length=1)


def expected(raw):
    shipment = ShipmentInput.model_validate(raw["shipment"])
    if not shipment.currency:
        raise UnsupportedCommand("legacy_outbound_currency_missing")
    return {"metrics": {"document_created": True, "quantity_total": sum(item.quantity for item in shipment.items),
        "currency": shipment.currency, "lines": [item.model_dump() for item in sorted(
            shipment.items, key=lambda item: item.source_item_id)]},
        "identities": {}}


def execute(db, *, dataset_id, command, actor_id, checkpoint):
    from app.invoice import local_fulfillment as fulfillment
    from app.invoice.models import Invoice, InvoiceCommerceEvent
    from app.invoice.settlement_models import ShipmentSettlement, SettlementItem
    from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate, LocalShipmentAction
    from app.inventory.models import Warehouse
    from app.commerce_shadow.dispatcher import snapshot
    raw, actor = command["body"], command["actor"]
    if str(actor.get("sub")) != str(actor_id) or not actor.get("roles"):
        raise UnsupportedCommand("legacy_authorization_snapshot_missing")
    from app.commerce_shadow.dispatcher import require_permissions
    require_permissions(actor, "shipment:write", "invoice:write")
    if raw.get("mapping_gaps"):
        raise UnsupportedCommand(raw["mapping_gaps"][0])
    shipment = ShipmentInput.model_validate(raw["shipment"])
    if not shipment.currency:
        raise UnsupportedCommand("legacy_outbound_currency_missing")
    if shipment.operation not in {"create", "update"}:
        raise UnsupportedCommand("legacy_outbound_operation_not_supported")
    if shipment.operation == "update" and shipment.target_ref is None:
        raise UnsupportedCommand("legacy_existing_outbound_update_checkpoint_required")
    invoice_id, identities = invoice_target(db, dataset_id, raw["source_invoice_id"], checkpoint)
    if invoice_id is None:
        raise UnsupportedCommand("legacy_outbound_contract_checkpoint_missing")
    warehouse_key = ":".join((raw["source_namespace"], raw["tenant"], shipment.external_warehouse_id))
    mapping = checkpoint.get("legacy_warehouse_map", {}).get(warehouse_key)
    if not mapping or not mapping.get("review_reference"):
        raise UnsupportedCommand("legacy_warehouse_mapping_missing")
    warehouse = db.get(Warehouse, mapping.get("warehouse_id"))
    if warehouse is None or not warehouse.active:
        raise UnsupportedCommand("legacy_warehouse_mapping_inactive")
    items = []
    for item in shipment.items:
        target = identities.get(f"source_item:{item.source_item_id}") or identities.get(str(item.source_item_id))
        if target is None:
            raise UnsupportedCommand("legacy_outbound_stable_line_mapping_missing")
        items.append(dict(invoice_item_id=target, quantity=item.quantity))
    if len({item["invoice_item_id"] for item in items}) != len(items):
        raise UnsupportedCommand("legacy_outbound_duplicate_line_identity")
    key = _key(dataset_id, raw["request_key"], "shipment-create")
    prior = db.scalar(select(InvoiceCommerceEvent).where(InvoiceCommerceEvent.request_key == key))
    if prior:
        body = LocalShipmentCreate.model_validate(prior.payload["body"])
    else:
        if shipment.operation == "update":
            from app.commerce_shadow.dispatcher import _resolve
            old_id = _resolve(db, dataset_id, shipment.target_ref)
            old = db.get(ShipmentSettlement, old_id)
            if old is None or old.invoice_id != invoice_id:
                raise UnsupportedCommand("legacy_outbound_parent_mapping_mismatch")
            # The ordinary native flow releases the old unshipped batch before
            # recalculating it. The genuine cancel guard rejects shipped facts.
            fulfillment.act(db, old.id, LocalShipmentAction(
                request_key=_key(dataset_id, raw["request_key"], "shipment-replace-cancel"),
                expected_authority_epoch=1, expected_version=old.version, business_date=shipment.business_date,
                reason="Independent original outbound amendment input"), actor, "cancel")
        invoice = db.get(Invoice, invoice_id)
        quote = LocalShipmentQuote(expected_authority_epoch=1, items=items, warehouse_id=warehouse.id,
            business_date=shipment.business_date)
        calculated = fulfillment.quote(db, invoice_id, quote, actor)
        body = LocalShipmentCreate(**quote.model_dump(), request_key=key, expected_version=invoice.commerce_version,
            quote_hash=calculated["quote_hash"])
    row = fulfillment.create(db, invoice_id, body, actor)
    if row.state == "awaiting_payment":
        fulfillment.act(db, row.id, LocalShipmentAction(request_key=_key(dataset_id, raw["request_key"], "shipment-ready"),
            expected_authority_epoch=1, expected_version=row.version, business_date=shipment.business_date,
            reason="Independent original outbound input verification"), actor, "ready")
    result = snapshot(db, "shipment.ready", row, checkpoint=checkpoint, check_invariants=True)
    actual = list(db.scalars(select(SettlementItem).where(SettlementItem.settlement_id == row.id)))
    source_ids = {line["invoice_item_id"]: original.source_item_id for line, original in zip(items, shipment.items)}
    lines = sorted([dict(source_item_id=source_ids.get(item.invoice_item_id), quantity=item.quantity) for item in actual],
        key=lambda item: item["source_item_id"] or 0)
    result["metrics"].update(document_created=True, quantity_total=sum(item.quantity for item in actual),
        physical_dispatch=False, currency=db.get(Invoice, invoice_id).currency, lines=lines)
    result["adapter"] = "legacy.outbound.remote"
    return result
