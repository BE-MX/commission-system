"""Common write fences for every invoice entry point."""
from app.invoice.models import OkkiOutboundTask
from app.receipt.models import Receipt


def ensure_active(invoice):
    if invoice.status in {"cancel_pending", "cancelled"}:
        raise ValueError("订单正在取消或已取消，请在取消处理记录中查看结果")


def ensure_mutable(db, invoice):
    ensure_active(invoice)
    from app.shipping_inspection.outbound_sync_state import ensure_invoice_idle
    ensure_invoice_idle(db, invoice)
    if invoice.sync_status == "sync_uncertain":
        raise ValueError("小满订单结果待核对，请先完成原订单恢复")
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).with_for_update().first()
    if task and (task.status in {"running", "uncertain"} or (task.reason or "").startswith("delete_pending:")):
        raise ValueError("出库正在执行、删除或结果待核对，暂不能修改或同步订单")
    if db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id, Receipt.status == "active",
                                 Receipt.sync_status.in_(["syncing", "uncertain"])).first():
        raise ValueError("回款正在发送或结果待核对，暂不能修改或同步订单")
