"""Source evidence, transaction outbox and read-only comparison reports.

None of these functions sends HTTP or commits a source business transaction.
Rejected observations are diagnostic records, never financial/stock events.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func
# Register the genuine dependency-closure models before isolated create_all.
from app.production.local_models import ProductionSupply  # noqa: F401
from app.commerce_shadow.models import (
    ShadowObservation, ShadowOutbox, ShadowDataset, ShadowRun, ShadowDifference, ShadowReview,
)

CALCULATOR_VERSION = "local-domain-v1"
SECRET_KEYS = {"password", "token", "secret", "authorization", "credential", "api_key", "scan_token",
               "attachment_ids", "media_url", "proof_url", "photos", "videos"}


def canonical(value):
    if isinstance(value, float):
        raise ValueError("对比命令金额/数量必须使用整数或十进制字符串")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("非有限数值不可观察")
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        for key in value:
            if str(key).lower() in SECRET_KEYS and value[key]:
                raise ValueError("对比输入不允许凭据、媒体链接或真实扫码身份")
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError("对比输入包含不支持的类型")


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def command_references(value):
    if isinstance(value, dict):
        if "$ref" in value:
            return {value["$ref"]}
        return set().union(*(command_references(child) for child in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(command_references(child) for child in value)) if value else set()
    return set()


def record_observation(db, *, source_event_id, invoice_id, action, request_key, command, outcome, result,
                       contract_revision, causal_version, dependencies, actor_id, authority_epoch=1,
                       reason_code=None, aggregate_key=None, local_customer_id=None, payment_id=None,
                       _resolution_of=None, _resolution_evidence=None):
    """Append after real authorization, in caller's transaction; never commit.

An unknown external request keeps its observation. Later recovery appends a NEW
source_event_id with that event in dependencies, never mutates the old evidence.
Call rejected observations in a separate transaction after economic rollback.
"""
    if outcome not in {"accepted", "rejected", "unknown"}:
        raise ValueError("未知命令结果分类")
    if min(causal_version, actor_id, authority_epoch) < 1 or contract_revision < (1 if invoice_id else 0):
        raise ValueError("观察身份/版本必须明确")
    if not any(identity is not None and identity > 0 for identity in (invoice_id, local_customer_id, payment_id)):
        raise ValueError("观察需真实订单、付款或客户身份，不能制造假订单")
    invoice_id = invoice_id or None
    if not source_event_id or len(source_event_id) > 128 or not request_key or len(request_key) > 128:
        raise ValueError("观察事件/请求身份无效")
    if not action or len(action) > 64:
        raise ValueError("观察动作无效")
    payload = canonical(dict(source_event_id=source_event_id, invoice_id=invoice_id, action=action,
        request_key=request_key, command=command, outcome=outcome, result=result,
        local_customer_id=local_customer_id, payment_id=payment_id,
        contract_revision=contract_revision, causal_version=causal_version,
        dependencies=sorted(set(dependencies) | command_references(command)),
        actor_id=actor_id, authority_epoch=authority_epoch, reason_code=reason_code,
        resolves_source_event_id=_resolution_of, resolution_evidence=_resolution_evidence,
        aggregate_key=aggregate_key or (f"invoice:{invoice_id}" if invoice_id else f"payment:{payment_id}" if payment_id
                                       else "payment-request:" + digest([local_customer_id, request_key]))))
    fingerprint = digest(payload)
    prior = db.scalar(select(ShadowObservation).where(ShadowObservation.source_event_id == source_event_id))
    if prior:
        if prior.request_hash != fingerprint:
            raise ValueError("源事件身份已用于不同命令或结果")
        return prior
    # A normal flush joins the caller's real transaction. In particular do not
    # open/release a stand-alone SQLite SAVEPOINT, which could commit evidence
    # before the enclosing business transaction has actually begun.
    row = ShadowObservation(**payload, request_hash=fingerprint)
    db.add(row)
    db.flush()
    db.add(ShadowOutbox(observation_id=row.id))
    db.flush()
    return row


def resolve_observation(db, *, unknown_source_event_id, outcome, result, evidence_ref, actor_id):
    """Append terminal readback evidence; never resend or rewrite the unknown.

Caller has verified the original external claim's terminal readback in this
transaction. This method can only reuse its immutable original command/actor,
contract and epoch. It cannot replace any economic input while resolving it.
"""
    original = db.scalar(select(ShadowObservation).where(
        ShadowObservation.source_event_id == unknown_source_event_id).with_for_update())
    if original is None or original.outcome != "unknown":
        raise ValueError("只能解决原有unknown观察")
    if outcome not in {"accepted", "rejected"} or actor_id != original.actor_id:
        raise ValueError("解决观察需原操作人及明确终局结果")
    if not isinstance(evidence_ref, dict) or not evidence_ref.get("terminal_readback_ref"):
        raise ValueError("解决观察需原请求终局读回证据引用")
    evidence_ref = canonical(evidence_ref)
    prior = db.scalar(select(ShadowObservation).where(
        ShadowObservation.resolves_source_event_id == unknown_source_event_id))
    if prior:
        if prior.outcome != outcome or prior.result != canonical(result) or prior.resolution_evidence != evidence_ref:
            raise ValueError("unknown已关联不同终局证据")
        return prior
    latest = db.scalar(select(func.max(ShadowObservation.causal_version)).where(
        ShadowObservation.aggregate_key == original.aggregate_key))
    return record_observation(db, source_event_id="resolution:" + digest(unknown_source_event_id),
        invoice_id=original.invoice_id, action=original.action, request_key="resolve:" + digest(original.request_key),
        command=original.command, outcome=outcome, result=result, contract_revision=original.contract_revision,
        causal_version=latest + 1, dependencies=sorted(set(original.dependencies + [unknown_source_event_id])),
        actor_id=original.actor_id, authority_epoch=original.authority_epoch,
        reason_code="resolution:" + unknown_source_event_id, aggregate_key=original.aggregate_key,
        local_customer_id=original.local_customer_id, payment_id=original.payment_id,
        _resolution_of=unknown_source_event_id, _resolution_evidence=evidence_ref)


def invoice_access(db, invoice_id, user):
    # Main's real-time access lookup; never trust actor/owner snapshots or the URL.
    from app.invoice.models import Invoice
    from app.invoice import delegation_service
    if ("super_admin" not in user.get("roles", []) and
            not {"invoice:read", "invoice:read_all"}.intersection(user.get("permissions", []))):
        raise HTTPException(404, "订单不存在")
    row = db.get(Invoice, invoice_id)
    if row is None:
        raise HTTPException(404, "订单不存在")
    if ("super_admin" not in user.get("roles", []) and "invoice:read_all" not in user.get("permissions", [])
            and not delegation_service.can_access_invoice(db, int(user["sub"]), row)):
        raise HTTPException(404, "订单不存在")
    if (row.local_customer_id and "super_admin" not in user.get("roles", [])
            and "invoice:read_all" not in user.get("permissions", [])):
        from app.customer.access_service import require_customer_access, CustomerAccessDenied
        try:
            require_customer_access(db, customer_id=row.local_customer_id, user=user,
                action_permissions=["invoice:read"], manage_permissions=["customer:admin"])
        except CustomerAccessDenied:
            raise HTTPException(404, "订单不存在") from None
    return row


def payment_access(db, payment_id, user):
    from app.finance.service import ensure_batch_access
    from app.invoice.settlement_models import ReceiptBatch
    if "super_admin" not in user.get("roles", []) and "receipt:read" not in user.get("permissions", []):
        raise HTTPException(404, "付款对比不存在")
    row = db.get(ReceiptBatch, payment_id)
    if row is not None and row.transaction_mode == "legacy":
        from app.receipt.models import Receipt
        from app.receipt import access
        from app.invoice.models import Invoice
        invoices = set(db.scalars(select(Receipt.invoice_id).where(Receipt.batch_id == row.id)))
        for identity in invoices:
            access.ensure_invoice(db, db.get(Invoice, identity), user)
        if not invoices and not access.all_access(user):
            if not row.local_customer_id:
                raise HTTPException(404, "付款对比不存在")
            customer_access(db, row.local_customer_id, user)
        return row
    ensure_batch_access(db, row, user)
    return row


def customer_access(db, customer_id, user):
    from app.customer.access_service import require_customer_access, CustomerAccessDenied
    try:
        return require_customer_access(db, customer_id=customer_id, user=user,
            action_permissions=["receipt:read"], manage_permissions=["customer:admin"])
    except CustomerAccessDenied:
        raise HTTPException(404, "付款对比不存在") from None


def observation_access(db, observation, user):
    if observation.action.startswith("legacy.receipt."):
        from app.invoice.models import Invoice
        from app.receipt.access import ensure_invoice
        if "super_admin" not in user.get("roles", []) and "receipt:read" not in user.get("permissions", []):
            raise HTTPException(404, "回款对比不存在")
        ensure_invoice(db, db.get(Invoice, observation.invoice_id), user)
        if observation.payment_id:
            payment_access(db, observation.payment_id, user)
        return observation
    if not observation.invoice_id and observation.action.startswith("contract.") and observation.local_customer_id:
        from app.customer.access_service import require_customer_access, CustomerAccessDenied
        try:
            require_customer_access(db, customer_id=observation.local_customer_id, user=user,
                action_permissions=["invoice:read", "invoice:write"], manage_permissions=["customer:admin"])
            return observation
        except CustomerAccessDenied:
            raise HTTPException(404, "合同对比不存在") from None
    if observation.invoice_id:
        invoice_access(db, observation.invoice_id, user)
    if observation.action.startswith(("payment.", "allocation.")) or not observation.invoice_id:
        if "super_admin" not in user.get("roles", []) and "receipt:read" not in user.get("permissions", []):
            raise HTTPException(404, "付款对比不存在")
        if observation.payment_id:
            payment_access(db, observation.payment_id, user)
        elif observation.local_customer_id:
            customer_access(db, observation.local_customer_id, user)
        elif not observation.invoice_id:
            raise HTTPException(404, "付款对比不存在")
    return observation


def create_dataset(db, *, dataset_id, checkpoint, target_fingerprint, actor_id):
    """Operator-only registration. No checkpoint import from the public API.

checkpoint={complete, invoice_ids, dependencies, watermarks, through_observation_id,
initial_state_verified, evidence}. It describes a separately prepared target;
it is NOT a dump of source domain/result rows.
"""
    checkpoint = canonical(checkpoint)
    required = {"complete", "invoice_ids", "dependencies", "watermarks", "through_observation_id",
                "initial_state_verified", "evidence"}
    if required - set(checkpoint) or not checkpoint["evidence"]:
        raise ValueError("检查点缺少覆盖清单或核验依据")
    for aggregate, version in checkpoint["watermarks"].items():
        if version and (aggregate not in checkpoint.get("contract_revisions", {})
                        or aggregate not in checkpoint.get("authority_epochs", {})):
            raise ValueError("非零检查点需原合同版本及办理权epoch清单")
    if not dataset_id or len(dataset_id) > 64 or len(target_fingerprint) != 64:
        raise ValueError("数据集/隔离目标身份无效")
    row = ShadowDataset(id=dataset_id, checkpoint=checkpoint, checkpoint_hash=digest(checkpoint),
                        target_fingerprint=target_fingerprint, created_by=actor_id)
    db.add(row)
    db.flush()
    return row


def request_run(db, body, user):
    for identity in body.invoice_ids:
        invoice_access(db, identity, user)
    dataset = db.get(ShadowDataset, body.dataset_id)
    if dataset is None:
        raise HTTPException(404, "验证数据集不存在")
    # The whole dependency closure is visible to the caller, not just one order.
    for identity in dataset.checkpoint["invoice_ids"]:
        invoice_access(db, identity, user)
    if set(body.invoice_ids) != set(dataset.checkpoint["invoice_ids"]):
        raise ValueError("必须运行完整检查点责任闭包")
    if (set(body.payment_ids) != set(dataset.checkpoint.get("payment_ids", [])) or
            set(body.local_customer_ids) != set(dataset.checkpoint.get("local_customer_ids", []))):
        raise ValueError("必须运行完整付款/客户检查点范围")
    if not body.invoice_ids and not body.payment_ids and not body.local_customer_ids and not dataset.checkpoint.get("source_event_ids"):
        raise ValueError("运行至少需要一个真实订单、付款或已观察客户范围")
    for identity in body.payment_ids:
        payment_access(db, identity, user)
    for identity in body.local_customer_ids:
        customer_access(db, identity, user)
    fingerprint = digest(body.model_dump())
    prior = db.scalar(select(ShadowRun).where(ShadowRun.request_key == body.request_key))
    if prior:
        if prior.request_hash != fingerprint:
            raise ValueError("运行请求键已用于不同数据集或水位")
        return prior
    row = ShadowRun(id=uuid4().hex, dataset_id=body.dataset_id, request_key=body.request_key,
        request_hash=fingerprint, calculator_version=CALCULATOR_VERSION, invoice_ids=sorted(set(body.invoice_ids)),
        payment_ids=sorted(set(body.payment_ids)), local_customer_ids=sorted(set(body.local_customer_ids)),
        through_observation_id=body.through_observation_id, created_by=int(user["sub"]),
        coverage={"state": "pending", "missing_dependencies": [], "observed_through": body.through_observation_id,
                  "exported_through": 0, "applied_through": 0, "rejection_coverage": "observed_only"})
    db.add(row)
    db.flush()
    return row


def review_difference(db, identity, body, user):
    row = db.scalar(select(ShadowDifference).where(ShadowDifference.id == identity).with_for_update())
    if row is None:
        raise HTTPException(404, "差异不存在")
    observation_access(db, db.get(ShadowObservation, row.observation_id), user)
    run = db.get(ShadowRun, row.run_id)
    for invoice_id in run.invoice_ids:
        invoice_access(db, invoice_id, user)
    from app.commerce_shadow.transport import collect_observations
    dataset = db.get(ShadowDataset, run.dataset_id)
    observations, _missing = collect_observations(db, run, dataset)
    for observation in observations:
        observation_access(db, observation, user)
    evidence = body.evidence.strip()
    if len(evidence) < 5:
        raise ValueError("复核需填写可核验的事实依据")
    db.add(ShadowReview(difference_id=row.id, actor_id=int(user["sub"]), classification=body.classification,
                        evidence=evidence))
    row.classification = body.classification
    db.flush()
    # Reports keep numerical differences and their run's status unchanged.
    return row


def describe_run(row):
    return {name: getattr(row, name) for name in ("id", "dataset_id", "calculator_version", "invoice_ids",
        "payment_ids", "local_customer_ids",
        "through_observation_id", "status", "coverage", "created_at", "checked_at")}


def describe_difference(row):
    return {name: getattr(row, name) for name in ("id", "run_id", "observation_id", "invoice_id", "payment_id", "local_customer_id", "field",
        "expected", "actual", "classification", "created_at")}
