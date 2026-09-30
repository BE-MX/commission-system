"""Presale shipment funding fence and one-shot pending outbound delivery."""
import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import and_, or_, update

from app.core.config import get_settings
from app.core.queue_scan import take
from app.core.time import beijing_now
from app.invoice import linked_outbound_service, okki_client, xiaoman_service
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.models import Invoice
from app.invoice.settlement_contract import build_outbound_candidate
from app.invoice.settlement_models import (Receivable, SettlementApplication,
    SettlementEvent, SettlementItem, ShipmentOutbound, ShipmentSettlement)
from app.invoice.settlement_policy import require_delivery
from app.invoice.settlement_service import check_outbounds, digest, funding_balance, goods_balance
from app.receipt import balance as receipt_balance, remote
from app.receipt.models import Receipt
from app.receipt.sync_service import refresh_accepted
from app.shipping_inspection import outbound_presence


logger = logging.getLogger(__name__)


def _funded(db, settlement):
    applications = db.query(SettlementApplication, Receipt).join(
        Receipt, Receipt.id == SettlementApplication.receipt_id).filter(
        SettlementApplication.settlement_id == settlement.id,
        SettlementApplication.status != "released").all()
    expected = Decimal(settlement.quote["new_payment_due"]) + Decimal(settlement.quote["deposit_applied"])
    if sum((Decimal(app.amount) for app, _ in applications), Decimal(0)) != expected:
        return False
    if any(receipt.status != "active" or receipt.sync_status != "synced"
           or receipt.collect_status != 1 or receipt.last_error for _, receipt in applications):
        return False
    balance = funding_balance(db, settlement)
    return (Decimal(balance["remaining_amount"]) == 0
            and Decimal(balance["effective_amount"]) == expected)


def _refresh_funding(db, settlement_id):
    ids = [receipt_id for (receipt_id,) in db.query(SettlementApplication.receipt_id).filter(
        SettlementApplication.settlement_id == settlement_id,
        SettlementApplication.status != "released").distinct()]
    db.commit()
    for identity in ids:
        receipt = db.get(Receipt, identity)
        if receipt and receipt.status == "active" and receipt.xiaoman_receipt_id:
            refresh_accepted(db, identity)
        else:
            db.rollback()
            return False
    return True


def _live_candidate(db, invoice, settlement, *, pending=None):
    warehouse = get_settings().OKKI_PRESALE_WAREHOUSE_ID
    if not warehouse:
        raise ValueError("预售出库仓库尚未配置")
    order = _live_funding(db, invoice, settlement)
    if (not remote.order_active(db, order)
            or str(order.get("order_id")) != str(invoice.xiaoman_order_id)
            or str(order.get("company_id")) != str(invoice.customer_id)
            or order.get("currency") != invoice.currency
            or remote.money(order.get("amount")) != invoice.total_amount - Decimal(invoice.surcharge_amount or 0)):
        raise ValueError("预售主单小满身份或金额已变化")
    related = linked_outbound_service.find_related(db, order)
    check_outbounds(db, invoice, {"outbounds": related}, pending=pending)
    reserved = defaultdict(int)
    for document in related:
        if pending and str(document.get("outbound_invoice_id")) == pending.remote_id:
            continue
        for item in document["record_list"]:
            if str(item.get("order_id")) == str(invoice.xiaoman_order_id):
                quantity = Decimal(str(item.get("outbound_count")))
                if not quantity.is_finite() or quantity < 0 or quantity != quantity.to_integral_value():
                    raise ValueError("远端关联出库数量无效")
                reserved[str(item.get("order_record_id"))] += int(quantity)
    items = [{"quantity": item.quantity, "snapshot": item.snapshot} for item in db.query(
        SettlementItem).filter_by(settlement_id=settlement.id).all()]
    for item in items:
        reserved.setdefault(str(item["snapshot"]["order_record_id"]), 0)
    handler = xiaoman_service.resolve_okki_user_id(db, invoice.sales_user_id)
    return build_outbound_candidate(settlement.settlement_no, invoice.xiaoman_order_id,
        invoice.customer_id, invoice.currency, items, order, warehouse,
        handler_id=handler, reserved_quantities=reserved)


def _live_funding(db, invoice, settlement):
    """Reconcile the complete active remote receipt lists, including freight."""
    goods_snapshot = remote.order_snapshot(db, invoice)
    goods_balance(db, invoice, goods_snapshot)
    main = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
    if not remote.order_active(db, main):
        raise ValueError("小满预售主单已删除或活动列表未确认")
    freight = db.query(Receivable).filter_by(settlement_id=settlement.id, kind="freight").first()
    freight_snapshot = None
    if freight:
        freight_snapshot = remote.target_snapshot(db, freight)
        receipt_balance.calculate_target(db, freight, freight_snapshot)
    goods_rows = {str(row["cash_collection_id"]): row for row in goods_snapshot["rows"]}
    freight_rows = ({str(row["cash_collection_id"]): row for row in freight_snapshot["rows"]}
                    if freight_snapshot else {})
    applications = db.query(SettlementApplication, Receipt).join(
        Receipt, Receipt.id == SettlementApplication.receipt_id).filter(
        SettlementApplication.settlement_id == settlement.id,
        SettlementApplication.status != "released").all()
    for application, receipt in applications:
        rows = freight_rows if application.component == "freight" else goods_rows
        row = rows.get(str(receipt.xiaoman_receipt_id))
        if not row or str(row.get("collect_status")) != "1":
            raise ValueError("预售本批远端有效回款已缺失或未生效")
    return main


def queue_ready(db, settlement_id):
    require_delivery()
    if not _refresh_funding(db, settlement_id):
        return None
    settlement = db.get(ShipmentSettlement, settlement_id)
    if not settlement or settlement.state not in {"awaiting_payment", "awaiting_verification", "ready"}:
        return None
    if not _funded(db, settlement):
        return None
    invoice = db.get(Invoice, settlement.invoice_id)
    # The remote read is outside a write lock; compare local versions after locking.
    version = settlement.version
    payload = _live_candidate(db, invoice, settlement)
    db.commit()
    db.query(Invoice.id).filter(Invoice.id == invoice.id).with_for_update().one()
    db.refresh(invoice, with_for_update=True)
    db.refresh(settlement, with_for_update=True)
    ensure_active(invoice)
    if settlement.version != version or settlement.state not in {"awaiting_payment", "awaiting_verification", "ready"}:
        db.rollback()
        return None
    if not _funded(db, settlement):
        db.rollback()
        return None
    existing = db.query(ShipmentOutbound).filter_by(settlement_id=settlement.id).first()
    if existing:
        db.rollback()
        return existing.id
    row = ShipmentOutbound(settlement_id=settlement.id, invoice_id=invoice.id,
        outbound_no=settlement.settlement_no, status="pending", payload=payload,
        payload_hash=digest(payload))
    db.add(row)
    settlement.state = "outbound_pending"
    settlement.version += 1
    db.commit()
    return row.id


def _verify(outbound, detail, remote_id=None):
    try:
        if (str(detail.get("outbound_invoice_id")) != str(remote_id or outbound.remote_id)
                or detail.get("serial_id") != outbound.outbound_no
                or str(detail.get("status")) not in {"1", "2"}):
            return False
        payload = outbound.payload
        if ("currency" in payload and detail.get("currency") != payload["currency"]
                or "source_type" in payload and str(detail.get("source_type")) != str(payload["source_type"])
                or "company_id" in payload and str((detail.get("company_info") or {}).get("id")) != str(payload["company_id"])
                or "invoice_warehouse_id" in payload and str((detail.get("invoice_warehouse_info") or {}).get("id")) != str(payload["invoice_warehouse_id"])):
            return False
        if "handler" in payload:
            expected_handlers = {str(value) for value in payload["handler"]}
            actual_handlers = {str(value.get("user_id")) for value in (detail.get("handler_info") or [])}
            if actual_handlers != expected_handlers:
                return False
        wanted = {str(row["order_record_id"]): row for row in outbound.payload["record_list"]}
        rows = detail.get("record_list")
        if not isinstance(rows, list) or len(rows) != len(wanted):
            return False
        actual = {str(row.get("order_record_id")): row for row in rows}
        if len(actual) != len(rows) or set(actual) != set(wanted):
            return False
        for identity, expected in wanted.items():
            item = actual[identity]
            for field in ("order_id", "product_id", "sku_id"):
                if str(item.get(field)) != str(expected[field]):
                    return False
            if Decimal(str(item.get("outbound_count"))) != Decimal(expected["outbound_count"]):
                return False
            if "sale_price" in expected and Decimal(str(item.get("sale_price"))) != Decimal(str(expected["sale_price"])):
                return False
            if "product_unit" in expected and item.get("product_unit") != expected["product_unit"]:
                return False
            if outbound.remote_line_snapshot:
                baseline = outbound.remote_line_snapshot.get(identity)
                if (not baseline or str(item.get("outbound_record_id")) != baseline["outbound_record_id"]
                        or Decimal(str(item.get("cost_unit_price_rmb"))) != Decimal(baseline["cost_unit_price_rmb"])):
                    return False
        return True
    except (TypeError, ValueError, InvalidOperation, KeyError):
        return False


def _line_snapshot(detail):
    result = {}
    try:
        for item in detail["record_list"]:
            identity = str(item["order_record_id"])
            line_id = str(item.get("outbound_record_id") or "")
            cost = Decimal(str(item.get("cost_unit_price_rmb")))
            if (not line_id.isdigit() or int(line_id) <= 0 or identity in result
                    or not cost.is_finite() or cost < 0):
                raise ValueError("小满出库明细 ID 或成本单价无效")
            result[identity] = {"outbound_record_id": line_id,
                                "cost_unit_price_rmb": str(cost)}
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("小满出库明细 ID 或成本单价缺失") from exc
    return result


def refresh(db, outbound_id, *, confirmation_token=None):
    outbound = db.get(ShipmentOutbound, outbound_id)
    if not outbound or not outbound.remote_id:
        raise ValueError("出库任务尚无小满出库单 ID")
    detail = remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": outbound.remote_id})
    token = okki_client.ensure_access_token(db)
    active = outbound_presence.is_active(token, outbound.remote_id, detail.get("create_time"))
    if (outbound.status == "confirming" and outbound.lease_until
            and outbound.lease_until > beijing_now()
            and outbound.attempt_token != confirmation_token):
        raise ValueError("实际出库确认仍在发送中，请稍后核对")
    funding_ok = True
    if str(detail.get("status")) == "2":
        try:
            funding_ok = _refresh_funding(db, outbound.settlement_id)
            settlement_for_funding = db.get(ShipmentSettlement, outbound.settlement_id)
            invoice_for_funding = db.get(Invoice, outbound.invoice_id)
            _live_funding(db, invoice_for_funding, settlement_for_funding)
            funding_ok = funding_ok and _funded(db, settlement_for_funding)
        except Exception:
            db.rollback()
            funding_ok = False
    db.query(Invoice.id).filter(Invoice.id == outbound.invoice_id).with_for_update().one()
    db.refresh(outbound, with_for_update=True)
    settlement = db.get(ShipmentSettlement, outbound.settlement_id)
    if (outbound.status == "confirming" and outbound.lease_until
            and outbound.lease_until > beijing_now()
            and outbound.attempt_token != confirmation_token):
        raise ValueError("实际出库确认仍在发送中，请稍后核对")
    if not active or not _verify(outbound, detail):
        outbound.status = "uncertain"
        outbound.last_error = "小满分批出库身份或数量与冻结任务不一致，请核对原单"
        settlement.state = "outbound_uncertain"
    elif str(detail["status"]) == "2" and not outbound.remote_line_snapshot:
        outbound.status = "uncertain"
        outbound.last_error = "小满首次回读已实际出库，缺少待出库明细 ID 和成本基线，请人工核查"
        settlement.state = "outbound_uncertain"
    elif str(detail["status"]) == "2":
        outbound.status = "shipped" if funding_ok else "shipped_unfunded"
        outbound.last_error = None if funding_ok else "小满已实际出库，但关联回款未通过实时核验，请立即核查"
        outbound.verified_at = beijing_now()
        settlement.state = "shipped" if funding_ok else "outbound_uncertain"
        if funding_ok:
            db.query(SettlementApplication).filter_by(settlement_id=settlement.id,
                status="reserved").update({"status": "applied"})
    elif outbound.status in {"shipped", "shipped_unfunded"}:
        outbound.status = "uncertain"
        outbound.last_error = "小满已出库单重新显示待出库，需人工核查，禁止再次确认"
        settlement.state = "outbound_uncertain"
    elif outbound.status in {"confirming", "confirm_uncertain"}:
        outbound.status = "confirm_uncertain"
        outbound.last_error = "实际出库请求结果待核对；小满当前仍显示待出库，禁止再次确认"
        settlement.state = "outbound_uncertain"
        outbound.verified_at = beijing_now()
    else:
        outbound.status = "pending_remote"
        outbound.last_error = None
        outbound.verified_at = beijing_now()
        settlement.state = "outbound_pending"
        if outbound.remote_line_snapshot is None:
            outbound.remote_line_snapshot = _line_snapshot(detail)
    outbound.version += 1
    settlement.version += 1
    db.commit()
    return outbound.status


def bind_exact(db, outbound_id, remote_id, expected_version):
    """Bind only an exact active remote outbound after an unknown first POST."""
    outbound = db.get(ShipmentOutbound, outbound_id)
    if not outbound:
        raise ValueError("出库任务不存在")
    invoice_id = outbound.invoice_id
    detail = remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": remote_id})
    token = okki_client.ensure_access_token(db)
    if (not outbound_presence.is_active(token, remote_id, detail.get("create_time"))
            or not _verify(outbound, detail, remote_id)):
        raise ValueError("小满出库单与冻结任务不匹配，不能绑定")
    db.commit()
    db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    db.refresh(outbound, with_for_update=True)
    settlement = db.get(ShipmentSettlement, outbound.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if (settlement.version != expected_version
            or outbound.status not in {"uncertain", "failed", "verifying"}
            or (outbound.remote_id and outbound.remote_id != remote_id)):
        raise ValueError("出库任务已变化，请刷新后核对")
    outbound.remote_id = remote_id
    outbound.status = "verifying"
    outbound.last_error = None
    outbound.version += 1
    settlement.state = "outbound_pending"
    settlement.version += 1
    db.commit()
    return refresh(db, outbound_id)


def retry_failed(db, outbound_id, expected_version):
    """Retry only a definite rejection after exact serial absence is checked."""
    require_delivery()
    outbound = db.get(ShipmentOutbound, outbound_id)
    if not outbound:
        raise ValueError("出库任务不存在")
    invoice_id = outbound.invoice_id
    serial = outbound.outbound_no
    db.commit()
    if okki_client.find_outbound_by_serial(db, serial):
        raise ValueError("小满已有同编号出库单，请输入远端 ID 核对绑定")
    db.commit()
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    ensure_active(invoice)
    db.refresh(outbound, with_for_update=True)
    settlement = db.get(ShipmentSettlement, outbound.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if (settlement.version != expected_version or outbound.status != "failed"
            or outbound.remote_id or settlement.state != "review_required"):
        raise ValueError("出库任务不是可重试的明确失败状态")
    outbound.status = "pending"
    outbound.attempt_token = None
    outbound.lease_until = None
    outbound.last_error = None
    outbound.version += 1
    settlement.state = "outbound_pending"
    settlement.version += 1
    db.commit()
    return outbound.status


def _fence(db, outbound_id, token):
    count = db.execute(update(ShipmentOutbound).where(
        ShipmentOutbound.id == outbound_id, ShipmentOutbound.attempt_token == token,
        ShipmentOutbound.status == "sending", ShipmentOutbound.lease_until > beijing_now(),
    ).values(lease_until=beijing_now() + timedelta(minutes=5),
             version=ShipmentOutbound.version + 1)).rowcount
    db.commit()
    if not count:
        raise ValueError("分批出库任务租约已失效，请核对原单")


def _fence_confirm(db, outbound_id, token):
    count = db.execute(update(ShipmentOutbound).where(
        ShipmentOutbound.id == outbound_id, ShipmentOutbound.attempt_token == token,
        ShipmentOutbound.status == "confirming", ShipmentOutbound.lease_until > beijing_now(),
    ).values(lease_until=beijing_now() + timedelta(minutes=5),
             version=ShipmentOutbound.version + 1)).rowcount
    db.commit()
    if not count:
        raise ValueError("实际出库确认租约已失效，请核对原单")


def confirm(db, outbound_id, expected_version, actor, reason):
    """One explicit status-2 edit after rechecking funding and the pending note."""
    require_delivery()
    outbound = db.get(ShipmentOutbound, outbound_id)
    if not outbound:
        raise ValueError("出库任务不存在")
    invoice_id = outbound.invoice_id
    db.commit()
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    ensure_active(invoice)
    db.refresh(outbound, with_for_update=True)
    settlement = db.get(ShipmentSettlement, outbound.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if (settlement.version != expected_version or settlement.state != "outbound_pending"
            or outbound.status != "pending_remote" or not outbound.remote_id):
        raise ValueError("出库任务已变化，请刷新后核对")
    db.commit()

    if not _refresh_funding(db, settlement.id) or not _funded(db, settlement):
        raise ValueError("本批回款未全部生效，不能确认实际出库")
    detail = remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": outbound.remote_id})
    token = okki_client.ensure_access_token(db)
    if (not outbound_presence.is_active(token, outbound.remote_id, detail.get("create_time"))
            or not _verify(outbound, detail) or str(detail.get("status")) != "1"):
        raise ValueError("小满待出库单身份、数量或状态已变化，请先核对")
    remote_lines = {str(item["order_record_id"]): item for item in detail["record_list"]}
    if not outbound.remote_line_snapshot:
        raise ValueError("小满待出库明细尚未完成首次核验，请先刷新")
    edit_lines, remote_line_ids = [], set()
    for frozen in outbound.payload["record_list"]:
        baseline = outbound.remote_line_snapshot[str(frozen["order_record_id"])]
        remote_line_id = str(remote_lines[str(frozen["order_record_id"])].get("outbound_record_id") or "")
        if not remote_line_id.isdigit() or int(remote_line_id) <= 0 or remote_line_id in remote_line_ids:
            raise ValueError("小满待出库明细缺少唯一 ID，不能确认实际出库")
        remote_line_ids.add(remote_line_id)
        edit_lines.append({**frozen, "outbound_record_id": int(remote_line_id),
                           "cost_unit_price_rmb": float(Decimal(baseline["cost_unit_price_rmb"]))})
    candidate = _live_candidate(db, invoice, settlement, pending=outbound)
    if digest(candidate) != outbound.payload_hash:
        raise ValueError("小满订单或关联出库已变化，不能确认实际出库")
    db.commit()

    db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    db.refresh(outbound, with_for_update=True)
    db.refresh(settlement, with_for_update=True)
    ensure_active(db.get(Invoice, invoice_id))
    if (settlement.version != expected_version or settlement.state != "outbound_pending"
            or outbound.status != "pending_remote"):
        raise ValueError("出库任务已变化，请刷新后核对")
    attempt = uuid4().hex
    outbound.status = "confirming"
    outbound.attempt_token = attempt
    outbound.lease_until = beijing_now() + timedelta(minutes=30)
    outbound.last_error = None
    outbound.version += 1
    db.add(SettlementEvent(settlement_id=settlement.id, action="confirm_outbound",
                           actor_id=actor, reason=reason))
    db.commit()
    payload = {**outbound.payload, "record_list": edit_lines,
               "outbound_invoice_id": int(outbound.remote_id),
               "status": 2, "warehouse_invoice_time": beijing_now().strftime("%Y-%m-%d %H:%M:%S")}
    sent = False

    def before_send():
        nonlocal sent
        _fence_confirm(db, outbound_id, attempt)
        sent = True

    try:
        result = okki_client.push_outbound(db, payload, before_send=before_send)
        if str(result.get("outbound_invoice_id")) != outbound.remote_id:
            raise okki_client.OkkiOutcomeUncertainError("实际出库返回了不同单号，请核对原单")
        refresh(db, outbound_id, confirmation_token=attempt)
    except Exception as exc:
        db.rollback()
        logger.warning("shipment confirmation failed id=%s (%s)", outbound_id, type(exc).__name__)
        definite_rejection = (sent and isinstance(exc, okki_client.OkkiApiError)
                              and not isinstance(exc, okki_client.OkkiOutcomeUncertainError))
        if definite_rejection:
            try:
                current = remote.read(db, "/v1/invoices/outbound/info", {"outbound_invoice_id": outbound.remote_id})
                active = outbound_presence.is_active(
                    okki_client.ensure_access_token(db), outbound.remote_id, current.get("create_time"))
                definite_rejection = active and _verify(outbound, current) and str(current.get("status")) == "1"
            except Exception:
                db.rollback()
                definite_rejection = False
        outbound = db.get(ShipmentOutbound, outbound_id)
        if outbound and outbound.attempt_token == attempt and outbound.status == "confirming":
            uncertain = sent and not definite_rejection
            outbound.status = "confirm_uncertain" if uncertain else "pending_remote"
            outbound.last_error = ("实际出库结果待核对，禁止再次确认" if uncertain
                else "小满明确拒绝实际出库，请检查库存或权限后重试" if definite_rejection
                else "实际出库尚未发送：" + str(exc)[:450])
            outbound.lease_until = None
            outbound.version += 1
            settlement = db.get(ShipmentSettlement, outbound.settlement_id)
            settlement.state = "outbound_uncertain" if uncertain else "outbound_pending"
            settlement.version += 1
            db.commit()
    return db.get(ShipmentOutbound, outbound_id).status


def deliver(db, outbound_id):
    outbound = db.get(ShipmentOutbound, outbound_id)
    if not outbound:
        return
    invoice_id = outbound.invoice_id
    db.commit()  # Do not keep the identity lookup snapshot across the write lock.
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    ensure_active(invoice)
    db.refresh(outbound, with_for_update=True)
    settlement = db.get(ShipmentSettlement, outbound.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if outbound.status != "pending" or settlement.state != "outbound_pending":
        db.rollback()
        return
    require_delivery()
    token = uuid4().hex
    outbound.status = "sending"
    outbound.attempt_token = token
    outbound.lease_until = beijing_now() + timedelta(minutes=30)
    outbound.version += 1
    db.commit()
    sent = False

    def before_send():
        nonlocal sent
        _fence(db, outbound_id, token)
        sent = True

    try:
        outbound = db.get(ShipmentOutbound, outbound_id)
        invoice = db.get(Invoice, outbound.invoice_id)
        settlement = db.get(ShipmentSettlement, outbound.settlement_id)
        ensure_active(invoice)
        if settlement.state != "outbound_pending":
            raise ValueError("本批结算已变化，出库任务不能发送")
        if not _refresh_funding(db, settlement.id) or not _funded(db, settlement):
            raise ValueError("预售本批回款尚未全部生效")
        payload = _live_candidate(db, invoice, settlement)
        if digest(payload) != outbound.payload_hash:
            raise ValueError("小满订单或关联出库已变化，冻结任务待核对")
        if okki_client.find_outbound_by_serial(db, outbound.outbound_no):
            raise ValueError("小满已存在相同编号出库单，请核对原任务")
        db.commit()
        result = okki_client.push_outbound(db, outbound.payload, before_send=before_send)
        identity = str(result["outbound_invoice_id"])
        count = db.execute(update(ShipmentOutbound).where(
            ShipmentOutbound.id == outbound_id, ShipmentOutbound.attempt_token == token,
            ShipmentOutbound.status == "sending",
        ).values(remote_id=identity, status="verifying", lease_until=None,
                 version=ShipmentOutbound.version + 1)).rowcount
        db.commit()
        if count:
            refresh(db, outbound_id)
        else:
            logger.warning("late shipment result id=%s remote=%s", outbound_id, identity)
            print(f"[shipment_delivery] late result id={outbound_id} remote={identity}", flush=True)
    except Exception as exc:
        db.rollback()
        logger.warning("shipment delivery failed id=%s (%s)", outbound_id, type(exc).__name__)
        print(f"[shipment_delivery] failed id={outbound_id} ({type(exc).__name__})", flush=True)
        outbound = db.get(ShipmentOutbound, outbound_id)
        if outbound and outbound.attempt_token == token and outbound.status in {"sending", "verifying"}:
            uncertain = (bool(outbound.remote_id) or isinstance(exc, okki_client.OkkiOutcomeUncertainError)
                         or (sent and not isinstance(exc, (ValueError, okki_client.OkkiApiError))))
            outbound.status = "uncertain" if uncertain else "failed"
            outbound.last_error = ("小满分批出库结果待核对，禁止重新创建" if uncertain
                else str(exc)[:500] if isinstance(exc, ValueError) else "小满拒绝出库单，请核对字段或库存")
            outbound.lease_until = None
            outbound.version += 1
            settlement = db.get(ShipmentSettlement, outbound.settlement_id)
            settlement.state = "outbound_uncertain" if uncertain else "review_required"
            settlement.version += 1
            db.commit()


def recover_expired(db):
    ids = [identity for (identity,) in db.query(ShipmentOutbound.id).filter(
        ShipmentOutbound.status.in_(["sending", "confirming"]),
        ShipmentOutbound.lease_until < beijing_now())]
    for identity in ids:
        outbound = db.get(ShipmentOutbound, identity)
        confirming = outbound.status == "confirming"
        outbound.status = "confirm_uncertain" if confirming else "uncertain"
        outbound.last_error = ("实际出库确认中断，请核对小满原单，禁止重复确认" if confirming
                               else "分批出库发送中断，请核对小满原单，禁止重复创建")
        outbound.lease_until = None
        outbound.version += 1
        settlement = db.get(ShipmentSettlement, outbound.settlement_id)
        settlement.state = "outbound_uncertain"
        settlement.version += 1
    db.commit()


def process_pending(db):
    recover_expired(db)
    ids = take(db.query(ShipmentSettlement.id).filter(
        ShipmentSettlement.state.in_(["awaiting_payment", "awaiting_verification", "ready"])
    ), ShipmentSettlement.id, "shipment_funding", 10)
    db.commit()
    for identity in ids:
        try:
            queue_ready(db, identity)
        except Exception as exc:
            db.rollback()
            logger.warning("shipment funding check failed id=%s (%s)", identity, type(exc).__name__)
            print(f"[shipment_delivery] funding check failed id={identity} ({type(exc).__name__})", flush=True)
    outbound_ids = take(db.query(ShipmentOutbound.id).filter(
        ShipmentOutbound.status == "pending"), ShipmentOutbound.id, "shipment_outbound_pending", 10)
    db.commit()
    for identity in outbound_ids:
        try:
            deliver(db, identity)
        except Exception as exc:
            db.rollback()
            logger.warning("shipment worker failed id=%s (%s)", identity, type(exc).__name__)
            print(f"[shipment_delivery] worker failed id={identity} ({type(exc).__name__})", flush=True)
    now = beijing_now()
    soon = now - timedelta(minutes=1)
    later = now - timedelta(hours=1)
    live_ids = [identity for (identity,) in db.query(ShipmentOutbound.id).filter(or_(
        and_(ShipmentOutbound.status.in_(["pending_remote", "confirm_uncertain", "shipped_unfunded"]),
             or_(ShipmentOutbound.last_check_attempt_at.is_(None),
                 ShipmentOutbound.last_check_attempt_at < soon)),
        and_(ShipmentOutbound.status == "shipped",
             or_(ShipmentOutbound.verified_at.is_(None), ShipmentOutbound.verified_at < later),
             or_(ShipmentOutbound.last_check_attempt_at.is_(None),
                 ShipmentOutbound.last_check_attempt_at < later)),
    )).order_by(ShipmentOutbound.last_check_attempt_at, ShipmentOutbound.id).limit(20)]
    db.commit()
    for identity in live_ids:
        try:
            db.execute(update(ShipmentOutbound).where(ShipmentOutbound.id == identity).values(
                last_check_attempt_at=beijing_now()))
            db.commit()  # Advance even when OKKI readback fails, so later tasks are not starved.
            refresh(db, identity)
        except Exception as exc:
            db.rollback()
            logger.warning("shipment readback failed id=%s (%s)", identity, type(exc).__name__)
            print(f"[shipment_delivery] readback failed id={identity} ({type(exc).__name__})", flush=True)
