"""Verify an uncertain update against the original remote order, never rebind."""
from decimal import Decimal
from app.invoice import lifecycle_remote, xiaoman_service
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.push_attempt import allow_recovery, finish
from app.invoice.models import InvoiceLinkedSync
from app.core.time import beijing_now
from app.invoice.models import InvoiceSyncLog, InvoiceItem
from app.semifinished.models import InvoiceAllocation


def confirm_existing(db, invoice, reason, actor, *, evidence=None):
    ensure_active(invoice)
    allow_recovery(invoice)
    if invoice.linked_sync_id:
        linked = db.query(InvoiceLinkedSync).filter_by(id=invoice.linked_sync_id).with_for_update().one()
        if linked.status != "uncertain" or (linked.lease_until and linked.lease_until > beijing_now()):
            raise ValueError("关联推送仍在执行，请先等待租约结束并核对")
    if invoice.sync_status != "sync_uncertain" or not invoice.xiaoman_order_id or len(reason.strip()) < 10:
        raise ValueError("仅已绑定订单的待核对结果可恢复，请填写至少10字核对依据")
    data = evidence if evidence is not None else lifecycle_remote.read(db, "order", invoice.xiaoman_order_id)
    if not isinstance(data, dict) or str(data.get("company_id")) != str(invoice.customer_id) or data.get("currency") != invoice.currency:
        raise ValueError("原小满订单不存在或身份不符，禁止解除同步保护")
    rows, binding, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, xiaoman_service.get_settings_row(db), editing=True)
    if issues:
        raise ValueError("本地产品映射不完整，请管理员核对原单")
    verified_rows = verify_existing(invoice, rows, data)
    if xiaoman_service._assign_unique_ids(invoice, binding, verified_rows):
        raise ValueError("小满明细ID无法完整回写")
    pending = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id, status="pending").all()
    keys = {r.operation_key for r in pending}
    if len(keys) > 1 or (pending and not next(iter(keys))):
        raise ValueError("库存预占批次异常，请核对")
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="verify_update", success=1, operator_id=actor,
        inventory_operation_key=next(iter(keys)) if keys else None,
        request_digest=reason.strip(), response_body="Original remote identity, items and total verified"))
    finish(invoice)
    invoice.sync_status, invoice.status = "not_synced", "ready"
    invoice.sync_error = "已核对原小满订单；请先完成待恢复库存，再重新同步核对其他资料"
    return invoice



def _canonical_uid(value):
    """Exact positive identity; reject ambiguous representations before write-back."""
    if type(value) is int:
        if value <= 0:
            raise ValueError("小满明细身份必须为正整数")
        value = str(value)
    if (not isinstance(value, str) or not value or not value.isascii()
            or not value.isdecimal() or value.startswith("0")
            or len(value) > InvoiceItem.__table__.c.xiaoman_unique_id.type.length):
        raise ValueError("小满明细身份不是规范正整数")
    return value


def verify_existing(invoice, rows, data):
    """Read-only comparison; no UID assignment or state writes before agreement."""
    if (not isinstance(data, dict) or str(data.get("order_id")) != str(invoice.xiaoman_order_id)
            or str(data.get("company_id")) != str(invoice.customer_id) or data.get("currency") != invoice.currency
            or not isinstance(data.get("product_list"), list)):
        raise ValueError("原小满订单身份或明细证据不完整")
    if any(not isinstance(row, dict) for row in data["product_list"]):
        raise ValueError("小满明细身份不完整")
    remote_rows = [{**row, "unique_id": _canonical_uid(row.get("unique_id"))}
                   for row in data["product_list"]]
    if len({row["unique_id"] for row in remote_rows}) != len(remote_rows):
        raise ValueError("小满明细身份重复")
    def signature(row):
        numbers = [Decimal(str(row[key])) for key in ("count", "unit_price", "cost_amount")]
        if any(not number.is_finite() for number in numbers):
            raise ValueError("小满明细数值不完整")
        return (str(row.get("product_id")), str(row.get("sku_id")), *numbers)
    try:
        same = sorted(map(signature, rows)) == sorted(map(signature, remote_rows))
        live_by_id = {row["unique_id"]: row for row in remote_rows}
        same = same and all("unique_id" not in row or
            (_canonical_uid(row["unique_id"]) in live_by_id
             and signature(row) == signature(live_by_id[_canonical_uid(row["unique_id"])]))
            for row in rows)
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError("小满订单明细证据不完整，不能确认已受理") from exc
    try:
        amount = Decimal(str(data.get("amount", "-1")))
        if not amount.is_finite():
            raise ValueError("小满订单金额证据不完整")
    except ArithmeticError as error:
        raise ValueError("小满订单金额证据不完整") from error
    if not same or amount != invoice.total_amount - Decimal(invoice.surcharge_amount or 0):
        raise ValueError("远端数量、价格或金额与本次修改不同，请在小满核实并处理后重新核对")
    return remote_rows
