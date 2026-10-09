"""Immutable original attempts, external observations and scoped recovery summaries."""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now, to_beijing_time
from app.portal.event_models import AuditEvent
from app.portal.order_models import Conversion, OrderRequest

START = "external_attempt_started"
FACT = "external_attempt_fact"
RECONCILED = "external_attempt_reconciled"
FINISHED = "external_attempt_finished"
ACTIONS = (START, FACT, RECONCILED, FINISHED)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, default=str).encode()).hexdigest()


def event_id(invoice_id, attempt_key, kind, fingerprint=""):
    return str(uuid5(NAMESPACE_URL, f"leshine:invoice-cancel:{invoice_id}:{attempt_key}:{kind}:{fingerprint}"))


def target_binding(invoice):
    return digest((str(invoice.xiaoman_order_id), str(invoice.customer_id), invoice.currency))


def object_binding(db, invoice_id):
    conversion = db.scalar(select(Conversion).where(Conversion.invoice_id == invoice_id))
    if conversion is None:
        return str(uuid5(NAMESPACE_URL, f"leshine:invoice:{invoice_id}")), None
    request = db.get(OrderRequest, conversion.request_id)
    return conversion.public_id, request.access_id


def append(db, invoice_id, attempt_key, action, data, *, object_id, access_id,
           actor_id=None, fingerprint=""):
    identity = event_id(invoice_id, attempt_key, action, fingerprint)
    prior = db.scalar(select(AuditEvent).where(AuditEvent.public_id == identity))
    if prior is None:
        prior = AuditEvent(public_id=identity, actor_type="employee" if actor_id else "system",
            actor_id=actor_id, access_id=access_id, object_type="invoice", object_public_id=object_id,
            action=action, reason="Original cancellation execution evidence", trace_id=attempt_key,
            safe_diff_json=data)
        db.add(prior)
        db.flush()
    return prior


@dataclass(frozen=True)
class Attempt:
    invoice_id: int
    key: str
    target: str
    token: str
    binding: tuple
    object_id: str
    access_id: int | None
    actor_id: int
    data: dict


def start(db, invoice, binding, token, actor_id):
    key = str(uuid4())
    object_id, access_id = object_binding(db, invoice.id)
    data = {"attempt_key":key, "task_type":"invoice_cancel_delete", "invoice_id":invoice.id,
        "target_fingerprint":digest(str(invoice.xiaoman_order_id)),
        "target_binding":target_binding(invoice), "binding_fingerprint":digest(binding),
        "document_version":invoice.portal_document_version, "content_fingerprint":binding[2],
        "run_token_fingerprint":digest(token), "original_actor_id":actor_id}
    append(db, invoice.id, key, START, data, object_id=object_id, access_id=access_id, actor_id=actor_id)
    return Attempt(invoice.id, key, str(invoice.xiaoman_order_id), token, binding,
                   object_id, access_id, actor_id, data)


def validate(db, attempt):
    row = db.scalar(select(AuditEvent).where(AuditEvent.public_id ==
        event_id(attempt.invoice_id, attempt.key, START)))
    if (row is None or row.action != START or row.object_type != "invoice"
        or row.object_public_id != attempt.object_id or row.access_id != attempt.access_id
        or row.safe_diff_json != attempt.data or attempt.data.get("invoice_id") != attempt.invoice_id
        or attempt.data.get("target_fingerprint") != digest(attempt.target)
        or attempt.data.get("binding_fingerprint") != digest(attempt.binding)
        or attempt.data.get("run_token_fingerprint") != digest(attempt.token)
        or object_binding(db, attempt.invoice_id) != (attempt.object_id, attempt.access_id)):
        raise HTTPException(409, "原执行证据或对象绑定无效", headers={"Cache-Control":"no-store"})


def observation(attempt, kind, result, evidence):
    if kind not in {"delete_response", "readback_observation"} or result not in {"succeeded", "failed", "unknown"}:
        raise ValueError("Unsupported execution observation")
    if evidence not in {"accepted", "unavailable", "absent", "present"}:
        raise ValueError("Unsupported safe execution evidence")
    semantic = {"attempt_key":attempt.key, "effect_kind":kind, "result_class":result,
        "provider_reference":attempt.data["target_fingerprint"], "evidence":evidence}
    return {**semantic, "fact_fingerprint":digest(semantic), "observed_at":beijing_now().isoformat()}


def record(db, attempt, observations):
    validate(db, attempt)
    for fact in observations:
        if (fact.get("effect_kind") not in {"delete_response", "readback_observation"}
            or fact.get("result_class") not in {"succeeded", "failed", "unknown"}
            or fact.get("evidence") not in {"accepted", "unavailable", "absent", "present"}):
            raise HTTPException(409, "原观测分类无效")
        if set(fact) != {"attempt_key", "effect_kind", "result_class", "provider_reference",
                        "evidence", "fact_fingerprint", "observed_at"}:
            raise HTTPException(409, "原观测字段无效")
        semantic = {key:fact[key] for key in ("attempt_key", "effect_kind", "result_class",
            "provider_reference", "evidence")}
        if (semantic["attempt_key"] != attempt.key or semantic["provider_reference"] != attempt.data["target_fingerprint"]
            or fact["fact_fingerprint"] != digest(semantic)):
            raise HTTPException(409, "原观测证据无效")
        append(db, attempt.invoice_id, attempt.key, FACT, fact, object_id=attempt.object_id,
            access_id=attempt.access_id, fingerprint=fact["effect_kind"]+":"+fact["fact_fingerprint"])


def journal(db, invoice):
    object_id, access_id = object_binding(db, invoice.id)
    return db.scalars(select(AuditEvent).where(AuditEvent.object_type == "invoice",
        AuditEvent.object_public_id == object_id, AuditEvent.action.in_(ACTIONS))
        .order_by(AuditEvent.id).execution_options(populate_existing=True)).all()


def capture(db, invoice):
    rows = journal(db, invoice)
    return tuple(sorted(row.public_id for row in rows if row.action in {START, FACT}))


def review_required(db, invoice):
    rows = journal(db, invoice)
    starts = [row for row in rows if row.action == START]
    binding = target_binding(invoice)
    pending = []
    for row in starts:
        key = row.safe_diff_json.get("attempt_key")
        facts = [fact for fact in rows if fact.action == FACT and fact.safe_diff_json.get("attempt_key") == key]
        fingerprint = digest(sorted([row.public_id]+[fact.public_id for fact in facts]))
        reviewed = any(item.action == RECONCILED and item.safe_diff_json.get("attempt_key") == key
            and item.safe_diff_json.get("collection_fingerprint") == fingerprint
            and item.safe_diff_json.get("target_binding") == binding for item in rows)
        if not reviewed:
            pending.append(row)
    return pending, rows


def reconcile(db, invoice, observation_value, actor_id, *, attempt_keys=None):
    pending, rows = review_required(db, invoice)
    object_id, access_id = object_binding(db, invoice.id)
    for started in pending:
        data = started.safe_diff_json
        key = data["attempt_key"]
        if attempt_keys is not None and key not in attempt_keys:
            continue
        if data.get("target_binding") != target_binding(invoice):
            raise HTTPException(409, "原远端目标已变化，请人工核对")
        collection = digest(sorted([started.public_id]+[row.public_id for row in rows
            if row.action == FACT and row.safe_diff_json.get("attempt_key") == key]))
        proof = {"attempt_key":key, "collection_fingerprint":collection,
            "target_binding":target_binding(invoice), "remote_observation":observation_value,
            "observed_at":beijing_now().isoformat()}
        append(db, invoice.id, key, RECONCILED, proof, object_id=object_id, access_id=access_id,
            actor_id=actor_id, fingerprint=digest((collection, target_binding(invoice), observation_value)))


def summary(db, invoice):
    pending, rows = review_required(db, invoice)
    facts = [row.safe_diff_json for row in rows if row.action == FACT]
    readbacks = sorted((fact for fact in facts if fact.get("effect_kind") == "readback_observation"),
                       key=lambda fact:fact.get("observed_at", ""))
    reviews = [row.safe_diff_json for row in rows if row.action == RECONCILED]
    observed = sorted([(fact.get("observed_at", ""), fact.get("evidence", "unavailable")) for fact in readbacks]
        + [(review.get("observed_at", ""), review.get("remote_observation", "unknown")) for review in reviews])
    value = observed[-1][1] if observed else "not_checked"
    latest = max((item[0] for item in observed), default=None)
    timestamp = to_beijing_time(datetime.fromisoformat(latest)).isoformat() if latest else None
    return {"review_required":bool(pending), "pending_attempt_count":len(pending),
        "last_observed_at":timestamp,
        "remote_observation":value if value in {"absent", "present", "not_checked"} else "unknown"}


def finish(db, attempt, invoice, binding):
    """Durable original fenced completion, for uncertain commit acknowledgements."""
    data = {"invoice_id":invoice.id, "attempt_key":attempt.key,
        "binding_fingerprint":digest(binding), "state_fingerprint":digest(invoice.cancellation)}
    append(db, invoice.id, attempt.key, FINISHED, data, object_id=attempt.object_id,
           access_id=attempt.access_id)


def completed(db, attempt, invoice, binding):
    row = db.scalar(select(AuditEvent).where(AuditEvent.public_id ==
        event_id(invoice.id, attempt.key, FINISHED)))
    if row is None:
        return False
    return (row.action == FINISHED and row.object_public_id == attempt.object_id
        and row.access_id == attempt.access_id and row.safe_diff_json == {
            "invoice_id":invoice.id, "attempt_key":attempt.key,
            "binding_fingerprint":digest(binding), "state_fingerprint":digest(invoice.cancellation)})
