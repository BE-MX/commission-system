"""Current authorized ordinary order claims, lock-free POST and original facts."""
import logging
import json
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.invoice import edit_authority, linked_sync_service as linked, okki_client
from app.invoice import order_push_facts as facts, product_service, service, uncertain_recovery, xiaoman_service, outbound_task_service
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import OkkiOutboundTask, InvoiceLinkedSync
from app.portal.authority import lock_authority
from app.portal.errors import PortalError
from app.receipt import invoice_link
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment
from app.semifinished import invoice_service as inventory
from app.semifinished.models import InvoiceAllocation

logger=logging.getLogger(__name__)


def unavailable():
    logger.warning("Order push evidence requires recovery")
    print("[invoice-push] evidence requires recovery", flush=True)
    raise HTTPException(503,"原推单记录暂不可核对，请读取原任务，禁止重复推送") from None


def rows(db,model,invoice_id):
    return db.scalars(select(model).where(model.invoice_id==invoice_id).order_by(model.id)
                      .with_for_update().execution_options(populate_existing=True)).all()


def state(row):
    return tuple(deepcopy(getattr(row,c.name)) for c in row.__table__.columns
                 if c.name not in {"created_at","updated_at"})


def capture(db,invoice,payload):
    dependencies=tuple(tuple(state(row) for row in rows(db,model,invoice.id))
                       for model in (Receipt,ReceiptIntent,InvoiceAllocation,OkkiOutboundTask))
    if invoice.linked_sync_id:
        dependencies += (tuple(state(row) for row in rows(db,InvoiceLinkedSync,invoice.id)),)
    proof_ids={identity for row in rows(db,ReceiptIntent,invoice.id) for identity in (row.attachment_ids or [])}
    proofs=db.scalars(select(ReceiptAttachment).where(or_(ReceiptAttachment.invoice_id==invoice.id,
                      ReceiptAttachment.id.in_(proof_ids))).order_by(ReceiptAttachment.id)
                      .with_for_update().execution_options(populate_existing=True)).all()
    return (state(invoice),tuple(state(item) for item in invoice.items),deepcopy(payload),dependencies,
            tuple(state(proof) for proof in proofs))


def prepare(db,invoice_id,user,linked_id=None,linked_token=None):
    invoice,actor=edit_authority.prepare_recovery(db,invoice_id,user,"invoice:sync")
    linked.ensure_idle(invoice,linked_id);ensure_mutable(db,invoice)
    if linked_id:linked.ensure_running(db,invoice,linked_id,linked_token)
    if facts.unresolved(db,invoice):raise HTTPException(409,"原推单存在未核对执行记录，请先恢复原任务")
    if service.validate_invoice(invoice):raise HTTPException(409,"发票未通过同步前校验")
    for item in invoice.items:
        if item.xiaoman_unique_id is not None:
            uncertain_recovery._canonical_uid(item.xiaoman_unique_id)
    removed = json.loads(invoice.xiaoman_removed_lines or "[]")
    if not isinstance(removed, list) or any(not isinstance(row, dict) for row in removed):
        raise ValueError("Invalid removed line identity snapshot")
    removed_ids = [uncertain_recovery._canonical_uid(row.get("unique_id")) for row in removed]
    if len(removed_ids) != len(set(removed_ids)):
        raise ValueError("Duplicate removed line identity")
    # Local projection reconciliation; no external I/O or preparatory invoice claim.
    try:
        with db.begin_nested():product_service.reconcile_custom_products(db)
    except (ValueError,TypeError):
        logger.warning("Local product reconciliation unavailable; existing generic mapping retained")
        print("[invoice-push] local product reconciliation unavailable", flush=True)
    payload,_,issues=xiaoman_service.build_push_payload(db,invoice)
    if issues:raise HTTPException(409,"产品映射、业务归属或推单设置尚未完整核对")
    identifiers=[row["unique_id"] for row in payload["product_list"] if row.get("unique_id")]
    if len(identifiers)!=len(set(identifiers)):
        raise HTTPException(409,"原推单明细身份重复，请先核对")
    expected=capture(db,invoice,payload)
    db.commit()
    return expected,deepcopy(payload)


def token(db,force=False):
    try:
        value=okki_client.ensure_access_token(db,force=force)
        db.commit()  # Only provider credential cache; no authority, invoice or stock locks.
        return value
    except (ValueError,okki_client.OkkiApiError,SQLAlchemyError):
        unavailable()
    finally:
        db.rollback();db.expire_all()


def claim(db,invoice_id,user,expected,payload,linked_id=None,linked_token=None):
    invoice,actor=edit_authority.prepare_recovery(db,invoice_id,user,"invoice:sync")
    linked.ensure_idle(invoice,linked_id);ensure_mutable(db,invoice)
    if linked_id:linked.ensure_running(db,invoice,linked_id,linked_token)
    current_payload,_,issues=xiaoman_service.build_push_payload(db,invoice)
    if issues or capture(db,invoice,current_payload)!=expected or facts.unresolved(db,invoice):
        raise HTTPException(409,"取证期间发票、映射或本地执行资料已变化")
    if xiaoman_service._screenshot_sync_issue(db,invoice):raise HTTPException(409,"截图订单身份查重未通过")
    receipt_token=invoice_link.arm(db,invoice,int(actor["id"]))
    operation_key=inventory.prepare_invoice_sync(db,invoice,int(actor["id"]),commit=False)
    inventory.ensure_pending_matches_invoice(db,invoice,operation_key)
    invoice.sync_status=invoice.status="sync_uncertain"
    invoice.sync_attempt={"token":uuid4().hex,"attempt_key":str(uuid4()),
                          "lease_until":(beijing_now()+timedelta(minutes=5)).isoformat()}
    db.flush()
    binding=capture(db,invoice,current_payload)
    attempt=facts.start(db,invoice,int(actor["id"]),binding,payload,operation_key,receipt_token)
    try:db.commit()
    except SQLAlchemyError:
        db.rollback();unavailable()
    return attempt


def owns(db,invoice,attempt):
    current=invoice.sync_attempt or {}
    if (current.get("token")!=attempt.token or current.get("attempt_key")!=attempt.key
            or not current.get("lease_until") or datetime.fromisoformat(current["lease_until"])<=beijing_now()
            or invoice.status in {"cancel_pending","cancelled"}):
        return False
    if invoice.linked_sync_id:
        task=db.get(InvoiceLinkedSync,invoice.linked_sync_id)
        if not task or task.status!="running" or not task.lease_until or task.lease_until<=beijing_now():return False
    payload,_,issues=xiaoman_service.build_push_payload(db,invoice)
    return not issues and capture(db,invoice,payload)==attempt.binding


def authorize_retry(db,attempt,user):
    invoice,actor=edit_authority.prepare_recovery(db,attempt.invoice_id,user,"invoice:sync")
    facts.validate(db,attempt)
    if not owns(db,invoice,attempt):raise HTTPException(409,"原执行权或完整绑定已变化，停止重发")
    db.commit()


def send(api_token,attempt,round_number):
    try:
        result=okki_client._post_json("/v1/invoices/order/push",api_token,deepcopy(attempt.payload),context="订单推送")
        if result is None:return facts.observation(attempt,round_number,"auth_rejected"),None
        if not isinstance(result,dict):return facts.observation(attempt,round_number,"unknown"),None
        try:
            reference=uncertain_recovery._canonical_uid(result.get("order_id"))
            original=attempt.data["original_order_id"]
            if original and reference!=str(original):raise ValueError("Wrong original order identity")
        except ValueError:return facts.observation(attempt,round_number,"unknown",response=result),None
        return facts.observation(attempt,round_number,"accepted",reference,result),deepcopy(result)
    except okki_client.OkkiOutcomeUncertainError:
        return facts.observation(attempt,round_number,"unknown"),None
    except okki_client.OkkiApiError:
        return facts.observation(attempt,round_number,"rejected"),None
    except Exception:
        logger.warning("Order push result unavailable")
        print("[invoice-push] result unavailable", flush=True)
        return facts.observation(attempt,round_number,"unknown"),None


def verified_response(attempt,data):
    response_rows=data.get("product_list")
    if not isinstance(response_rows,list) or any(not isinstance(row,dict) for row in response_rows):
        raise ValueError("Missing response product identities")
    normalized=[{**row,"unique_id":uncertain_recovery._canonical_uid(row.get("unique_id"))} for row in response_rows]
    if len({row["unique_id"] for row in normalized})!=len(normalized):raise ValueError("Duplicate product identity")
    sent=[row for row in attempt.payload["product_list"] if not row.get("remove")]
    if sorted((str(r.get("product_id")),str(r.get("sku_id"))) for r in normalized)!=sorted((str(r["product_id"]),str(r["sku_id"])) for r in sent):
        raise ValueError("Unverified response products")
    by_id={row["unique_id"]:row for row in normalized}
    if any(row.get("unique_id") and (str(row["unique_id"]) not in by_id
           or (str(row["product_id"]),str(row["sku_id"])) !=
              (str(by_id[str(row["unique_id"])].get("product_id")),str(by_id[str(row["unique_id"])].get("sku_id")))) for row in sent):
        raise ValueError("Reassigned original product identity")
    return normalized


def apply(db,invoice,attempt,observation,data):
    result_class=observation["result_class"]
    result={"ok":False,"message":"原订单推送结果待核对，禁止自动重发","issues":[],
            "xiaoman_order_id":invoice.xiaoman_order_id}
    if result_class=="accepted":
        invoice.xiaoman_order_id=observation["provider_reference"]
        # Save known acceptance even when UID or stock finalization still needs recovery.
        xiaoman_service._write_sync_log(db,invoice,action=attempt.data["action"],success=True,
            payload={xiaoman_service.FIELD_NEW_DEAL: attempt.payload.get(xiaoman_service.FIELD_NEW_DEAL)},
            response={"order_id":invoice.xiaoman_order_id,"attempt_reference":attempt.key},
            error=None,operator_id=attempt.actor_id,inventory_operation_key=attempt.inventory_key)
        try:
            validated=verified_response(attempt,data)
            _,binding,issues,_=xiaoman_service._build_product_rows(db,invoice,xiaoman_service.get_settings_row(db),editing=True)
            if issues or xiaoman_service._assign_unique_ids(invoice,binding,validated):raise ValueError("Incomplete local assignment")
            with db.begin_nested():inventory.finalize_invoice_sync(db,invoice.id,attempt.inventory_key,attempt.actor_id)
        except (ValueError,RuntimeError,SQLAlchemyError):
            result.update(okki_accepted=True,inventory_pending=bool(attempt.inventory_key),
                          xiaoman_order_id=invoice.xiaoman_order_id)
            invoice.sync_error=result["message"]
            invoice_link.finish_attempt(db,invoice,attempt.receipt_token)
            return result
        invoice.sync_status=invoice.status="synced";invoice.synced_at=beijing_now();invoice.sync_error=None
        invoice.sync_attempt=None
        sent_removals=[row for row in attempt.payload["product_list"] if row.get("remove")]
        if sent_removals:invoice.xiaoman_removed_lines=None
        if attempt.data["action"]=="create" and xiaoman_service.get_settings().OKKI_OUTBOUND_AUTO_ENABLED:
            invoice.outbound_auto_requested=int(invoice.order_type!="presale")
            outbound_task_service.enqueue_outbound_task(db,invoice)
        elif attempt.data["action"]=="update":
            outbound_task_service.requeue_waiting_stock_after_invoice_sync(db,invoice)
        result.update(ok=True,message="已同步到小满",xiaoman_order_id=invoice.xiaoman_order_id)
        result.update(invoice_link.mark_success(db,invoice,attempt.receipt_token))
    elif result_class in {"rejected","auth_rejected"}:
        with db.begin_nested():inventory.release_invoice_sync(db,invoice.id,attempt.inventory_key,attempt.actor_id)
        invoice.sync_status=invoice.status="sync_failed";invoice.sync_attempt=None
        invoice.sync_error="小满明确拒绝原推单，请核对后重试"
        invoice_link.release_rejected(db,invoice,attempt.receipt_token)
        result["message"]=invoice.sync_error
        xiaoman_service._write_sync_log(db,invoice,action=attempt.data["action"],success=False,payload=None,
            response=None,error=invoice.sync_error,operator_id=attempt.actor_id,inventory_operation_key=attempt.inventory_key)
    else:
        invoice.sync_error=result["message"]
        result["inventory_pending"]=bool(attempt.inventory_key)
        xiaoman_service._write_sync_log(db,invoice,action=attempt.data["action"],success=False,
            payload=None,response=None,error=invoice.sync_error,operator_id=attempt.actor_id,
            inventory_operation_key=attempt.inventory_key)
    invoice_link.finish_attempt(db,invoice,attempt.receipt_token)
    return result


def record_original(db,attempt,observations):
    for retry in range(3):
        db.rollback();db.expire_all()
        try:
            lock_authority(db,force=True)
            edit_authority.lock_document(db,attempt.invoice_id,force=True)
            facts.validate(db,attempt)
            for observation in observations:facts.record(db,attempt,observation)
            db.commit()
            return
        except (SQLAlchemyError,PortalError,ValueError):
            db.rollback();logger.warning("Order push fact persistence retry %s",retry+1)
            print(f"[invoice-push] fact persistence retry {retry+1}", flush=True)
    unavailable()


def persist(db,attempt,observations,data,*,finish=True):
    record_original(db,attempt,observations)  # Facts independently commit before business application.
    if not finish:return None
    for retry in range(3):
        db.rollback();db.expire_all()
        try:
            invoice,actor=edit_authority.prepare_recovery(db,attempt.invoice_id,{"id":attempt.actor_id},"invoice:sync")
            facts.validate(db,attempt)
            completed=facts.get(db,invoice.id,attempt.key,facts.FINISH)
            if completed and completed.safe_diff_json.get("final_fingerprint")==facts.digest(capture(db,invoice,xiaoman_service.build_push_payload(db,invoice)[0])):
                db.commit();return completed.safe_diff_json["result"]
            owned=owns(db,invoice,attempt)
            result=apply(db,invoice,attempt,observations[-1],data) if owned else {
                "ok":False,"message":"原推单事实已保存，执行权已变化，请核对当前任务","issues":[],
                "xiaoman_order_id":invoice.xiaoman_order_id,"execution_changed":True}
            db.flush()
            db.refresh(invoice)  # Freeze persisted DATETIME precision for commit-ack recovery.
            payload=xiaoman_service.build_push_payload(db,invoice)[0]
            final=facts.digest(capture(db,invoice,payload))
            facts.append(db,invoice.id,attempt.key,facts.FINISH,{"result":result,"final_fingerprint":final,
                "resolved":owned and (bool(result.get("ok")) or observations[-1]["result_class"] in {"rejected","auth_rejected"}),
                "observation_fingerprint":facts.observation_fingerprint(db,invoice.id,attempt.key)},
                attempt.object_id,attempt.access_id)
            db.commit();return result
        except (SQLAlchemyError,PortalError,ValueError):
            db.rollback();logger.warning("Order push business recovery retry %s",retry+1)
            print(f"[invoice-push] business recovery retry {retry+1}", flush=True)
    unavailable()


def response(db,invoice_id,user,result):
    _,actor=edit_authority.prepare_recovery(db,invoice_id,user,"invoice:sync")
    db.commit()
    return result


def run(db,invoice_id,user,*,linked_id=None,linked_token=None,follow_outbound=True):
    try:
        expected,payload=prepare(db,invoice_id,user,linked_id,linked_token)
        api_token=token(db)
        attempt=claim(db,invoice_id,user,expected,payload,linked_id,linked_token)
        observations=[]
        observation,data=send(api_token,attempt,1);observations.append(observation)
        if observation["result_class"]=="auth_rejected":
            persist(db,attempt,tuple(observations),None,finish=False)
            try:
                api_token=token(db,force=True);authorize_retry(db,attempt,user)
            except HTTPException:
                persist(db,attempt,tuple(observations),None)
                raise
            observation,data=send(api_token,attempt,2);observations.append(observation)
        result=persist(db,attempt,tuple(observations),data)
        if result.get("ok") and follow_outbound:
            # Preserve the existing continuation; its executor remains separately audited.
            invoice,actor=edit_authority.prepare_recovery(db,invoice_id,user,"invoice:sync")
            db.commit()
            from app.invoice import outbound_followup_service
            result["outbound_sync"]=outbound_followup_service.safely_run(db,invoice,actor,force_authority=True)
            db.rollback();db.expire_all()
        return response(db,invoice_id,user,result)
    except ValueError:
        db.rollback()
        logger.warning("Current invoice, inventory or receipt state rejects order push")
        print("[invoice-push] current state rejects push", flush=True)
        raise HTTPException(409,"当前订单、库存或回款资料不允许推送",headers={"Cache-Control":"private, no-store"}) from None
    except HTTPException as error:
        error.headers={**(error.headers or {}),"Cache-Control":"private, no-store"}
        raise
