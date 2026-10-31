"""Formal command observation adapters; economic transactions stay caller-owned.

Rejected/unknown attempts are staged in Session.info and are written only AFTER
the controller rolled back the failed economic transaction. No network is used.
"""
import functools
import hashlib
import inspect
import json
from uuid import uuid4
from sqlalchemy import select
from fastapi import HTTPException
from app.core.config import get_settings
from app.commerce_shadow import service
from app.commerce_shadow.models import ShadowObservation
from app.commerce_shadow.diagnostics import report

PENDING = "commerce_shadow_pending_failures"
DEPTH = "commerce_shadow_command_depth"


def enabled(db):
    settings = get_settings()
    return (settings.COMMERCE_SHADOW_ENABLED and not settings.COMMERCE_SHADOW_EXECUTION_ONLY
            and not db.info.get("commerce_shadow_execution_only"))


def _body(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value or {})


def _input_digest(action, body, actor):
    return hashlib.sha256(json.dumps([action, body, actor], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()


def _actor(db, user):
    from app.auth.service import get_live_user_authorization
    identity = int(user["sub"])
    roles, permissions = get_live_user_authorization(db, identity)
    if not roles:
        return None
    return {"sub": str(identity), "roles": roles, "permissions": permissions}


def source_reference(db, kind, identity):
    """Resolve an ACTUAL original source identity, never infer from equal IDs."""
    if identity is None:
        return None
    prefixes = {"invoice": ("contract.", "legacy.order.push"), "invoice_item": ("contract.", "legacy.order.push"),
        "receivable": ("contract.", "shipment."), "payment": ("payment.",),
        "allocation": ("allocation.",), "shipment": ("shipment.",)}[kind]
    for row in db.scalars(select(ShadowObservation).where(ShadowObservation.outcome == "accepted")
                          .order_by(ShadowObservation.id.desc())):
        if not row.action.startswith(prefixes):
            continue
        identities = row.result.get("identities", {})
        names = [name for name in identities if name.startswith("item_")] if kind == "invoice_item" else (
            ["receivable_id", "freight_receivable_id"] if kind == "receivable" else ["id"])
        for name in names:
            if identities.get(name) == identity:
                return {"$ref": row.source_event_id, "field": name}
    # Explicitly unmapped. The candidate dispatcher blocks unless a verified
    # checkpoint identity_map provides this exact source identity.
    return identity


def _metadata(db, action, target_id=None, invoice_id=None, body=None, result=None):
    from app.invoice.models import Invoice
    from app.invoice.settlement_models import ReceiptBatch, ShipmentSettlement
    from app.receipt.models import Receipt
    body = body or {}
    invoice_id = invoice_id or body.get("invoice_id")
    payment_id = None
    customer_id = body.get("local_customer_id")
    row = result[0] if isinstance(result, tuple) else result
    if action.startswith("contract."):
        invoice_id = getattr(row, "id", None) or invoice_id or target_id
    elif action.startswith("payment."):
        payment_id = getattr(row, "id", None) or target_id
    elif action.startswith("allocation."):
        allocation = row if row is not None else db.get(Receipt, target_id) if target_id and action.endswith("reverse") else None
        payment_id = getattr(allocation, "batch_id", None) or (target_id if action.endswith("create") else None)
        invoice_id = invoice_id or getattr(allocation, "invoice_id", None)
    elif action.startswith("shipment."):
        shipment = row if row is not None else db.get(ShipmentSettlement, target_id) if target_id and action != "shipment.create" else None
        invoice_id = invoice_id or getattr(shipment, "invoice_id", None) or (target_id if action == "shipment.create" else None)
    elif action.startswith("receivable."):
        invoice_id = invoice_id or getattr(row, "invoice_id", None)
    elif action.startswith("legacy.receipt."):
        if row is None and target_id:
            row = db.get(Receipt, target_id)
        invoice_id = invoice_id or getattr(row, "invoice_id", None)
    invoice = db.get(Invoice, invoice_id) if invoice_id else None
    payment = db.get(ReceiptBatch, payment_id) if payment_id else None
    customer_id = customer_id or getattr(payment, "local_customer_id", None) or getattr(invoice, "local_customer_id", None)
    from app.commerce_transition.models import InvoiceAuthority
    authority = db.get(InvoiceAuthority, invoice_id) if invoice_id else None
    return {"invoice_id": invoice_id, "payment_id": payment_id, "local_customer_id": customer_id,
        "authority_epoch": getattr(authority, "epoch", None) or body.get("expected_authority_epoch") or 1,
        "contract_revision": max(1, getattr(invoice, "commerce_version", 0)) if invoice else 0,
        "aggregate_key": f"invoice:{invoice_id}" if invoice_id else f"payment:{payment_id}" if payment_id else None}


def _command(db, action, raw, actor, target_id=None):
    body = json.loads(json.dumps(raw, default=str))
    unavailable = []
    for field in ("attachment_ids", "photos", "videos"):
        if body.get(field):
            unavailable.append(field)
            body[field] = []
    for key, kind in (("invoice_id", "invoice"), ("receivable_id", "receivable"), ("settlement_id", "shipment")):
        if body.get(key):
            body[key] = source_reference(db, kind, body[key])
    for item in body.get("items", []):
        field = "invoice_item_id" if "invoice_item_id" in item else "id"
        if item.get(field):
            item[field] = source_reference(db, "invoice_item", item[field])
    command = {"body": body, "actor": actor}
    if target_id is not None:
        kind = ("invoice" if action.startswith("contract.") or action == "shipment.create" else "payment"
                if action.startswith("payment.") or action == "allocation.create" else "allocation"
                if action == "allocation.reverse" else "receivable" if action.startswith("receivable.") else "shipment")
        command["target_id"] = target_id if action.startswith("legacy.") else source_reference(db, kind, target_id)
    if unavailable:
        command["unavailable_evidence"] = unavailable
    return command


def _sequence(db, aggregate):
    previous = db.scalar(select(ShadowObservation.causal_version).where(ShadowObservation.aggregate_key == aggregate)
        .order_by(ShadowObservation.causal_version.desc()).limit(1).with_for_update())
    return (previous or 0) + 1


def accepted(db, *, action, body, user, result, target_id=None, invoice_id=None, context=None):
    if not enabled(db):
        return None
    raw = _body(body)
    actor = (context or {}).get("actor") or _actor(db, user)
    if actor is None:
        # Unauthorized raw bodies must not be exported. The caller's authority
        # layer is responsible for rejecting; this sample is not called covered.
        return None
    raw_hash = _input_digest(action, {"body": raw, "target_id": target_id, "invoice_id": invoice_id}, int(actor["sub"]))
    source_id = "formal:" + raw_hash
    prior = db.scalar(select(ShadowObservation).where(ShadowObservation.source_event_id == source_id).with_for_update()
                      .execution_options(populate_existing=True))
    if prior:
        if prior.result.get("input_digest") != raw_hash:
            raise ValueError("正式命令身份已用于其他输入")
        return prior
    metadata = _metadata(db, action, target_id, invoice_id, raw, result)
    aggregate = metadata.pop("aggregate_key") or "request:" + raw_hash
    from app.commerce_shadow.dispatcher import snapshot
    evidence = snapshot(db, action, result[0] if isinstance(result, tuple) else result)
    evidence["input_digest"] = raw_hash
    command = (context or {}).get("command") or _command(db, action, raw, actor, target_id)
    return service.record_observation(db, source_event_id=source_id, action=action, request_key="formal:" + raw_hash,
        command=command, outcome="accepted", result=evidence, causal_version=_sequence(db, aggregate),
        dependencies=[], actor_id=int(actor["sub"]), aggregate_key=aggregate, **metadata)


def stage_failure(db, *, action, body, user, error, target_id=None, invoice_id=None, context=None, outcome=None):
    if not enabled(db):
        return
    raw = _body(body)
    context = dict(context or {})
    context.update(action=action, raw=raw, user={"sub": user["sub"]}, target_id=target_id, invoice_id=invoice_id,
        outcome=outcome or ("rejected" if isinstance(error, (ValueError, HTTPException)) else "unknown"),
        reason_code=str(error.detail) if isinstance(error, HTTPException) else str(error) if isinstance(error, ValueError) else type(error).__name__)
    db.info.setdefault(PENDING, []).append(context)


def record_after_rollback(db, error=None):
    pending = db.info.pop(PENDING, [])
    if not pending or not enabled(db):
        return
    if db.in_transaction():
        raise ValueError("失败观察只能在经济事务完整rollback后保存")
    try:
        from app.commerce_transition.service import lock_policy
        lock_policy(db)
        for context in pending:
            actor = context.get("actor") or _actor(db, context["user"])
            if actor is None:
                continue
            metadata = dict(context.get("metadata") or _metadata(db, context["action"], context["target_id"],
                context["invoice_id"], context["raw"]))
            # Check CURRENT scope before retaining even a minimized rejected input.
            probe = type("Scope", (), {**metadata, "action": context["action"]})()
            scope_actor = {**actor, "permissions": list(actor["permissions"])}
            for domain in ("invoice", "receipt"):
                if any(f"{domain}:{verb}" in actor["permissions"] for verb in ("write", "admin")):
                    scope_actor["permissions"].append(f"{domain}:read")
            try:
                service.observation_access(db, probe, scope_actor)
            except HTTPException:
                continue
            command = context.get("command") or _command(db, context["action"], context["raw"], actor, context["target_id"])
            attempt = uuid4().hex
            aggregate = metadata.pop("aggregate_key", None) or "request:" + _input_digest(context["action"], context["raw"], int(actor["sub"]))
            service.record_observation(db, source_event_id="diagnostic:" + attempt, action=context["action"],
                request_key="diagnostic:" + attempt, command=command, outcome=context["outcome"], result={},
                causal_version=_sequence(db, aggregate), dependencies=[], actor_id=int(actor["sub"]),
                aggregate_key=aggregate, reason_code=context["reason_code"][:160], **metadata)
        db.commit()
    except Exception as exc:
        db.rollback()
        report("failure_observation_unavailable", exc)
        raise


def observe_command(action, *, target_arg=None, invoice_arg=None):
    def decorate(function):
        signature = inspect.signature(function)
        @functools.wraps(function)
        def invoke(*args, **kwargs):
            values = signature.bind(*args, **kwargs).arguments
            resolved_action = action(values) if callable(action) else action
            db, body, user = values["db"], values["body"], values["user"]
            if not enabled(db):
                return function(*args, **kwargs)
            if db.info.get(DEPTH):
                # Compound commands (amend/cancel/dispatch) replay their own
                # internal finance/stock commands. Observing those again would
                # apply the same adjustment twice in the independent candidate.
                return function(*args, **kwargs)
            target = values.get(target_arg) if target_arg else None
            invoice = (getattr(body, "invoice_id", None) if invoice_arg == "body.invoice_id" else values.get(invoice_arg)) if invoice_arg else None
            # Do not read ANY database row before formal authorization/barriers.
            # In particular receipt/main invoice freshness guards must see an
            # untouched transaction when the business command starts.
            context = {}
            db.info[DEPTH] = 1
            try:
                result = function(*args, **kwargs)
                accepted(db, action=resolved_action, body=body, user=user, result=result, target_id=target, invoice_id=invoice, context=context)
                return result
            except Exception as exc:
                stage_failure(db, action=resolved_action, body=body, user=user, error=exc, target_id=target, invoice_id=invoice, context=context)
                raise
            finally:
                db.info.pop(DEPTH, None)
        return invoke
    return decorate


def external_result(db, *, claim, action, outcome, result_row, actor_id, evidence_ref, command_input=None):
    """Legacy writer AFTER original ledger result, same caller transaction.

Provider acceptance alone is not a posted receipt. Call with outcome=unknown
until the original ledger has its confirmed remote identity/status. This API
does not send, commit, normalize missing bank/SKU identity or fabricate a local
contract; legacy-only envelopes remain explicitly blocked in the candidate.
"""
    if not enabled(db):
        return None
    if outcome not in {"accepted", "rejected", "unknown"} or not actor_id or actor_id < 1:
        raise ValueError("外部观察需明确原操作人及结果")
    from app.invoice.models import Invoice
    from app.receipt.models import Receipt
    expected_operation = {"legacy.order.push": "order_push", "legacy.receipt.remote": "receipt_push"}.get(action)
    if expected_operation and claim.operation != expected_operation:
        raise ValueError("原发送代次与观察动作不匹配")
    invoice = db.get(Invoice, claim.invoice_id)
    if outcome == "accepted":
        if isinstance(result_row, Receipt):
            if (result_row.invoice_id != claim.invoice_id or result_row.sync_status != "synced"
                    or result_row.collect_status != 1 or not result_row.xiaoman_receipt_id):
                raise ValueError("远端接收不能代替原回款正式生效凭证")
        elif isinstance(result_row, Invoice):
            if result_row.id != claim.invoice_id or result_row.sync_status != "synced" or not result_row.xiaoman_order_id:
                raise ValueError("远端接收不能代替原订单正式凭证")
        elif action == "legacy.outbound.remote":
            from app.commerce_transition.models import ClaimEvidence
            readbacks = db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id,
                ClaimEvidence.outcome == "succeeded")).all()
            complete = (getattr(result_row, "status", None) == "done"
                or getattr(result_row, "action", None) == "sync_done")
            parent = getattr(result_row, "invoice_id", None)
            parent_matches = parent == claim.invoice_id if parent is not None else bool(
                (claim.responsibilities or {}).get("outbound_record_id") and str(getattr(result_row, "outbound_record_id", ""))
                == str(claim.responsibilities["outbound_record_id"]))
            if (claim.operation not in {"outbound_create", "outbound_update", "shipment_outbound_create"}
                    or not parent_matches or not complete or not claim.external_id
                    or not any((proof.evidence or {}).get("original_readback_hash") for proof in readbacks)):
                raise ValueError("原出库必须有正式任务及独立核验的远端ID")
        else:
            raise ValueError("accepted需实际正式账本对象，不能使用HTTP响应或对比结果")
    raw = dict(command_input or {"request_key": claim.request_key,
        "invoice_id": claim.invoice_id, "source_payload_hash": claim.payload_hash})
    if "original_payload" in raw:
        # Legacy provider serializers already produced JSON numeric floats.
        # Preserve their exact JSON decimal representation as strings; never
        # feed binary floats into the independent financial calculator.
        raw["original_payload"] = json.loads(json.dumps(raw["original_payload"], ensure_ascii=False,
            allow_nan=False), parse_float=str)
    raw.setdefault("request_key", claim.request_key)
    frozen_actor = raw.get("actor") or {"sub": str(actor_id), "roles": [], "permissions": []}
    if str(frozen_actor.get("sub")) != str(actor_id):
        raise ValueError("原外部输入授权人不匹配")
    command = {"body": raw, "actor": frozen_actor}
    supported_input = ((action == "legacy.order.push" and raw.get("contract"))
        or (action == "legacy.receipt.remote" and raw.get("receipt") and raw.get("payment"))
        or (action == "legacy.outbound.remote" and raw.get("shipment")))
    if not supported_input:
        command["unavailable_evidence"] = ["legacy_bank_catalog_mapping"]
    if action in {"legacy.receipt.remote", "legacy.outbound.remote"} and supported_input and not raw.get("source_contract_revision"):
        command["unavailable_evidence"] = sorted(set(command.get("unavailable_evidence", []) + ["legacy_source_order_generation_missing"]))
    base = "external:" + service.digest([claim.id, action, claim.request_key, claim.payload_hash])
    unknown = db.scalar(select(ShadowObservation).where(ShadowObservation.source_event_id == base + ":unknown"))
    from app.commerce_shadow.dispatcher import snapshot
    result = snapshot(db, action, result_row) if result_row is not None else {"metrics": {"formal_result": "unknown"}, "identities": {}}
    if action == "legacy.order.push" and outcome == "accepted" and raw.get("contract"):
        from app.commerce_shadow.legacy_adapter import expected_order
        from pydantic import ValidationError
        from app.commerce_shadow.dispatcher import UnsupportedCommand
        try:
            result = expected_order(raw)
        except (ValidationError, UnsupportedCommand) as failure:
            report("legacy_contract_input_incomplete", failure)
            command["unavailable_evidence"] = ["legacy_contract_input_incomplete"]
    elif action == "legacy.receipt.remote" and outcome == "accepted" and raw.get("receipt"):
        from app.commerce_shadow.legacy_adapter import expected_receipt
        from pydantic import ValidationError
        from app.commerce_shadow.dispatcher import UnsupportedCommand
        try:
            result = expected_receipt(raw)
        except (ValidationError, UnsupportedCommand) as failure:
            report("legacy_receipt_input_incomplete", failure)
            command["unavailable_evidence"] = ["legacy_receipt_input_incomplete"]
    elif action == "legacy.outbound.remote" and outcome == "accepted" and raw.get("shipment"):
        from app.commerce_shadow.legacy_adapter import expected_outbound
        from pydantic import ValidationError
        from app.commerce_shadow.dispatcher import UnsupportedCommand
        try:
            result = expected_outbound(raw)
        except (ValidationError, UnsupportedCommand) as failure:
            report("legacy_outbound_input_incomplete", failure)
            command["unavailable_evidence"] = ["legacy_outbound_input_incomplete"]
    result["original_claim_id"] = claim.id
    if unknown and outcome != "unknown":
        return service.resolve_observation(db, unknown_source_event_id=unknown.source_event_id, outcome=outcome,
            result=result, evidence_ref={"terminal_readback_ref": evidence_ref}, actor_id=actor_id)
    source_id = base + ":" + outcome
    prior = db.scalar(select(ShadowObservation).where(ShadowObservation.source_event_id == source_id).with_for_update())
    if prior:
        if prior.command != service.canonical(command) or prior.actor_id != actor_id:
            raise ValueError("同外部原请求身份的输入变化")
        return prior
    aggregate = f"invoice:{claim.invoice_id}"
    return service.record_observation(db, source_event_id=source_id, invoice_id=claim.invoice_id,
        local_customer_id=getattr(invoice, "local_customer_id", None),
        payment_id=raw.get("receipt", {}).get("batch_id") if action == "legacy.receipt.remote" else None, action=action,
        request_key=source_id, command=command, outcome=outcome, result=result,
        # Legacy documents lack a universal revision counter. The immutable
        # original order claim is its monotonic sending generation, including
        # requests sent before observation was enabled. Arrival order is not a
        # contract version and cannot promote an older provider result.
        contract_revision=claim.id if action == "legacy.order.push" else (
            raw.get("source_contract_revision") or 1),
        causal_version=_sequence(db, aggregate),
        dependencies=[], actor_id=actor_id, authority_epoch=claim.epoch, aggregate_key=aggregate,
        reason_code=str(evidence_ref)[:160] if outcome == "rejected" else None)


def capture_legacy_receipt(db, invoice, row, payload):
    from app.commerce_shadow.capture import receipt
    return receipt(db, invoice, row, payload)


def capture_legacy_outbound(db, invoice, payload, actor_id, *, request_key, operation="create", before=None):
    from app.commerce_shadow.capture import outbound
    return outbound(db, invoice, payload, actor_id, request_key=request_key, operation=operation, before=before)
