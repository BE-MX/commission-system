"""Current-authorized local outbound recovery after unlocked remote evidence."""
import logging
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from app.core.time import beijing_now
from app.invoice import edit_authority, linked_sync_service as linked
from app.invoice import linked_outbound_service as outbounds, outbound_task_service as tasks
from app.invoice import okki_client, xiaoman_service
from app.invoice.cancellation_service import audit
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import InvoiceLinkedSync, OkkiOutboundTask
from app.portal.access_policy import employee_principal
from app.portal.authority import lock_authority
from app.portal.errors import PortalError
from app.receipt import remote

logger = logging.getLogger(__name__)


def authorize(db, invoice_id, user):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "出库核对必须从新事务开始")
    db.expire_all()
    lock_authority(db, force=True)
    try:
        current = employee_principal(db, int(user.get("id") or user.get("sub") or 0), "invoice:admin")
    except (ValueError, TypeError):
        raise HTTPException(403, "无法确认当前操作人") from None
    except PortalError as error:
        raise HTTPException(error.status, "当前账号无权恢复或核对出库") from None
    invoice = edit_authority.lock_document(db, invoice_id, force=True)
    edit_authority._visible(db, invoice, current)
    return invoice, current


def row_state(row):
    return None if row is None else tuple(deepcopy(getattr(row, c.name)) for c in row.__table__.columns)


def latest_locked(db, invoice_id):
    return db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id == invoice_id)
        .order_by(InvoiceLinkedSync.created_at.desc(), InvoiceLinkedSync.id.desc())
        .with_for_update().execution_options(populate_existing=True))


def product_rows(db, invoice):
    rows, _, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues:
        raise ValueError("订单产品映射尚未完整核对")
    return rows


def local_state(db, invoice, action, version):
    linked.ensure_idle(invoice)
    ensure_mutable(db, invoice)
    if not invoice.xiaoman_order_id or linked.edit_version(invoice) != version:
        raise ValueError("订单未绑定或已变化，请重新读取")
    task = db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    operation = latest_locked(db, invoice.id)
    rows = product_rows(db, invoice)
    if action == "outbound_retry":
        if invoice.order_type == "presale" or invoice.sync_status != "synced":
            raise ValueError("仅已同步现货订单可恢复自动出库")
        if tasks.has_unbackfilled_custom_lines(db, invoice):
            raise ValueError("非标产品尚未补齐真实产品与SKU")
        if task and (str(task.order_id) != str(invoice.xiaoman_order_id) or
                (task.reason or "").startswith(("regenerate:", "delete_pending:")) or
                not (task.status == "failed" or (task.status == "skipped" and task.reason == tasks.SKIP_REASON_GENERIC_MERGE))):
            raise ValueError("仅明确未发送或漏建任务可恢复；已创建、删除或待核对任务请人工处理")
    else:
        if not operation or operation.status != "manual" or operation.steps.get("order", {}).get("status") != "done" or linked.snapshot(invoice) != operation.after or operation.steps.get("outbound", {}).get("status") == "done":
            raise ValueError("请先执行本版本关联同步")
    binding = (edit_authority._binding(db, invoice), remote.invoice_binding(invoice), invoice.order_type, invoice.status,
               deepcopy(invoice.cancellation), invoice.outbound_auto_requested,
               row_state(task), row_state(operation), deepcopy(rows))
    return binding, task, operation, rows


def verify_order(invoice, order):
    if (not isinstance(order, dict) or str(order.get("order_id")) != str(invoice.xiaoman_order_id)
            or str(order.get("company_id")) != str(invoice.customer_id)
            or order.get("currency") != invoice.currency
            or remote.money(order.get("amount")) != invoice.total_amount - remote.money(invoice.surcharge_amount or 0)):
        raise ValueError("小满订单绑定或金额无法验证")


def recover(db, invoice_id, user, action, reason, version):
    if action not in {"outbound_retry", "ack_outbound"}:
        raise HTTPException(422, "不支持此出库恢复操作")
    try:
        invoice, current = authorize(db, invoice_id, user)
        captured, _, _, rows = local_state(db, invoice, action, version)
        detached = SimpleNamespace(xiaoman_order_id=invoice.xiaoman_order_id, customer_id=invoice.customer_id,
            currency=invoice.currency, total_amount=invoice.total_amount, surcharge_amount=invoice.surcharge_amount)
        db.commit()  # Only authorization and capture reads, no business mutation.
        try:
            order = remote.read(db, "/v1/invoices/order/info", {"order_id": detached.xiaoman_order_id})
            verify_order(detached, order)
            if action == "outbound_retry":
                if not isinstance(remote.order_receipts(db, detached.xiaoman_order_id), list):
                    raise ValueError("Incomplete receipt evidence")
            related = outbounds.find_related(db, order)
            if not isinstance(related, list):
                raise ValueError("Incomplete outbound evidence")
            evidence = None if action == "outbound_retry" else outbounds.summarize_documents(rows, related, detached.xiaoman_order_id)
        except (ValueError, TypeError, KeyError, okki_client.OkkiApiError):
            logger.warning("Outbound recovery remote evidence unavailable")
            print("[outbound] recovery remote evidence unavailable", flush=True)
            raise HTTPException(503, "出库证据暂不可用，请读取原任务后重试") from None
        finally:
            db.rollback()
            db.expire_all()
        invoice, current = authorize(db, invoice_id, user)
        actual, task, operation, _ = local_state(db, invoice, action, version)
        if actual != captured:
            raise HTTPException(409, "核对期间订单或关联任务已变化，请重新读取")
        actor = int(current["id"])
        if action == "outbound_retry":
            if related:
                raise ValueError("已有出库单，不能整单重建，请处理原出库")
            invoice.outbound_auto_requested = 1
            task = task or tasks.enqueue_outbound_task(db, invoice)
            if task is None or task.invoice_id != invoice.id or str(task.order_id) != str(invoice.xiaoman_order_id):
                raise ValueError("出库任务归属已变化，请核对原任务")
            task.status, task.reason, task.last_error, task.attempts = "pending", None, None, 0
            audit(db, invoice, "outbound_retry", actor, {"reason": reason, "task_id": task.id})
            result = {"status": "pending", "message": "已核实无关联出库单，恢复自动出库；执行端仍会实时查重"}
        else:
            if evidence["differences"] or not evidence["documents"] or any(str(d["status"]) not in {"1", "2"} for d in evidence["documents"]):
                raise ValueError("出库数量、明细关联或状态仍需处理，不能标记完成")
            evidence.update(status="done", category="manually_verified", message="已人工核对价格、地址、备注：" + reason,
                            operator_id=actor, confirmed_at=beijing_now().isoformat())
            operation.steps = {**operation.steps, "outbound": evidence}
            operation.status = "done" if all(s["status"] == "done" for s in operation.steps.values()) else "manual"
            result = {"status": operation.status, "outbound": evidence}
        db.commit()
        return result
    except ValueError:
        db.rollback()
        logger.warning("Outbound recovery rejected by current local state")
        print("[outbound] recovery rejected by current local state", flush=True)
        raise HTTPException(409, "当前订单、任务或出库证据不允许此处理，请重新核对") from None
