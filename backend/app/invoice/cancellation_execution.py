"""Authorized once-only cancellation effects and independently committed facts."""
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.invoice import cancellation_service as cancel, cancellation_facts as facts
from app.invoice import edit_authority, lifecycle_remote, okki_client
from app.portal.access_policy import employee_principal
from app.portal.authority import lock_authority
from app.portal.errors import PortalError

logger = logging.getLogger(__name__)


def unavailable(message):
    logger.warning("Cancellation execution requires reconciliation")
    print("[invoice-cancel] execution requires reconciliation", flush=True)
    raise HTTPException(503, message, headers={"Cache-Control":"no-store"}) from None


def authorize(db, invoice_id, user):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "取消授权必须从新事务开始")
    db.expire_all()
    try:
        lock_authority(db, force=True)
        actor = int(user.get("id") or user.get("sub") or 0)
        current = employee_principal(db, actor, "invoice:admin")
    except (TypeError, ValueError):
        raise HTTPException(403, "无法确认当前操作人") from None
    except PortalError as error:
        raise HTTPException(error.status, "当前账号无权核对或取消发票") from None
    invoice = edit_authority.lock_document(db, invoice_id, force=True)
    edit_authority._visible(db, invoice, current)
    return invoice, current


def public_result(db, invoice_id, user):
    invoice, current = authorize(db, invoice_id, user)
    result = {**cancel.public_state(invoice.cancellation), "recovery_summary":facts.summary(db, invoice)}
    db.commit()
    return result


def persist_result(db, attempt, observations):
    """Trusted original execution, never a new employee authorization or effect."""
    for retry in range(3):
        db.rollback()
        db.expire_all()
        try:
            lock_authority(db, force=True)
            invoice = edit_authority.lock_document(db, attempt.invoice_id, force=True)
            facts.record(db, attempt, observations)
            state = invoice.cancellation or {}
            binding = edit_authority._binding(db, invoice)
            if facts.completed(db, attempt, invoice, binding):
                db.commit()
                return True
            owns = (state.get("status") == "deleting" and state.get("attempt_key") == attempt.key
                and state.get("token") == attempt.token and state.get("lease_until")
                and datetime.fromisoformat(state["lease_until"]) > beijing_now()
                and binding == attempt.binding)
            if owns:
                readback = next(fact for fact in observations if fact["effect_kind"] == "readback_observation")
                local, count = cancel.local_evidence(db, invoice.id, for_update=True)
                absent = readback["evidence"] == "absent"
                completed = absent and not local
                evidence = {**(state.get("evidence") or {}), "local_receipt_count":count, "blockers":local}
                invoice.cancellation = {**state, "status":"remote_deleted" if completed else "uncertain", "evidence":evidence,
                    "updated_at":beijing_now().isoformat(), "message":
                    "已核实远端订单不存在，方舟记录保留" if completed else "原执行结果仍需核对，不会重发删除"}
                if completed:
                    invoice.status = "cancelled"
                cancel.audit(db, invoice, "cancel_step", attempt.actor_id, invoice.cancellation)
                if readback["evidence"] in {"absent", "present"}:
                    facts.reconcile(db, invoice, readback["evidence"], None, attempt_keys={attempt.key})
                db.flush()
                facts.finish(db, attempt, invoice, edit_authority._binding(db, invoice))
            db.commit()  # Facts persist before any response authorization.
            return owns
        except (SQLAlchemyError, PortalError, ValueError):
            db.rollback()
            logger.warning("Cancellation fact persistence retry %s", retry + 1)
            print(f"[invoice-cancel] fact persistence retry {retry + 1}", flush=True)
    unavailable("执行事实暂未完成保存，请按原任务核对，禁止重复删除")


def remove_authorized(db, invoice_id, user):
    invoice, current = authorize(db, invoice_id, user)
    state = deepcopy(invoice.cancellation)
    if not state:
        raise HTTPException(409, "请先发起取消")
    if state.get("status") in cancel.TERMINAL:
        result = {**cancel.public_state(state), "recovery_summary":facts.summary(db, invoice)}
        db.commit()
        return result
    if state.get("status") in {"deleting", "uncertain"} or facts.capture(db, invoice):
        db.rollback()
        return cancel.refresh_authorized(db, invoice_id, user)
    expected = (edit_authority._binding(db, invoice), state)
    captured = SimpleNamespace(**{key:deepcopy(getattr(invoice, key)) for key in
        ("id", "customer_id", "currency", "xiaoman_order_id", "cancellation")})
    db.commit()
    try:
        api_token = okki_client.ensure_access_token(db)
        proof = cancel.inspect(db, captured)
    except (ValueError, okki_client.OkkiApiError):
        unavailable("取消取证暂不可用，请重新核对")
    finally:
        db.rollback()
        db.expire_all()
    invoice, current = authorize(db, invoice_id, user)
    if (edit_authority._binding(db, invoice), invoice.cancellation) != expected:
        raise HTTPException(409, "发票或原取消绑定已变化，请重新读取")
    if invoice.status != "cancel_pending" or state.get("status") not in {"pending", "blocked"}:
        raise HTTPException(409, "当前取消流程不可执行")
    proof["blockers"] = ([] if not proof["outbounds"] else ["仍有关联远端出库单"])
    if proof["remote_receipt_count"]:
        proof["blockers"].append("仍有关联远端回款")
    local, count = cancel.local_evidence(db, invoice.id, for_update=True)
    proof["blockers"].extend(local)
    proof["local_receipt_count"] = count
    if proof["blockers"]:
        cancel.save(db, invoice, {"status":"blocked", "evidence":proof}, current["id"], "存在阻塞，未发送删除")
        return public_result(db, invoice_id, user)
    if not proof["remote_exists"]:
        invoice.status = "cancelled"
        cancel.save(db, invoice, {"status":"remote_deleted", "evidence":proof}, current["id"], "远端已不存在，方舟记录保留")
        return public_result(db, invoice_id, user)
    # Recheck durable history in the final claim transaction, not only capture.
    if facts.capture(db, invoice):
        raise HTTPException(409, "已有原执行记录，禁止再次删除")
    token = uuid4().hex
    attempt = facts.start(db, invoice, expected[0], token, int(current["id"]))
    invoice.cancellation = {**state, "status":"deleting", "token":token, "attempt_key":attempt.key,
        "lease_until":(beijing_now()+timedelta(minutes=5)).isoformat(), "evidence":proof,
        "updated_at":beijing_now().isoformat(), "message":"原执行意图已保存，等待远端结果"}
    cancel.audit(db, invoice, "cancel_step", attempt.actor_id, invoice.cancellation)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        unavailable("原执行提交待核对，未继续发送删除，请读取原任务")
    observations = []
    try:
        result = lifecycle_remote.request(api_token, "order", attempt.target, remove=True)
        observations.append(facts.observation(attempt, "delete_response",
            "succeeded" if result is True else "unknown", "accepted" if result is True else "unavailable"))
    except (okki_client.OkkiApiError, ValueError):
        logger.warning("Cancellation delete response unavailable")
        print("[invoice-cancel] delete response unavailable", flush=True)
        observations.append(facts.observation(attempt, "delete_response", "unknown", "unavailable"))
    try:
        after = lifecycle_remote.request(api_token, "order", attempt.target)
        if after is not None and (not isinstance(after, dict) or str(after.get("order_id")) != attempt.target):
            raise ValueError("Unverified remote identity")
        observations.append(facts.observation(attempt, "readback_observation",
            "succeeded" if after is None else "failed", "absent" if after is None else "present"))
    except (okki_client.OkkiApiError, ValueError):
        logger.warning("Cancellation readback unavailable")
        print("[invoice-cancel] readback unavailable", flush=True)
        observations.append(facts.observation(attempt, "readback_observation", "unknown", "unavailable"))
    owns = persist_result(db, attempt, tuple(observations))
    result = public_result(db, invoice_id, user)
    if not owns:
        raise HTTPException(409, "原执行事实已保存，执行权已变化，请核对当前任务")
    return result
