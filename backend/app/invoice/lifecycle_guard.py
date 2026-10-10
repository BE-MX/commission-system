"""Common write fences for every invoice entry point."""
from app.invoice.models import OkkiOutboundTask
from app.receipt.models import Receipt


def ensure_active(invoice):
    if invoice.status in {"cancel_pending", "cancelled"}:
        raise ValueError("订单正在取消或已取消，请在取消处理记录中查看结果")


def active_presale_settlement(db, invoice, *, current=False):
    if invoice.order_type != "presale":
        return None
    from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound
    from app.invoice import shipment_inspection_service
    query = db.query(ShipmentSettlement).filter(
        ShipmentSettlement.invoice_id == invoice.id,
        ShipmentSettlement.state != "cancelled",
    ).order_by(ShipmentSettlement.id)
    if current:
        query = query.populate_existing().with_for_update()
    for row in query.all():
        if row.state != 'shipped':
            return row
        outbound = db.query(ShipmentOutbound).filter_by(settlement_id=row.id).first()
        if outbound and not shipment_inspection_service.snapshot(db, outbound, current=current)[1]:
            return row
    return None


def presale_edit_blocked_reason(db, invoice):
    row = active_presale_settlement(db, invoice)
    if row is None:
        return None
    reason = "当前有未完成的发货结算，主单暂不能修改或同步。"
    if isinstance(row.quote, dict) and row.quote.get("funding_version") == 2:
        return reason + "新增到账款请使用右侧“登记预售收款”，提交后无需保存主单；本批补款请在发货结算或整笔回款中处理。"
    return reason + "收款请通过原批次补款，先完成或处理原批次后再修改主单。"


def ensure_mutable(db, invoice):
    ensure_active(invoice)
    if active_presale_settlement(db, invoice, current=True):
        raise ValueError("预售订单有未完成的发货结算，请先处理本批，暂不能修改或取消主单")
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
