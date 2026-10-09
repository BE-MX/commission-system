"""Void a demonstrably local PI without deleting business evidence or calling OKKI."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4
import json

from sqlalchemy import select

from app.core.time import beijing_now
from app.invoice import lifecycle_guard, linked_sync_service
from app.invoice.delegation_service import can_act_for
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.portal import admin_service as admin, quote_service
from app.portal.access_policy import validate_binding
from app.portal.domain import content_hash, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, Conversion, CustomerAccess, OrderRequest, OutboxEvent


def context(db,actor_id,public_id):
    admin.begin(db,actor_id,"portal_order:write")
    admin.employee_principal(db,actor_id,"invoice:write")
    site = admin.site_for_admin(db)
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id==str(public_id))
        .with_for_update().execution_options(populate_existing=True))
    access = None if order is None else db.get(CustomerAccess,order.access_id,populate_existing=True)
    if access is None or access.site_id != site.id or not can_act_for(db,actor_id,access.sales_user_id):
        reject("RESOURCE_NOT_FOUND","请求不存在或不在当前操作范围。",404)
    validate_binding(db,access)
    if access.okki_namespace != quote_service.get_settings().PORTAL_OKKI_NAMESPACE:
        reject("PI_VOID_REQUIRES_REVIEW","客户来源配置已变化，请先核对原PI归属。",409)
    conversion = db.scalar(select(Conversion).where(Conversion.request_id==order.id)
        .with_for_update().execution_options(populate_existing=True))
    invoice = None if conversion is None else db.scalar(select(Invoice).where(Invoice.id==conversion.invoice_id)
        .with_for_update().execution_options(populate_existing=True))
    if (invoice is None or order.status != "invoice_created" or order.invoice_id != invoice.id
            or invoice.source_type != "portal" or invoice.source_order_id != order.public_id
            or invoice.customer_id != access.okki_company_id or order.okki_company_id_snapshot != access.okki_company_id
            or order.customer_id_snapshot != access.customer_id or not can_act_for(db,actor_id,invoice.sales_user_id)):
        reject("RESOURCE_NOT_FOUND","PI不存在或当前身份/归属需要复核。",404)
    return access,order,conversion,invoice


def require_local_idle(db,invoice):
    if (invoice.xiaoman_order_id or invoice.synced_at or invoice.sync_status not in {"not_synced","sync_failed"}
            or invoice.status not in {"draft","ready","sync_failed"}
            or invoice.sync_attempt or invoice.linked_sync_id or invoice.order_type != "stock"
            or (invoice.cancellation and invoice.cancellation.get("status") != "aborted")):
        reject("PI_VOID_REQUIRES_REVIEW","PI已同步、同步结果待核对或存在处理任务，请走方舟取消核对流程。",409)
    try:
        linked_sync_service.ensure_idle(invoice)
        lifecycle_guard.ensure_mutable(db,invoice)
    except ValueError:
        reject("PI_VOID_REQUIRES_REVIEW","PI存在进行中业务，请先完成方舟核对。",409)
    if db.scalar(select(OkkiOutboundTask.id).where(OkkiOutboundTask.invoice_id==invoice.id).with_for_update().limit(1)) is not None:
        reject("PI_VOID_REQUIRES_REVIEW","PI已有出库任务记录，请先核对出库。",409)
    if db.scalar(select(Receipt.id).where(Receipt.invoice_id==invoice.id,Receipt.status=="active").with_for_update().limit(1)) is not None:
        reject("PI_VOID_REQUIRES_REVIEW","PI存在有效回款，请先核对财务处理。",409)
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if intent is not None and (intent.status != "draft" or intent.attempt_token or intent.receipt_id or intent.lease_until):
        reject("PI_VOID_REQUIRES_REVIEW","自动回款意图等待处理，请先核对。",409)
    allocations = db.scalars(select(InvoiceAllocation).where(InvoiceAllocation.invoice_id==invoice.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    if any(row.status=="pending" or Decimal(row.allocated_qty_grams or 0)!=0 or Decimal(row.pending_delta_grams or 0)!=0 for row in allocations):
        reject("PI_VOID_REQUIRES_REVIEW","存在半成品占用或待恢复库存，请先核对。",409)
    return intent


def void(db,actor_id,public_id,expected,body):
    access,order,conversion,invoice = context(db,actor_id,public_id)
    digest = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action=="pi_voided",
        CommandReceipt.object_public_id==order.public_id,CommandReceipt.command_key=="local-void"))
    if saved is not None:
        if saved.payload_hash != digest:
            reject("IDEMPOTENCY_CONFLICT","该PI已通过其他作废命令处理，请查看原记录。",409)
        return {"replayed":True,"original_receipt":deepcopy(saved.result_reference_json),
            "current_state":order.status,"invoice_status":invoice.status,"row_version":order.row_version}
    quote_service.require_writes()
    require_version(order.row_version,expected)
    require_version(invoice.portal_document_version,body.invoice_document_version)
    if conversion.status != "created":
        reject("PI_VOID_REQUIRES_REVIEW","该PI关联已终止，请查看原处理记录。",409)
    intent = require_local_idle(db,invoice)
    before = order.row_version
    now = beijing_now()
    invoice.status = "cancelled"
    invoice.updated_by = actor_id
    invoice.cancellation = {"status":"retained","mode":"local_void","reason":body.reason,"created_by":actor_id,
        "updated_at":now.isoformat(),"evidence":{"remote_exists":False},
        "message":"未同步PI已本地作废；保留发票、请求、回款草稿和审计，未调用外部系统。"}
    if intent is not None:
        intent.eligible = 0  # Retain draft values/attachments; no future automatic arming.
    conversion.status = "tombstoned"
    order.row_version += 1
    db.flush()  # The lifecycle hook withdraws publications and increments the PI version atomically.
    result = {"request_id":order.public_id,"invoice_id":invoice.id,"invoice_status":"cancelled",
        "invoice_document_version":invoice.portal_document_version,"row_version":order.row_version,"completed_at":now.isoformat()}
    db.add(CommandReceipt(action="pi_voided",object_public_id=order.public_id,command_key="local-void",
        payload_hash=digest,result_reference_json=result,first_actor_type="employee",first_actor_id=actor_id,completed_at=now))
    db.add(AuditEvent(actor_type="employee",actor_id=actor_id,access_id=access.id,object_type="order_request",
        object_public_id=order.public_id,action="order.pi_voided",before_version=before,after_version=order.row_version,
        reason=body.reason,trace_id=str(uuid4()),safe_diff_json={"invoice_id":invoice.id,"invoice_status":"cancelled"}))
    db.add(InvoiceSyncLog(invoice_id=invoice.id,action="portal_void",success=1,operator_id=actor_id,
        request_digest=json.dumps({"request_id":order.public_id,"reason":body.reason},ensure_ascii=False)))
    db.add(OutboxEvent(event_key="order.pi_voided:"+order.public_id,event_type="order_pi_voided",
        aggregate_public_id=order.public_id,payload_json={"request_id":order.public_id},next_attempt_at=now))
    db.flush()
    return {"replayed":False,"original_receipt":result,"current_state":order.status,
        "invoice_status":invoice.status,"row_version":order.row_version}
