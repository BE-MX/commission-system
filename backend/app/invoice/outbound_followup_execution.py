"""Ordinary push continuation: unlocked evidence and current-authorized queue writes."""
import json
import logging
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import edit_authority, linked_sync_service as linked, order_push_facts as facts
from app.invoice import order_sync_execution as push, outbound_followup_service as legacy
from app.invoice import outbound_task_service as tasks, uncertain_recovery, xiaoman_service
from app.invoice.cancellation_service import audit
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import InvoiceSyncLog, OkkiOutboundTask
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)


def reject(status, message):
    raise HTTPException(status, message, headers={"Cache-Control": "private, no-store"}) from None


def row_state(row):
    return None if row is None else tuple(deepcopy(getattr(row, c.name)) for c in row.__table__.columns)


def verify_generation_target(row, invoice):
    try:
        result = json.loads(row.response_body or "null")
        if not isinstance(result, dict) or uncertain_recovery._canonical_uid(result.get("order_id")) != str(invoice.xiaoman_order_id):
            raise ValueError("Generation belongs to another original target")
    except (ValueError, TypeError, AttributeError):
        reject(409, "原推单代次缺少当前订单的可信引用")


def capture(db, invoice, *, worker_capture=False):
    linked.ensure_idle(invoice)
    if worker_capture:
        # Read-only worker capture may inspect its own running task; ownership is
        # subsequently proved from immutable START/checkpoints before any action.
        from app.invoice.lifecycle_guard import ensure_active
        from app.shipping_inspection.outbound_sync_state import ensure_invoice_idle
        from app.receipt.models import Receipt
        ensure_active(invoice);ensure_invoice_idle(db,invoice)
        if db.query(Receipt.id).filter(Receipt.invoice_id==invoice.id,Receipt.status=='active',
                Receipt.sync_status.in_(['syncing','uncertain'])).first():
            reject(409,'原回款正在发送或结果待核对')
    else:
        ensure_mutable(db, invoice)
    if invoice.sync_status != "synced" or not invoice.xiaoman_order_id or facts.unresolved(db, invoice):
        reject(409, "原订单或执行事实尚未完整核对，不能推进出库")
    payload, _, issues = xiaoman_service.build_push_payload(db, invoice)
    if issues:
        reject(409, "原订单产品或归属尚未完整核对")
    product_rows, _, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues:
        reject(409, "原订单产品映射尚未完整核对")
    for item in invoice.items:
        if item.xiaoman_unique_id is not None:
            uncertain_recovery._canonical_uid(item.xiaoman_unique_id)
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if task and str(task.order_id) != str(invoice.xiaoman_order_id):
        reject(409, "出库任务与原订单绑定不一致")
    if task and (task.reason or '').startswith('delete_pending:'):
        reject(409,'原出库删除尚未核对')
    generation = None
    if task and (task.reason or "").startswith("regenerate:"):
        generation_id = uncertain_recovery._canonical_uid((task.reason or "").split(" ", 1)[0][11:])
        generation = db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.id == int(generation_id),
            InvoiceSyncLog.invoice_id == invoice.id, InvoiceSyncLog.success == 1,
            InvoiceSyncLog.action.in_(["create", "update"]))
            .with_for_update().execution_options(populate_existing=True))
        if generation is None:
            reject(409, "原出库再生成代次不属于当前成功推单")
        verify_generation_target(generation, invoice)
    latest = db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id == invoice.id,
        InvoiceSyncLog.success == 1, InvoiceSyncLog.action.in_(["create", "update"]))
        .order_by(InvoiceSyncLog.id.desc()).with_for_update().execution_options(populate_existing=True))
    if latest is not None:
        verify_generation_target(latest, invoice)
    deleted_id = ((task.reason or "")[8:] if task and task.status == "skipped"
                  and (task.reason or "").startswith("deleted:") else None)
    if deleted_id is not None:
        uncertain_recovery._canonical_uid(deleted_id)
    deletion = db.scalar(select(ShippingOperationEvent).where(
        ShippingOperationEvent.scope == "outbound-delete", ShippingOperationEvent.request_id == deleted_id,
        ShippingOperationEvent.action == "outbound_deleted").with_for_update()
        .execution_options(populate_existing=True)) if deleted_id else None
    if deletion is not None:
        try:
            data = deletion.payload
            orders = [uncertain_recovery._canonical_uid(value) for value in data["order_ids"]]
            saved_tasks = [uncertain_recovery._canonical_uid(row["id"]) for row in data["tasks"]]
            if (uncertain_recovery._canonical_uid(data["outbound_invoice_id"]) != deleted_id
                    or str(invoice.xiaoman_order_id) not in orders or str(task.id) not in saved_tasks
                    or len(set(orders)) != len(orders) or len(set(saved_tasks)) != len(saved_tasks)):
                raise ValueError("Unrelated deletion evidence")
        except (ValueError, TypeError, KeyError, AttributeError):
            reject(409, "原出库删除证据不属于当前订单及任务")
    linked_row = db.scalar(select(linked.InvoiceLinkedSync).where(linked.InvoiceLinkedSync.invoice_id == invoice.id)
        .order_by(linked.InvoiceLinkedSync.created_at.desc(), linked.InvoiceLinkedSync.id.desc())
        .with_for_update().execution_options(populate_existing=True))
    custom_missing = tasks.has_unbackfilled_custom_lines(db, invoice)
    binding = (push.capture(db, invoice, payload), row_state(task), row_state(latest), row_state(deletion),
               row_state(linked_row), row_state(generation), deepcopy(product_rows), custom_missing)
    dto = SimpleNamespace(xiaoman_order_id=invoice.xiaoman_order_id, customer_id=invoice.customer_id,
        currency=invoice.currency, total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)
    info = {"status": task.status if task else None, "reason": task.reason if task else None,
            "latest_id": latest.id if latest else None, "deleted_id": deleted_id,
            "deletion_verified": bool(deletion and latest and latest.created_at > deletion.created_at),
            "custom_missing": custom_missing}
    return binding, dto, deepcopy(product_rows), info, task


def read_order(db, dto, rows):
    order = legacy.remote.read(db, "/v1/invoices/order/info", {"order_id": dto.xiaoman_order_id})
    if (not isinstance(order, dict) or str(order.get("order_id")) != str(dto.xiaoman_order_id)
            or not isinstance(order.get("product_list"), list)
            or any(not isinstance(row, dict) for row in order["product_list"])
            or "company_id" not in order or "currency" not in order or "amount" not in order):
        reject(503, "原订单证据不完整，请读取原任务核对")
    customer = order['company_id']
    if (not (type(customer) is int and customer > 0 or isinstance(customer, str) and bool(customer.strip()))
            or not isinstance(order['currency'], str) or not order['currency']):
        reject(503, "原订单客户或币种头字段不完整")
    for row in order["product_list"]:
        try:
            uncertain_recovery._canonical_uid(row.get("unique_id"))
        except ValueError:
            reject(503, "原订单明细身份不可信，请读取原任务核对")
    try:
        numbers = [Decimal(str(order["amount"]))]
        for row in order["product_list"]:
            numbers.extend(Decimal(str(row[key])) for key in ("count", "unit_price", "cost_amount"))
        if any(not value.is_finite() for value in numbers):
            raise ValueError("Nonfinite supplier evidence")
    except (ValueError, TypeError, KeyError, ArithmeticError):
        reject(503, "原订单商业字段证据不完整，请读取原任务核对")
    try:
        uncertain_recovery.verify_existing(dto, rows, order)
    except ValueError:
        reject(409, "原订单商业证据与当前发票不同，请核对原单")
    return deepcopy(order)


def evidence(db, dto, rows, info):
    try:
        order = read_order(db, dto, rows)
        related = legacy.linked_outbound_service.find_related(db, order)
        if not isinstance(related, list):
            reject(503, "关联出库证据不完整")
        shortages = None
        generation = (info["reason"] or "").split(" ", 1)[0]
        new_generation = generation.startswith("regenerate:") and info["latest_id"] is not None and generation != f'regenerate:{info["latest_id"]}'
        if not related and info["status"] == "waiting_stock" and not new_generation:
            try:
                shortages = legacy._stock_shortages(db, order)
            except (ValueError, TypeError, AttributeError, ArithmeticError):
                reject(503, "目标仓库库存证据不完整，请核对原任务")
        if not related and read_order(db, dto, rows) != order:
            reject(409, "取证期间原订单发生变化，请重新核对")
        return related, shortages
    except HTTPException:
        raise
    except Exception:
        logger.warning("Outbound followup supplier evidence unavailable")
        print("[outbound-followup] supplier evidence unavailable", flush=True)
        reject(503, "出库取证暂不可用，请读取原任务，禁止重复推送")
    finally:
        db.rollback()
        db.expire_all()


def queue(db, invoice, task, info, shortages, actor):
    status, reason, latest_id = info["status"], info["reason"] or "", info["latest_id"]
    result = {"status": "manual", "message": "缺少已核实删除的原出库单，请人工核对后处理"}
    changed = False
    if status == "pending":
        if reason.startswith("regenerate:") and latest_id and reason != f"regenerate:{latest_id}":
            task.reason = f"regenerate:{latest_id}"
            changed = True
        result = {"status": "pending", "message": "出库任务将按最新订单及库存核对后生成"}
    elif status == "waiting_stock":
        generation = reason.split(" ", 1)[0] if reason.startswith("regenerate:") else ""
        next_generation = f"regenerate:{latest_id}" if generation and latest_id else generation
        if generation and next_generation != generation:
            task.status, task.reason, task.last_error, task.attempts = "pending", next_generation, None, 0
        elif shortages:
            task.reason = (next_generation + " " if next_generation else "") + "Insufficient warehouse stock"
            task.last_error = json.dumps({"outcome": "waiting_stock", "order_id": str(invoice.xiaoman_order_id),
                                         "reason": task.reason, "shortages": shortages})
        else:
            task.status, task.reason, task.last_error = "pending", next_generation or None, None
        changed = True
        result = {"status": task.status, "message": "目标仓库仍缺货" if shortages else "任务已排队，执行端将再次核对库存"}
        if shortages:
            result["shortages"] = shortages
    elif status == "skipped":
        if info["custom_missing"]:
            result["message"] = "非标产品尚未补齐真实产品与SKU，不能自动生成出库单"
        elif info["deleted_id"] and info["deletion_verified"]:
            invoice.outbound_auto_requested = 1
            task.status, task.reason, task.last_error, task.attempts = "pending", f"regenerate:{latest_id}", None, 0
            changed = True
            result = {"status": "pending", "message": "原删除及新推单代次已核实，任务已重新排队"}
    if changed:
        audit(db, invoice, "outbound_queue", actor["id"],
              {"status": task.status, "generation_id": latest_id, "original_order_id": str(invoice.xiaoman_order_id)})
    return result


def run(db, invoice_id, user):
    try:
        invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:sync")
        if invoice.order_type == "presale":
            db.commit()
            return {"status": "manual", "message": "预售单由发货结算按批次安排，不执行整单自动出库"}
        expected, dto, rows, info, _ = capture(db, invoice)
        db.commit()
        related, shortages = evidence(db, dto, rows, info)
        invoice, actor = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:sync")
        current, _, _, info, task = capture(db, invoice)
        if current != expected:
            reject(409, "出库取证期间原订单、任务或财务资料已变化")
        if related:
            invoice_dto = SimpleNamespace(id=invoice.id, invoice_no=invoice.invoice_no)
            db.commit()
            if len(related) != 1:
                return {"status": "manual", "message": "订单关联多张出库单，请分别核对"}
            # This existing outbound edit executor has its own protocol audit; queue tests do not prove it.
            return legacy._follow_existing(db, invoice_dto, actor, related, force_authority=True)
        result = queue(db, invoice, task, info, shortages, actor)
        db.commit()
        invoice, _ = edit_authority.prepare_recovery(db, invoice_id, user, "invoice:sync")
        db.commit()
        return result
    except HTTPException as error:
        db.rollback()
        error.headers = {**(error.headers or {}), "Cache-Control": "private, no-store"}
        raise
    except ValueError:
        db.rollback()
        logger.warning("Current outbound followup state rejected")
        print("[outbound-followup] current state rejected", flush=True)
        reject(409, "当前订单或任务不允许后续出库，请核对原任务")
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Outbound followup transaction unavailable")
        print("[outbound-followup] transaction unavailable", flush=True)
        reject(503, "后续出库提交暂不可确认，请读取原任务，禁止重复推送")
