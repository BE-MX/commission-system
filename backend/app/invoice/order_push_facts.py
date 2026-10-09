"""Trusted original order POST identity and immutable safe observations."""
import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now, to_beijing_time
from app.invoice.cancellation_facts import digest, object_binding
from app.portal.event_models import AuditEvent

logger = logging.getLogger(__name__)

START = "invoice_push_attempt"
FACT = "invoice_push_observation"
FINISH = "invoice_push_finished"
REVIEW = "invoice_push_reconciled"


def identity(invoice_id, key, kind):
    return str(uuid5(NAMESPACE_URL, f"leshine:invoice-push:{invoice_id}:{key}:{kind}"))


def get(db, invoice_id, key, kind):
    return db.scalar(select(AuditEvent).where(AuditEvent.public_id == identity(invoice_id,key,kind))
                     .execution_options(populate_existing=True))


def append(db, invoice_id, key, kind, data, object_id, access_id, actor_id=None):
    row=get(db,invoice_id,key,kind)
    if row is not None:
        if row.safe_diff_json != data or row.object_public_id != object_id or row.access_id != access_id:
            raise HTTPException(409,"原推单事实身份或内容不一致")
        return row
    row=AuditEvent(public_id=identity(invoice_id,key,kind),actor_type="employee" if actor_id else "system",
                   actor_id=actor_id,access_id=access_id,object_type="invoice",object_public_id=object_id,
                   action=kind.split(":")[0],reason="Original order push evidence",trace_id=key,
                   safe_diff_json=deepcopy(data))
    db.add(row);db.flush()
    return row


@dataclass(frozen=True)
class Attempt:
    invoice_id: int
    key: str
    token: str
    actor_id: int
    binding: tuple
    payload: dict
    object_id: str
    access_id: int | None
    data: dict
    inventory_key: str | None
    receipt_token: str | None


def start(db,invoice,actor_id,binding,payload,inventory_key,receipt_token):
    token=(invoice.sync_attempt or {}).get("token")
    key=(invoice.sync_attempt or {}).get("attempt_key")
    if not token or not key:raise ValueError("Missing durable order attempt")
    object_id,access_id=object_binding(db,invoice.id)
    data={"invoice_id":invoice.id,"attempt_key":key,"task_type":"invoice_order_push",
          "action":"update" if invoice.xiaoman_order_id else "create",
          "original_order_id":invoice.xiaoman_order_id,"original_actor_id":actor_id,
          "payload_fingerprint":digest(payload),"binding_fingerprint":digest(binding),
          "token_fingerprint":digest(token),"document_version":invoice.portal_document_version,
          "inventory_operation_key":inventory_key,"receipt_token_fingerprint":digest(receipt_token)}
    append(db,invoice.id,key,START,data,object_id,access_id,actor_id)
    return Attempt(invoice.id,key,token,actor_id,deepcopy(binding),deepcopy(payload),object_id,access_id,
                   deepcopy(data),inventory_key,receipt_token)


def validate(db,attempt):
    row=get(db,attempt.invoice_id,attempt.key,START)
    if (row is None or row.action != START or row.safe_diff_json != attempt.data
            or row.object_public_id != attempt.object_id or row.access_id != attempt.access_id
            or object_binding(db,attempt.invoice_id) != (attempt.object_id,attempt.access_id)
            or attempt.data.get("invoice_id") != attempt.invoice_id
            or attempt.data.get("original_actor_id") != attempt.actor_id
            or attempt.data.get("inventory_operation_key") != attempt.inventory_key
            or attempt.data.get("receipt_token_fingerprint") != digest(attempt.receipt_token)
            or attempt.data.get("token_fingerprint") != digest(attempt.token)
            or attempt.data.get("binding_fingerprint") != digest(attempt.binding)
            or attempt.data.get("payload_fingerprint") != digest(attempt.payload)):
        raise HTTPException(409,"原推单执行身份无效")


def observation(attempt,round_number,result,provider_reference=None,response=None):
    if round_number not in (1,2) or result not in {"accepted","rejected","unknown","auth_rejected"}:
        raise ValueError("Invalid order observation")
    return {"attempt_key":attempt.key,"round":round_number,"result_class":result,
            "provider_reference":provider_reference,"response_fingerprint":digest(response),
            "observed_at":beijing_now().isoformat()}


def record(db,attempt,observation):
    validate(db,attempt)
    if (set(observation) != {"attempt_key","round","result_class","provider_reference","response_fingerprint","observed_at"}
            or observation["attempt_key"] != attempt.key or observation["round"] not in (1,2)
            or observation["result_class"] not in {"accepted","rejected","unknown","auth_rejected"}):
        raise HTTPException(409,"原推单观测无效")
    kind=FACT+":"+str(observation["round"])
    prior=get(db,attempt.invoice_id,attempt.key,kind)
    append(db,attempt.invoice_id,attempt.key,kind,observation,attempt.object_id,attempt.access_id)
    if prior is None:
        from app.invoice.models import InvoiceSyncLog
        db.add(InvoiceSyncLog(invoice_id=attempt.invoice_id,action="push_fact",success=0,
                              operator_id=attempt.actor_id,request_digest="Original order observation",
                              response_body=json.dumps(observation,ensure_ascii=True)))


def observations(db, invoice_id, key):
    return [row for round_number in (1, 2)
            if (row := get(db, invoice_id, key, FACT + ":" + str(round_number))) is not None]


def observation_fingerprint(db, invoice_id, key):
    return digest([(row.public_id, row.safe_diff_json) for row in observations(db, invoice_id, key)])


def unresolved(db, invoice):
    object_id, access_id = object_binding(db, invoice.id)
    starts = db.scalars(select(AuditEvent).where(AuditEvent.object_type == "invoice",
        AuditEvent.object_public_id == object_id, AuditEvent.action == START)
        .order_by(AuditEvent.id).execution_options(populate_existing=True)).all()
    pending = []
    for row in starts:
        data = row.safe_diff_json or {}
        key = data.get("attempt_key")
        if not key or data.get("invoice_id") != invoice.id:
            raise HTTPException(409, "原推单事实身份不完整")
        current = observation_fingerprint(db, invoice.id, key)
        reviewed = db.scalars(select(AuditEvent).where(AuditEvent.action == REVIEW,
            AuditEvent.trace_id == key, AuditEvent.object_public_id == object_id)
            .execution_options(populate_existing=True)).all()
        finished = get(db, invoice.id, key, FINISH)
        if (any(row.safe_diff_json.get("observation_fingerprint") == current for row in reviewed)
                or finished and finished.safe_diff_json.get("resolved")
                and finished.safe_diff_json.get("observation_fingerprint") == current):
            continue
        pending.append(row)
    return pending


def check_review(db, invoice, original_key, resolution, target=None):
    if not original_key:
        if unresolved(db, invoice):
            raise HTTPException(409, "原执行身份缺失，禁止绕过持久推单事实")
        return
    row = get(db, invoice.id, original_key, START)
    if row is None or row.action != START or object_binding(db, invoice.id) != (row.object_public_id, row.access_id):
        raise HTTPException(409, "原推单记录缺失或不属于当前订单")
    accepted = {record.safe_diff_json.get("provider_reference") for record in observations(db, invoice.id, original_key)
                if record.safe_diff_json.get("result_class") == "accepted"}
    if accepted and (resolution == "confirm_not_created" or accepted != {str(target)}):
        raise HTTPException(409, "原推单已获接受，核对必须使用原供应商订单身份")


def review(db, invoice, original_key, resolution):
    if not original_key:
        return
    row = get(db, invoice.id, original_key, START)
    if row is None:
        raise HTTPException(409, "原推单记录缺失")
    fingerprint = observation_fingerprint(db, invoice.id, original_key)
    append(db, invoice.id, original_key, REVIEW + ":" + fingerprint, {
        "attempt_key": original_key, "resolution": resolution,
        "observation_fingerprint": fingerprint},
        row.object_public_id, row.access_id)


def summary(db, invoice):
    """Current scoped local risk only; never expose raw attempts or provider bodies."""
    pending = unresolved(db, invoice)
    records = [record.safe_diff_json for attempt in pending
               for record in observations(db, invoice.id, attempt.safe_diff_json["attempt_key"])]
    accepted = set()
    for record in records:
        if record.get("result_class") == "accepted":
            from app.invoice.uncertain_recovery import _canonical_uid
            try:
                accepted.add(_canonical_uid(record.get("provider_reference")))
            except ValueError:
                logger.warning("Original push reference is not canonical")
                print("[invoice-push] original reference is not canonical", flush=True)
                accepted.add(None)
    result = "not_observed" if not records else "unknown"
    if accepted:
        result = "accepted" if len(accepted) == 1 and None not in accepted else "conflicting"
    elif records and all(record.get("result_class") in {"rejected", "auth_rejected"} for record in records):
        result = "rejected"
    timestamps = []
    for record in records:
        try:
            timestamps.append(to_beijing_time(datetime.fromisoformat(record["observed_at"])))
        except (ValueError, TypeError, KeyError):
            logger.warning("Original push observation time unavailable")
            print("[invoice-push] observation time unavailable", flush=True)
            continue
    reference = next(iter(accepted)) if result == "accepted" else None
    resolution = None
    if (len(pending) == 1 and reference and not invoice.sync_attempt
            and (invoice.status, invoice.sync_status) in {("ready", "not_synced"), ("synced", "synced")}
            and (not invoice.xiaoman_order_id or str(invoice.xiaoman_order_id) == reference)):
        resolution = "confirm_existing" if invoice.xiaoman_order_id else "bind_order"
    return {"review_required": bool(pending), "pending_attempt_count": len(pending),
            "last_observed_at": max(timestamps).isoformat() if timestamps else None,
            "result_class": result, "original_order_id": reference, "resolution": resolution}
