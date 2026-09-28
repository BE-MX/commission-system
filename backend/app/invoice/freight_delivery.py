"""Durable freight-order sender for presale settlements.

An ambiguous POST is never retried. The unique name is reserved in the local
ledger before any remote write, so early mirror rows can be classified.
"""
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import update

from app.core.time import beijing_now
from app.invoice import okki_client, xiaoman_service
from app.invoice.lifecycle_guard import ensure_active
from app.invoice.models import Invoice
from app.invoice.settlement_contract import build_freight_order_candidate
from app.invoice.settlement_models import Receivable, ShipmentSettlement
from app.invoice.settlement_policy import require_delivery
from app.invoice.settlement_service import digest
from app.receipt import remote


logger = logging.getLogger(__name__)


def _verify(target, detail, remote_id=None):
    try:
        return (str(detail.get("order_id")) == str(remote_id or target.remote_order_id)
                and detail.get("name") == target.remote_order_name
                and str(detail.get("company_id")) == str(target.customer_id)
                and detail.get("currency") == target.currency
                and remote.money(detail.get("amount")) == Decimal(target.amount)
                and remote.money(detail.get("product_total_amount")) == 0
                and int(detail.get("product_total_count")) == 0
                and detail.get("product_list") == [])
    except (TypeError, ValueError):
        return False


def _source_active(db, invoice):
    if not invoice.xiaoman_order_id:
        raise ValueError("预售主单尚无小满订单 ID")
    detail = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
    if (not remote.order_active(db, detail)
            or str(detail.get("order_id")) != str(invoice.xiaoman_order_id)
            or str(detail.get("company_id")) != str(invoice.customer_id)
            or detail.get("currency") != invoice.currency
            or remote.money(detail.get("amount")) != invoice.total_amount - Decimal(invoice.surcharge_amount or 0)):
        raise ValueError("预售主单已删除或客户、币种、金额变化，运费目标暂停发送")


def _matching_active_orders(db, target):
    """Fail closed unless the entire active creation-time range can be read twice."""
    params = {"start_time": target.created_at.date().isoformat(),
              "end_time": beijing_now().date().isoformat(), "time_type": 2,
              "removed": 0, "approval_with_draft": 1, "count": 100}
    def scan():
        seen, matches, total = set(), set(), None
        for page in range(1, 501):
            data = remote.read(db, "/v1/invoices/order/list", {**params, "start_index": page})
            rows, count = data.get("list"), data.get("count")
            if not isinstance(rows, list) or not str(count).isdigit():
                raise ValueError("小满有效订单列表不完整")
            if total is not None and total != int(count):
                raise ValueError("小满有效订单列表查询期间变化")
            total = int(count)
            for row in rows:
                identity = str(row.get("order_id") or "") if isinstance(row, dict) else ""
                if not identity.isdigit() or identity in seen:
                    raise ValueError("小满有效订单列表 ID 缺失或重复")
                seen.add(identity)
                if row.get("name") == target.remote_order_name:
                    matches.add(identity)
            if len(seen) == total:
                return matches
            if not rows or len(seen) > total:
                break
        raise ValueError("小满有效订单列表未完整读取")
    first, second = scan(), scan()
    if first != second:
        raise ValueError("小满运费订单列表发生变化，请稍后核对")
    return second


def freeze(db, target):
    """Persist the exact payload before a POST; never recompute on retry."""
    if target.kind != "freight" or not target.settlement_id or not target.remote_order_name:
        raise ValueError("运费应收目标身份不完整")
    if target.remote_payload is not None:
        if digest(target.remote_payload) != target.remote_payload_hash:
            raise ValueError("运费目标冻结载荷校验失败")
        return
    invoice = db.get(Invoice, target.invoice_id)
    settlement = db.get(ShipmentSettlement, target.settlement_id)
    if not invoice or not settlement or invoice.order_type != "presale":
        raise ValueError("运费目标所属预售结算不存在")
    payload, _, issues = xiaoman_service.build_push_payload(db, invoice)
    if issues or payload is None:
        raise ValueError("运费目标主单资料不完整：" + "；".join(x.get("message", "") for x in issues))
    candidate = build_freight_order_candidate(payload, settlement.settlement_no,
        invoice.xiaoman_order_id, target.customer_id, target.currency,
        settlement.created_at.date().isoformat(), target.amount)
    if candidate["payload"]["name"] != target.remote_order_name:
        raise ValueError("运费目标预留编号与冻结载荷不一致")
    target.remote_payload = candidate["payload"]
    target.remote_payload_hash = digest(candidate["payload"])
    target.version += 1


def _claim(db, target_id):
    target = db.get(Receivable, target_id)
    if target is None:
        return None
    invoice_id = target.invoice_id
    db.commit()  # End the identity lookup snapshot before the current locking reads.
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    ensure_active(invoice)
    db.refresh(target, with_for_update=True)
    settlement = db.get(ShipmentSettlement, target.settlement_id) if target.settlement_id else None
    if settlement:
        db.refresh(settlement, with_for_update=True)
    if (target.kind != "freight" or target.remote_status != "unverified"
            or target.remote_order_id or not settlement
            or settlement.state in {"cancelled", "paused", "review_required"}):
        db.rollback()
        return None
    require_delivery()
    freeze(db, target)
    token = uuid4().hex
    target.remote_status = "sending"
    target.attempt_token = token
    target.lease_until = beijing_now() + timedelta(minutes=30)
    target.last_error = None
    target.version += 1
    db.commit()
    return token


def _fence(db, target_id, token):
    count = db.execute(update(Receivable).where(
        Receivable.id == target_id, Receivable.attempt_token == token,
        Receivable.remote_status == "sending", Receivable.lease_until > beijing_now(),
    ).values(lease_until=beijing_now() + timedelta(minutes=5),
             version=Receivable.version + 1)).rowcount
    db.commit()
    if not count:
        raise ValueError("运费目标发送租约已失效，请核对原单")


def deliver(db, target_id):
    token = _claim(db, target_id)
    if token is None:
        return
    sent = False

    def before_send():
        nonlocal sent
        _fence(db, target_id, token)
        sent = True

    try:
        target = db.get(Receivable, target_id)
        if digest(target.remote_payload) != target.remote_payload_hash:
            raise ValueError("运费目标冻结载荷校验失败")
        payload = target.remote_payload
        db.commit()
        invoice = db.get(Invoice, target.invoice_id)
        _source_active(db, invoice)
        if _matching_active_orders(db, target):
            raise ValueError("小满已有同名运费订单，请按精确 ID 核对绑定")
        db.commit()
        result = okki_client.push_order(db, payload, before_send=before_send)
        identity = str(result.get("order_id") or "") if isinstance(result, dict) else ""
        if not identity.isdigit() or int(identity) <= 0:
            raise okki_client.OkkiOutcomeUncertainError("小满运费目标响应缺少订单 ID")
        count = db.execute(update(Receivable).where(
            Receivable.id == target_id, Receivable.attempt_token == token,
            Receivable.remote_status == "sending",
        ).values(remote_order_id=identity, remote_status="verifying",
                 lease_until=None, version=Receivable.version + 1)).rowcount
        db.commit()
        if count:
            refresh(db, target_id)
        else:
            logger.warning("late freight order result id=%s remote=%s", target_id, identity)
            print(f"[freight_delivery] late result id={target_id} remote={identity}", flush=True)
    except Exception as exc:
        db.rollback()
        logger.warning("freight target delivery failed id=%s (%s)", target_id, type(exc).__name__)
        print(f"[freight_delivery] failed id={target_id} ({type(exc).__name__})", flush=True)
        uncertain = (isinstance(exc, okki_client.OkkiOutcomeUncertainError)
                     or (sent and not isinstance(exc, (ValueError, okki_client.OkkiApiError))))
        target = db.get(Receivable, target_id)
        if target and target.attempt_token == token and target.remote_status in {"sending", "verifying"}:
            uncertain = uncertain or bool(target.remote_order_id)
            target.remote_status = "uncertain" if uncertain else "failed"
            target.last_error = ("小满运费订单结果待核对，禁止重新创建" if uncertain else
                                 "运费目标未发送：" + str(exc)[:450] if isinstance(exc, ValueError)
                                 else "小满拒绝运费目标，请检查权限和字段")
            target.lease_until = None
            target.version += 1
            db.commit()


def refresh(db, target_id):
    """Read a known ID only; a mismatched order remains quarantined."""
    target = db.get(Receivable, target_id)
    if not target or not target.remote_order_id:
        raise ValueError("运费目标尚无小满订单 ID")
    detail = remote.read(db, "/v1/invoices/order/info", {"order_id": target.remote_order_id})
    active = remote.order_active(db, detail)
    db.query(Invoice.id).filter(Invoice.id == target.invoice_id).with_for_update().one()
    db.refresh(target, with_for_update=True)
    if active and _verify(target, detail):
        target.remote_status = "bound"
        target.last_error = None
    else:
        target.remote_status = "uncertain"
        target.last_error = "小满运费订单身份或金额与冻结目标不一致，请核对原单"
    target.version += 1
    db.commit()
    return target.remote_status


def bind_exact(db, target_id, remote_id, expected_version):
    """Manual recovery of an unknown POST using a verified existing OKKI ID."""
    target = db.get(Receivable, target_id)
    if not target:
        raise ValueError("运费目标不存在")
    invoice_id = target.invoice_id
    detail = remote.read(db, "/v1/invoices/order/info", {"order_id": remote_id})
    if not remote.order_active(db, detail) or not _verify(target, detail, remote_id):
        raise ValueError("小满订单与冻结的运费目标不匹配，不能绑定")
    db.commit()
    db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    db.refresh(target, with_for_update=True)
    settlement = db.get(ShipmentSettlement, target.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if (settlement.version != expected_version or target.kind != "freight"
            or target.remote_status not in {"uncertain", "verifying", "failed"}
            or (target.remote_order_id and target.remote_order_id != remote_id)):
        raise ValueError("运费目标已变化，请刷新后核对")
    target.remote_order_id = remote_id
    target.remote_status = "verifying"
    target.last_error = None
    target.version += 1
    db.commit()
    return refresh(db, target_id)


def retry_failed(db, target_id, expected_version):
    """Only a definite pre-write rejection may get a fresh send attempt."""
    require_delivery()
    target = db.get(Receivable, target_id)
    if not target:
        raise ValueError("运费目标不存在")
    invoice_id = target.invoice_id
    if _matching_active_orders(db, target):
        raise ValueError("小满已有同名运费订单，请输入远端 ID 核对绑定")
    db.commit()
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    ensure_active(invoice)
    db.refresh(target, with_for_update=True)
    settlement = db.get(ShipmentSettlement, target.settlement_id)
    db.refresh(settlement, with_for_update=True)
    if (settlement.version != expected_version
            or settlement.state not in {"awaiting_payment", "awaiting_verification", "ready"}
            or target.remote_status != "failed" or target.remote_order_id):
        raise ValueError("运费目标不是可重试的明确失败状态")
    target.remote_status = "unverified"
    target.attempt_token = None
    target.lease_until = None
    target.last_error = None
    target.version += 1
    db.commit()
    return target.remote_status


def recover_expired(db):
    now = beijing_now()
    db.execute(update(Receivable).where(
        Receivable.kind == "freight", Receivable.remote_status == "sending",
        Receivable.lease_until < now,
    ).values(remote_status="uncertain", lease_until=None,
             last_error="运费目标发送中断，请核对小满原单，禁止重复创建",
             version=Receivable.version + 1))
    db.commit()


def process_pending(db):
    recover_expired(db)
    ids = [identity for (identity,) in db.query(Receivable.id).filter(
        Receivable.kind == "freight", Receivable.remote_status == "unverified",
    ).order_by(Receivable.id).limit(10)]
    db.commit()
    for identity in ids:
        try:
            deliver(db, identity)
        except Exception as exc:
            db.rollback()
            logger.warning("freight target worker failed id=%s (%s)", identity, type(exc).__name__)
            print(f"[freight_delivery] worker failed id={identity} ({type(exc).__name__})", flush=True)
