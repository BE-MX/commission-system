"""Authorized uncertain-result reconciliation; remote reads never hold authority."""
import logging
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now
from app.invoice import edit_authority, linked_sync_service as linked, lifecycle_remote, okki_client
from app.invoice import service, uncertain_recovery, xiaoman_service, order_push_facts, legacy_sending
from app.commerce_transition.models import SendingClaim, ClaimEvidence
from app.commerce_transition.service import digest
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.models import InvoiceLinkedSync
from app.invoice.push_attempt import allow_recovery
from app.receipt import remote
from app.semifinished.models import InvoiceAllocation

logger = logging.getLogger(__name__)


def original_claims(db, invoice, key):
    claims=db.scalars(select(SendingClaim).where(SendingClaim.invoice_id==invoice.id,
        SendingClaim.operation=='order_push').order_by(SendingClaim.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    selected=[claim for claim in claims if key and (claim.responsibilities or {}).get('task_key')==key]
    if any(claim.state in {'sending','unknown'} and claim not in selected for claim in claims):
        raise ValueError('存在其他未决原发送责任，不能清除订单保护')
    return selected


def claim_binding(db, invoice, key):
    return tuple((claim.id,claim.request_key,claim.route,claim.epoch,claim.payload_hash,claim.state,claim.external_id)
        for claim in original_claims(db,invoice,key))


def settle_original_claims(db, invoice, key, resolution, evidence=None, target=None, *, formal=False):
    claims=original_claims(db,invoice,key)
    if resolution=='confirm_not_created':
        # Neither an operator note nor an empty mirror can prove a POST absent.
        # Only immutable, definitive ORIGINAL results can permit a fresh create.
        if not claims:
            raise ValueError('没有原请求确定未发送凭证，历史单只能凭真实原单读回核对')
        for claim in claims:
            proof=db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id==claim.id)).all()
            if claim.state not in {'failed','not_sent'} or claim.external_id or not any(
                row.outcome==claim.state and row.external_id is None and
                (row.evidence or {}).get('definitive_original_request_result') is True for row in proof):
                raise ValueError('原发送结果未知，禁止以租约过期或查无记录解除保护')
        return
    for claim in claims:
        if claim.state in {'failed','not_sent'}:
            continue  # A conclusively rejected auth round is already closed.
        if claim.external_id and claim.external_id!=str(target):
            raise ValueError('核对结果与原发送远端身份不一致')
        legacy_sending.finish(db,claim.request_key,'succeeded',{
            'original_request_readback':True,'readback_sha256':digest(evidence),
            'review_resolution':resolution,'original_attempt_key':key},str(target))
        legacy_sending.observe_formal(db,claim.request_key,'legacy.order.push','accepted' if formal else 'unknown',
            result_row=invoice if formal else None,
            evidence_ref={'original_attempt_key':key,'readback_sha256':digest(evidence)})


def require_state(db, invoice, resolution, reason, *, target=None):
    ensure_active(invoice)
    allow_recovery(invoice)
    if invoice.sync_status != "sync_uncertain" or not reason.strip():
        raise ValueError("当前发票不处于待核对状态")
    row = None
    if invoice.linked_sync_id:
        row = db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.id == invoice.linked_sync_id)
            .with_for_update().execution_options(populate_existing=True))
        if row is None or row.invoice_id != invoice.id or row.status != "uncertain" or (row.lease_until and row.lease_until > beijing_now()):
            raise ValueError("原关联执行仍在进行或身份不完整")
    if resolution == "confirm_existing":
        if not invoice.xiaoman_order_id or len(reason.strip()) < 10:
            raise ValueError("仅已绑定订单可确认已有结果，请填写至少10字核对依据")
    elif invoice.xiaoman_order_id or row is not None:
        raise ValueError("仅无绑定的首次推送可使用此核对方式")
    order_push_facts.check_review(db, invoice, (invoice.sync_attempt or {}).get("attempt_key"),
                                  resolution, target if resolution == "bind_order" else invoice.xiaoman_order_id)
    return row


def capture(db, invoice, resolution, reason, target=None):
    row = require_state(db, invoice, resolution, reason, target=target)
    rows, _, issues, _ = xiaoman_service._build_product_rows(db, invoice, xiaoman_service.get_settings_row(db), editing=True, reconciling=True)
    if issues:
        raise ValueError("本地产品映射尚未完整核对")
    allocations = db.scalars(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id == invoice.id)
        .order_by(InvoiceAllocation.id).with_for_update().execution_options(populate_existing=True)).all()
    def state(record):
        return None if record is None else tuple(deepcopy(getattr(record, c.name)) for c in record.__table__.columns)
    binding = (edit_authority._binding(db, invoice), remote.invoice_binding(invoice), invoice.order_type,
        invoice.status, deepcopy(invoice.sync_attempt), deepcopy(invoice.cancellation), state(row),
        tuple(state(allocation) for allocation in allocations), deepcopy(rows),
        (invoice.sync_attempt or {}).get("attempt_key"),
        order_push_facts.observation_fingerprint(db, invoice.id, (invoice.sync_attempt or {}).get("attempt_key"))
        if (invoice.sync_attempt or {}).get("attempt_key") else None,
        claim_binding(db,invoice,(invoice.sync_attempt or {}).get('attempt_key')))
    return binding, rows


def current_response(db, invoice_id, user):
    invoice, _ = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:admin")
    result = service.serialize_detail(invoice)
    db.commit()
    return result


def late_context(db, invoice, resolution, reason, target):
    """Recover new facts after an earlier review without reactivating its attempt."""
    from app.invoice import order_sync_execution
    from app.invoice.lifecycle_guard import ensure_mutable
    ensure_mutable(db, invoice)
    linked.ensure_idle(invoice)
    from app.receipt.models import ReceiptIntent
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)
                       .with_for_update().execution_options(populate_existing=True))
    if intent and intent.attempt_token and intent.lease_until and intent.lease_until > beijing_now():
        raise ValueError("原回款意图执行租约尚未结束")
    if (invoice.sync_attempt or (invoice.status, invoice.sync_status) not in {("ready", "not_synced"), ("synced", "synced")}
            or service.validate_invoice(invoice) or len(reason.strip()) < 10):
        raise ValueError("当前执行或核对依据不允许处理迟到事实")
    pending = order_push_facts.unresolved(db, invoice)
    if len(pending) != 1:
        raise ValueError("原推单事实不唯一，请逐个核对执行身份")
    attempt = pending[0]
    key = attempt.safe_diff_json["attempt_key"]
    accepted = {row.safe_diff_json.get("provider_reference") for row in order_push_facts.observations(db, invoice.id, key)
                if row.safe_diff_json.get("result_class") == "accepted"}
    if len(accepted) != 1 or None in accepted:
        raise ValueError("没有唯一可信的已受理订单身份")
    reference = accepted.pop()
    if invoice.xiaoman_order_id:
        if resolution != "confirm_existing" or str(invoice.xiaoman_order_id) != reference:
            raise ValueError("迟到事实与当前绑定不同，禁止覆盖当前订单")
    elif resolution != "bind_order" or str(target) != reference:
        raise ValueError("迟到已受理事实只能绑定其原订单，不能宣称未创建")
    rows, _, line_issues, _ = xiaoman_service._build_product_rows(db, invoice, xiaoman_service.get_settings_row(db), editing=True, reconciling=True)
    if line_issues:
        raise ValueError("当前订单映射不完整")
    fingerprint = order_push_facts.observation_fingerprint(db, invoice.id, key)
    binding = (order_sync_execution.capture(db, invoice, rows), key, fingerprint)
    return binding, reference, rows, attempt


def resolve_late(db, invoice, user, resolution, reason, target):
    expected, reference, rows, attempt = late_context(db, invoice, resolution, reason, target)
    invoice_id, company_id, currency = invoice.id, str(invoice.customer_id), invoice.currency
    db.commit()
    try:
        evidence = lifecycle_remote.read(db, "order", reference)
        if (not isinstance(evidence, dict) or str(evidence.get("order_id")) != reference
                or str(evidence.get("company_id")) != company_id or evidence.get("currency") != currency):
            raise ValueError("Unverified original accepted order")
        evidence = deepcopy(evidence)
    except (ValueError, okki_client.OkkiApiError):
        logger.warning("Late order fact evidence unavailable")
        print("[invoice-sync] late order fact evidence unavailable", flush=True)
        raise HTTPException(503, "原已受理订单证据暂不可用，请稍后核对") from None
    finally:
        db.rollback(); db.expire_all()
    invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:admin")
    actual, _, current_rows, current_attempt = late_context(db, invoice, resolution, reason, target)
    if actual != expected:
        raise HTTPException(409, "核对期间订单或原事实集合已变化，请重新读取")
    validation_document = SimpleNamespace(xiaoman_order_id=reference, customer_id=invoice.customer_id,
        currency=invoice.currency, total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)
    validated = uncertain_recovery.verify_existing(validation_document, current_rows, evidence)
    key = current_attempt.safe_diff_json["attempt_key"]
    if not invoice.xiaoman_order_id:
        # This existing local resolver also checks the actual local company/name projection
        # and unique invoice binding. The temporary state is never independently committed.
        invoice.sync_status = "sync_uncertain"
        xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="bind_order", reason=reason,
            xiaoman_order_id=reference, operator_id=int(actor["id"]))
    _, binding, issues, _ = xiaoman_service._build_product_rows(db, invoice, xiaoman_service.get_settings_row(db), editing=True, reconciling=True)
    if issues or xiaoman_service._assign_unique_ids(invoice, binding, validated):
        raise ValueError("原已受理明细不能完整回写")
    settle_original_claims(db,invoice,key,resolution,evidence,reference)
    order_push_facts.review(db, invoice, key, resolution)
    from app.invoice.models import InvoiceSyncLog
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="push_fact_review", success=1,
        operator_id=int(actor["id"]), request_digest=reason.strip(),
        response_body="Original accepted order and frozen late observations verified",
        inventory_operation_key=current_attempt.safe_diff_json.get("inventory_operation_key")))
    db.commit()
    return current_response(db, invoice_id, user)


def resolve(db, invoice_id, user, *, resolution, reason, xiaoman_order_id=None, xiaoman_order_no=None):
    try:
        invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:admin")
        if resolution == "bind_order":
            target = xiaoman_service.binding_order(db, invoice, order_id=xiaoman_order_id,
                                                    order_no=xiaoman_order_no)
            xiaoman_order_id = str(target["order_id"])
        if invoice.sync_status != "sync_uncertain" and order_push_facts.unresolved(db, invoice):
            return resolve_late(db, invoice, user, resolution, reason, xiaoman_order_id)
        if resolution=='bind_order':
            expected,rows=capture(db,invoice,resolution,reason,xiaoman_order_id)
            identity=invoice.id
            validation_document=SimpleNamespace(xiaoman_order_id=xiaoman_order_id,customer_id=invoice.customer_id,
                currency=invoice.currency,total_amount=invoice.total_amount,surcharge_amount=invoice.surcharge_amount)
            name=invoice.invoice_no
            db.commit()
            try:
                evidence=lifecycle_remote.read(db,'order',xiaoman_order_id)
                if not isinstance(evidence,dict) or evidence.get('name')!=name:
                    raise ValueError('原订单名称读回与原绑定不一致')
                uncertain_recovery.verify_existing(validation_document,rows,evidence)
                evidence=deepcopy(evidence)
            finally:
                db.rollback();db.expire_all()
            invoice,actor=edit_authority.prepare_recovery(db,identity,user,'invoice:admin')
            actual,_=capture(db,invoice,resolution,reason,xiaoman_order_id)
            if actual!=expected:raise ValueError('核对期间原订单或发送证据已变化')
            original_key=(invoice.sync_attempt or {}).get('attempt_key')
            settle_original_claims(db,invoice,original_key,resolution,evidence,xiaoman_order_id)
            xiaoman_service.resolve_sync_uncertain(db,invoice,resolution=resolution,reason=reason,
                xiaoman_order_id=xiaoman_order_id,operator_id=int(actor['id']))
            order_push_facts.review(db,invoice,original_key,resolution)
            db.commit()
            return current_response(db,invoice_id,user)
        if resolution != "confirm_existing":
            # Validate the known accepted reference before any resolver writes.
            if resolution == "bind_order":
                order_push_facts.check_review(db, invoice, (invoice.sync_attempt or {}).get("attempt_key"), resolution, xiaoman_order_id)
            require_state(db, invoice, resolution, reason, target=xiaoman_order_id)
            original_key=(invoice.sync_attempt or {}).get("attempt_key")
            settle_original_claims(db,invoice,original_key,resolution)
            xiaoman_service.resolve_sync_uncertain(db, invoice, resolution=resolution, reason=reason,
                xiaoman_order_id=xiaoman_order_id, operator_id=int(actor["id"]))
            order_push_facts.review(db,invoice,original_key,resolution)
            db.commit()
            return current_response(db, invoice_id, user)
        expected, rows = capture(db, invoice, resolution, reason)
        target = invoice.xiaoman_order_id
        db.commit()  # Read-only authorization, state and product mapping capture.
        try:
            evidence = lifecycle_remote.read(db, "order", target)
            if not isinstance(evidence, dict) or str(evidence.get("order_id")) != str(target):
                raise ValueError("Unverified remote order identity")
            evidence = deepcopy(evidence)
        except (ValueError, okki_client.OkkiApiError):
            logger.warning("Uncertain order recovery evidence unavailable")
            print("[invoice-sync] recovery evidence unavailable", flush=True)
            raise HTTPException(503, "原订单证据暂不可用，请稍后核对") from None
        finally:
            db.rollback()
            db.expire_all()
        invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:admin")
        actual, _ = capture(db, invoice, resolution, reason)
        if actual != expected:
            raise HTTPException(409, "核对期间订单、映射或原执行任务已变化，请重新读取")
        original_key=(invoice.sync_attempt or {}).get("attempt_key")
        settle_original_claims(db,invoice,original_key,resolution,evidence,target)
        uncertain_recovery.confirm_existing(db, invoice, reason, int(actor["id"]), evidence=evidence)
        order_push_facts.review(db,invoice,original_key,resolution)
        db.commit()
        return current_response(db, invoice_id, user)
    except ValueError:
        db.rollback()
        logger.warning("Uncertain order recovery rejected by current state or evidence")
        print("[invoice-sync] recovery rejected by current state or evidence", flush=True)
        raise HTTPException(409, "当前订单、原任务或远端证据不允许解除保护，请重新核对", headers={"Cache-Control":"private, no-store"}) from None
    except HTTPException as error:
        error.headers = {**(error.headers or {}), "Cache-Control":"private, no-store"}
        raise
