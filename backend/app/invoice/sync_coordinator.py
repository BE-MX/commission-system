"""Shared existing order synchronization and inventory finalization."""
import logging
from fastapi import HTTPException
from app.invoice import service, xiaoman_service
from app.semifinished import invoice_service as semifinished_invoice_service

logger = logging.getLogger(__name__)


class BeforeSendError(HTTPException):
    before_send = True


def synchronize(db, invoice, operator_id, *, linked_id=None, linked_token=None):
    from app.invoice.linked_sync_service import ensure_idle, ensure_running, LostExecution
    from app.invoice.lifecycle_guard import ensure_mutable
    try:
        ensure_idle(invoice, linked_id)
        ensure_mutable(db, invoice)
    except ValueError as exc:
        raise BeforeSendError(409, str(exc)) from exc
    # Persisted by any preparatory commit: no worker may claim the old version.
    invoice.sync_status = "not_synced"
    ensure_running(db, invoice, linked_id, linked_token)
    invoice_id = invoice.id
    operation_key = None
    receipt_token = None
    from app.receipt import invoice_link
    try:
        receipt_token = invoice_link.arm(db, invoice, operator_id)
        if receipt_token:
            db.commit()  # stock-only claim survives the order service's intermediate commits
            invoice = service.get_invoice(db, invoice_id, for_update=True)
        ensure_running(db, invoice, linked_id, linked_token)
        operation_key = semifinished_invoice_service.prepare_invoice_sync(db, invoice, operator_id)
    except LostExecution:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        if receipt_token:
            invoice = service.get_invoice(db, invoice_id, for_update=True)
            ensure_running(db, invoice, linked_id, linked_token)
            invoice_link.release_rejected(db, invoice, receipt_token)
            invoice_link.finish_attempt(db, invoice, receipt_token)
            db.commit()
        raise BeforeSendError(409, str(exc))
    # prepare 可能提交预占并释放原发票行锁；重新加锁，避免预占后的并发编辑/同步。
    invoice = service.get_invoice(db, invoice_id, for_update=True)
    ensure_running(db, invoice, linked_id, linked_token)
    try:
        semifinished_invoice_service.ensure_pending_matches_invoice(db, invoice, operation_key)
    except LostExecution:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        try:
            ensure_running(db, invoice, linked_id, linked_token)
            semifinished_invoice_service.release_invoice_sync(db, invoice_id, operation_key, operator_id)
            ensure_running(db, invoice, linked_id, linked_token)
            invoice_link.release_rejected(db, invoice, receipt_token)
            invoice_link.finish_attempt(db, invoice, receipt_token)
            db.commit()
        except Exception:  # noqa: BLE001 - 释放失败保留 pending，由管理员恢复
            db.rollback()
            raise BeforeSendError(409, f"{exc}；半成品预占释放异常，请联系管理员")
        raise BeforeSendError(409, str(exc))
    result = xiaoman_service.sync_invoice(
        db,
        invoice,
        operator_id=operator_id,
        inventory_operation_key=operation_key,
        receipt_sync_token=receipt_token,
        **({"linked_id": linked_id, "linked_token": linked_token} if linked_id else {}),
    )
    ensure_running(db, invoice, linked_id, linked_token)
    if result.get("ok"):
        try:
            semifinished_invoice_service.finalize_invoice_sync(db, invoice_id, operation_key, operator_id)
        except Exception as exc:  # noqa: BLE001 - OKKI 已受理，保留 pending 供人工恢复，绝不能误释放
            logger.warning("semifinished finalize failed invoice=%s: %s", invoice_id, exc)
            print(f"[semifinished] finalize failed invoice={invoice_id}: {exc}", flush=True)
            db.rollback()
            result = {
                "ok": False,
                "message": "OKKI 已同步，但半成品出库待恢复，请联系管理员处理",
                "issues": [],
                "xiaoman_order_id": invoice.xiaoman_order_id,
                "inventory_pending": True,
            }
        else:
            result.update(invoice_link.mark_success(db, invoice, receipt_token))
            db.commit()
    elif (result.get("okki_accepted") or invoice.sync_status == "sync_uncertain") and operation_key:
        # OKKI 已建单但响应缺行：无法可靠判断哪些产品已经生效，保留整批预占，
        # 由管理员核对 OKKI 后选择 finalize/release，禁止恢复为可用库存造成超卖。
        result["message"] = f"{result.get('message') or 'OKKI 受理结果待核对'}；半成品库存保持预占，请核对后恢复"
        result["inventory_pending"] = True
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 预占已在第一阶段提交，失败时仍安全保持 pending
            logger.warning("invoice partial-accept state commit failed invoice=%s: %s", invoice_id, exc)
            db.rollback()
    else:
        try:
            ensure_running(db, invoice, linked_id, linked_token)
            semifinished_invoice_service.release_invoice_sync(db, invoice_id, operation_key, operator_id)
            invoice_link.release_rejected(db, invoice, receipt_token)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 释放异常必须显式暴露并保留日志
            logger.warning("semifinished release failed invoice=%s: %s", invoice_id, exc)
            print(f"[semifinished] release failed invoice={invoice_id}: {exc}", flush=True)
            db.rollback()
            result["message"] = f"{result.get('message') or '同步失败'}；半成品预占释放异常，请联系管理员"
            result["inventory_pending"] = True
    if receipt_token:
        invoice = service.get_invoice(db, invoice_id, for_update=True)
        ensure_running(db, invoice, linked_id, linked_token)
        invoice_link.finish_attempt(db, invoice, receipt_token)
        db.commit()
    return result