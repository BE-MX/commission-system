"""Advance the linked OKKI purchase and receipt using durable per-stage intents."""

from dataclasses import asdict
from datetime import date
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.commerce_transition import service as transition
from app.core.config import get_settings
from app.core.time import beijing_now
from app.factory_inbound.batch_models import Batch
from app.factory_inbound.linked_purchase import (
    LinkedPurchaseBatch, LinkedPurchaseError, LinkedPurchaseLine,
    build_inbound_completion, build_inbound_draft, build_purchase_order,
)
from app.factory_inbound.okki_transport import INBOUND_PATH, PURCHASE_PATH, OkkiMutationRejected, OkkiTransport
from app.factory_inbound.purchase_readback import PurchaseReadbackError
from app.factory_inbound.writeback_service import WritebackConflict, apply_writeback, record_completed_readback
from app.inventory.legacy_scope import require_legacy_purchase_inbound_scope

logger = logging.getLogger(__name__)
MUTATION_PATHS = {"purchase": f"{PURCHASE_PATH}/push", "draft": f"{INBOUND_PATH}/push",
                  "complete": f"{INBOUND_PATH}/push"}


class SyncConflict(ValueError):
    """The batch cannot enter or continue the automatic legacy route."""


def _tenant_binding():
    settings = get_settings()
    return transition.digest([
        settings.OKKI_API_BASE.rstrip("/"), settings.OKKI_CLIENT_ID, settings.PORTAL_OKKI_NAMESPACE,
    ])


def initialize_batch(batch, linked_batch, *, operator_name):
    """Freeze the approved pair before any OKKI call."""
    build_purchase_order(linked_batch)
    intent = asdict(linked_batch)
    intent["business_date"] = linked_batch.business_date.isoformat()
    intent["lines"] = list(intent["lines"])
    batch.purchase_intent = {**intent, "operator_name": operator_name, "tenant_binding": _tenant_binding()}
    batch.sync_checkpoint = {"stage": "purchase"}
    batch.request_snapshot = {}


def _linked_batch(intent):
    return LinkedPurchaseBatch(**{
        **{key: value for key, value in intent.items() if key not in {"operator_name", "tenant_binding"}},
        "business_date": date.fromisoformat(intent["business_date"]),
        "lines": tuple(LinkedPurchaseLine(**row) for row in intent["lines"]),
    })


def batch_status(batch):
    checkpoint = batch.sync_checkpoint or {}
    purchase = batch.purchase_intent or {}
    return {
        "id": str(batch.id),
        "batch_no": batch.batch_no,
        "sync_status": batch.sync_status,
        "writeback_status": batch.writeback_status,
        "stage": checkpoint.get("stage"),
        "message": checkpoint.get("message"),
        "purchase_order_no": purchase.get("purchase_order_no"),
        "xiaoman_serial_id": batch.xiaoman_serial_id or purchase.get("inbound_serial_id"),
        "xiaoman_inbound_id": str(batch.xiaoman_inbound_id) if batch.xiaoman_inbound_id else None,
        "can_resume": bool(purchase) and batch.sync_status != "blocked" and batch.writeback_status != "done",
    }


def _batch(db, batch_id, *, lock=False):
    query = select(Batch).where(Batch.id == batch_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    batch = db.scalar(query)
    if not batch or not batch.purchase_intent or not batch.sync_checkpoint:
        raise SyncConflict("工厂到货批次不存在或缺少已冻结的小满采购计划")
    return batch


def _legacy_policy(db):
    settings = get_settings()
    if not settings.FACTORY_INBOUND_SYNC_ENABLED:
        raise SyncConflict("小满自动入库尚未开启")
    if settings.TRANSACTION_MODE == "local":
        raise SyncConflict("当前环境已切换到方舟实物库存")
    try:
        return transition.require_phase(db, "legacy")
    except transition.TransitionError as exc:
        raise SyncConflict(str(exc)) from exc


def _guard_scope(db, batch):
    try:
        require_legacy_purchase_inbound_scope(db, {"record_list": batch.purchase_intent["lines"]})
    except ValueError as exc:
        raise SyncConflict(str(exc)) from exc


def _guard_tenant(batch):
    if batch.purchase_intent.get("tenant_binding") != _tenant_binding():
        raise SyncConflict("小满租户配置与批次确认时不一致，请恢复原配置后续办")


def _update_checkpoint(batch, **changes):
    batch.sync_checkpoint = {**batch.sync_checkpoint, **changes}


def _pause(batch, message, *, status="uncertain"):
    batch.sync_status = status
    _update_checkpoint(batch, message=message)


def _next_stage(batch, checkpoint, stage, remote_id):
    history = {**checkpoint.get("history", {}), checkpoint["stage"]: {
        "intent": checkpoint.get("attempt"), "verified_id": remote_id,
    }}
    batch.sync_checkpoint = {"stage": stage, "history": history}
    if stage in {"draft", "complete"}:
        batch.sync_status = "drafted" if stage == "complete" else "confirmed"


def _verify_identity(remote_id, known_id):
    try:
        if type(remote_id) is not int and not (
            isinstance(remote_id, str) and remote_id.isascii() and remote_id.isdecimal() and len(remote_id) <= 19
        ):
            raise ValueError()
        resolved = int(remote_id)
        if not 0 < resolved <= 9_223_372_036_854_775_807 or (known_id is not None and resolved != known_id):
            raise ValueError()
        return resolved
    except (TypeError, ValueError) as exc:
        raise SyncConflict("小满回读内部 ID 与已记录的请求不符") from exc


def _purchase_result(batch, linked, checkpoint, detail):
    attempt = checkpoint.get("attempt")
    dispatched = attempt and attempt.get("dispatch_started")
    if detail is None:
        return None if dispatched else build_purchase_order(linked)
    if not dispatched:
        _pause(batch, "预留采购单号已被占用，请核对原单", status="blocked")
        return None
    order_id = _verify_identity(detail.get("purchase_order_id"), attempt.get("remote_id"))
    batch.request_snapshot = build_inbound_draft(linked, detail, purchase_order_id=order_id)
    _next_stage(batch, checkpoint, "draft", order_id)
    return None


def _receipt_result(db, batch, linked, checkpoint, detail):
    stage = checkpoint["stage"]
    attempt = checkpoint.get("attempt")
    dispatched = attempt and attempt.get("dispatch_started")
    if detail is None:
        if stage == "draft" and not dispatched:
            return batch.request_snapshot
        return None
    if stage == "draft" and not dispatched:
        _pause(batch, "预留入库单号已被占用，请核对原单", status="blocked")
        return None
    known_id = batch.xiaoman_inbound_id or (attempt or {}).get("remote_id")
    remote_id = _verify_identity(detail.get("inbound_invoice_id"), known_id)
    if stage == "complete" and detail.get("status") in (2, "2"):
        record_completed_readback(db, batch.id, detail, inbound_id=remote_id, serial_id=linked.inbound_serial_id)
        _next_stage(batch, checkpoint, "done", remote_id)
        return None
    body = build_inbound_completion(batch.request_snapshot, detail, inbound_id=remote_id)
    if stage == "complete":
        return None if dispatched else body
    batch.xiaoman_inbound_id = remote_id
    batch.xiaoman_serial_id = linked.inbound_serial_id
    _next_stage(batch, checkpoint, "complete", remote_id)
    return None


def _external_detail(transport, linked, stage):
    if stage == "purchase":
        return transport.find_purchase(linked.purchase_order_no)
    return transport.find_inbound(linked.inbound_serial_id)


def _new_attempt(batch, body):
    attempt = {"token": uuid4().hex, "body": body, "intent_at": beijing_now().isoformat(timespec="seconds")}
    _pause(batch, "正在核对小满请求结果")
    _update_checkpoint(batch, attempt=attempt)
    return attempt


def _dispatch(db, batch_id, stage, attempt, transport_factory):
    # Only the caller who commits the dispatch marker may make this POST.
    # Cutover checks cover the recorded in-flight work, so no DB lock spans HTTP.
    authorized = False

    def before_send(path, payload):
        nonlocal authorized
        if (authorized or attempt.get("dispatch_started")
                or path != MUTATION_PATHS[stage] or payload != attempt["body"]):
            raise OkkiMutationRejected("小满发送凭证与已冻结的请求不符")
        try:
            policy = _legacy_policy(db)
            batch = _batch(db, batch_id, lock=True)
            checkpoint = batch.sync_checkpoint
            if batch.sync_status == "blocked" or checkpoint["stage"] != stage or checkpoint.get("attempt") != attempt:
                raise OkkiMutationRejected("本次发送凭证已失效或已被领取")
            _guard_tenant(batch)
            _guard_scope(db, batch)
            _pause(batch, "正在核对小满请求结果")
            _update_checkpoint(batch, attempt={**attempt, "policy_version": policy.version,
                                               "dispatch_started": beijing_now().isoformat(timespec="seconds")})
            db.commit()
        except Exception:
            db.rollback()
            raise
        authorized = True

    transport = transport_factory(before_send=before_send)
    received_id = None
    rejected = False
    try:
        body = attempt["body"]
        remote_id = transport.create_purchase(body) if stage == "purchase" else transport.push_inbound(body)
        if not authorized:
            raise SyncConflict("小满发送未经过批次凭证验证")
        received_id = _verify_identity(remote_id, body.get("inbound_id"))
    except OkkiMutationRejected:
        rejected = True
        logger.warning("Factory inbound send permit unavailable for batch %s stage %s", batch_id, stage)
        print(f"Factory inbound send permit unavailable for batch {batch_id} stage {stage}", flush=True)
    except Exception as exc:
        logger.warning("Unknown OKKI outcome for batch %s stage %s (%s)", batch_id, stage, type(exc).__name__)
        print(f"Unknown OKKI outcome for batch {batch_id} stage {stage} ({type(exc).__name__})", flush=True)

    transition.lock_policy(db)
    batch = _batch(db, batch_id, lock=True)
    checkpoint = batch.sync_checkpoint
    current = checkpoint.get("attempt") or {}
    if checkpoint["stage"] == stage and current.get("token") == attempt["token"] and batch.sync_status != "blocked":
        if received_id is not None:
            _update_checkpoint(batch, attempt={**current, "remote_id": received_id})
        elif rejected and not current.get("dispatch_started"):
            _pause(batch, "小满尚未发送，请检查配置后续办", status="failed")
        elif authorized:
            _pause(batch, "小满请求结果待核对")
    db.commit()


def _write_back(db, batch_id):
    try:
        batch = _batch(db, batch_id)
        _guard_tenant(batch)
        if batch.writeback_status == "done":
            db.rollback()
            return batch
        batch = apply_writeback(db, batch_id, operator_name=batch.purchase_intent["operator_name"])
        _update_checkpoint(batch, message=None)
        db.commit()
        return batch
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        logger.warning("Factory inbound writeback failed for batch %s (%s)", batch_id, type(exc).__name__)
        print(f"Factory inbound writeback failed for batch {batch_id} ({type(exc).__name__})", flush=True)
        batch = _batch(db, batch_id, lock=True)
        if batch.writeback_status != "done":
            batch.writeback_status = "failed"
            _update_checkpoint(batch, message=str(exc) if isinstance(exc, WritebackConflict) else "生产单回写待处理")
        db.commit()
        return batch


def _read_stage(db, batch_id, transport, linked, checkpoint):
    stage = checkpoint["stage"]
    try:
        return _external_detail(transport, linked, stage), True
    except Exception as exc:
        logger.warning("OKKI readback failed for batch %s stage %s (%s)", batch_id, stage, type(exc).__name__)
        print(f"OKKI readback failed for batch {batch_id} stage {stage} ({type(exc).__name__})", flush=True)
        batch = _batch(db, batch_id, lock=True)
        if batch.sync_checkpoint == checkpoint:
            _pause(batch, "小满回读暂未拿到有效结果")
        db.commit()
        return None, False


def _advance(db, batch_id, transport_factory):
    reader = transport_factory()
    # Three remote writes, three verified readbacks, and the local transaction.
    # A concurrent runner can advance a checkpoint, but cannot adopt our send token.
    for _ in range(10):
        if not get_settings().FACTORY_INBOUND_SYNC_ENABLED:
            raise SyncConflict("小满自动入库尚未开启")
        batch = _batch(db, batch_id)
        _guard_tenant(batch)
        checkpoint = batch.sync_checkpoint
        stage = checkpoint["stage"]
        if stage == "done":
            return _write_back(db, batch_id)
        if batch.sync_status == "blocked":
            db.rollback()
            return batch
        linked = _linked_batch(batch.purchase_intent)
        db.rollback()
        detail, readable = _read_stage(db, batch_id, reader, linked, checkpoint)
        if not readable:
            return db.get(Batch, batch_id)

        _legacy_policy(db)
        batch = _batch(db, batch_id, lock=True)
        if batch.sync_checkpoint != checkpoint:
            db.rollback()
            continue
        _guard_scope(db, batch)
        _guard_tenant(batch)
        try:
            if stage == "purchase":
                body = _purchase_result(batch, linked, checkpoint, detail)
            else:
                body = _receipt_result(db, batch, linked, checkpoint, detail)
        except (LinkedPurchaseError, PurchaseReadbackError, SyncConflict, WritebackConflict) as exc:
            _pause(batch, str(exc))
            db.commit()
            return batch
        if body is None:
            advanced = batch.sync_checkpoint["stage"] != stage
            if not advanced and batch.sync_status != "blocked":
                _pause(batch, "原请求尚未证实成功，需继续核对原单；本阶段不会补发")
            db.commit()
            if advanced:
                continue
            return batch

        attempt = checkpoint.get("attempt")
        if attempt is None:
            attempt = _new_attempt(batch, body)
        elif attempt["body"] != body:
            _pause(batch, "本阶段请求内容变化，请核对原单", status="blocked")
            db.commit()
            return batch
        db.commit()
        _dispatch(db, batch_id, stage, attempt, transport_factory)
        batch = _batch(db, batch_id)
        if batch.sync_status == "failed":
            db.rollback()
            return batch
        db.rollback()
    return _batch(db, batch_id)


def advance_batch(db, batch_id, *, transport_factory=None):
    """Advance provable stages or retain their last durable checkpoint for recovery."""
    try:
        return _advance(db, batch_id, transport_factory or OkkiTransport)
    except Exception:
        db.rollback()
        raise
