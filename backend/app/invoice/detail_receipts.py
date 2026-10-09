"""Verified funds and a deduplicated original-currency receipt view."""
import logging
from decimal import Decimal
from app.core.time import beijing_now
from app.invoice import detail_access, detail_receipt_snapshot, settlement_service
from app.invoice.settlement_models import Receivable, ShipmentSettlement
from app.receipt import balance, remote, service
from app.receipt.models import Receipt

logger = logging.getLogger(__name__)


def validate_finance(rows):
    if any(str(row.get("collect_status")) not in ("0", "1") for row in rows):
        raise ValueError("远端回款财务状态未明确，进度待核验")


def merge_rows(db, invoice, local, remote_rows, *, purpose="ordinary"):
    by_remote = {str(r["cash_collection_id"]): r for r in remote_rows}
    if len(by_remote) != len(remote_rows):
        raise ValueError("远端回款重复，待核对")
    result = []
    mapped = set()
    for row in local:
        data = service.describe(db, row, invoice)
        if row.status != "active" and str(row.xiaoman_receipt_id) in by_remote:
            raise ValueError("历史回款远端 ID 再次出现，请核对原单")
        match = by_remote.get(str(row.xiaoman_receipt_id)) if row.status == "active" else None
        if match:
            mapped.add(str(row.xiaoman_receipt_id))
            data["collect_status"] = match.get("collect_status")
        else:
            data["collect_status"] = None
        data["key"] = f"local:{row.id}"
        data["verified"] = bool(match)
        result.append(data)
    for identity, row in by_remote.items():
        if identity not in mapped:
            result.append({"key": f"remote:{identity}", "id": None, "receipt_no": row.get("cash_collection_no") or identity,
                "xiaoman_receipt_id": identity, "collection_date": row.get("collection_date"),
                "amount": str(remote.money(row.get("amount"))), "bank_charge": None,
                "currency": row.get("currency"), "purpose": purpose, "source": "remote",
                "sync_status": "synced", "collect_status": row.get("collect_status"), "verified": True,
                "status": "active", "attachment_count": 0, "remark": row.get("remark")})
    return result


def read(db, invoice, user, *, refresh=True):
    detail_access.require_receipts(db, invoice, user)
    local = db.query(Receipt).filter(Receipt.invoice_id == invoice.id).order_by(Receipt.id.desc()).all()
    items = [dict(service.describe(db, row, invoice), key=f"local:{row.id}", verified=False, collect_status=None) for row in local]
    result = {"state": "unverified", "items": items, "summary": None, "freight": None,
              "batch_balance": None, "checked_at": None, "message": "", "source": "live" if refresh else "background_snapshot"}
    payload = None
    snapshot_stamp = None
    try:
        if not refresh and invoice.xiaoman_order_id:
            payload, snapshot_stamp = detail_receipt_snapshot.load(db)
        if not refresh and not invoice.xiaoman_order_id:
            snapshot, snapshot_stamp = {"rows": []}, beijing_now()
            result["source"] = "local"
        else:
            snapshot = remote.order_snapshot(db, invoice) if refresh else detail_receipt_snapshot.order(payload, invoice)
        validate_finance(snapshot["rows"])
        summary = (settlement_service.goods_balance if invoice.order_type == "presale" else balance.calculate)(db, invoice, snapshot)
        items = merge_rows(db, invoice, [r for r in local if r.purpose != "freight"], snapshot["rows"])
        effective, total = Decimal(summary["effective_amount"]), Decimal(summary["total_amount"])
        summary.update(unpaid_amount=str(max(total - effective, Decimal(0))), overpaid_amount=str(max(effective - total, Decimal(0))))
        result.update(state="ready", items=items, summary=summary, checked_at=beijing_now() if refresh else snapshot_stamp)
    except Exception as exc:
        logger.warning("invoice funds verification unavailable invoice=%s: %s", invoice.id, type(exc).__name__)
        print(f"[invoice_detail] funds verification unavailable invoice={invoice.id}: {type(exc).__name__}", flush=True)
        result["message"] = str(exc) if isinstance(exc, ValueError) else "回款事实核验失败，请重试；已保留方舟关联记录"
    if invoice.order_type == "presale":
        targets = db.query(Receivable).join(ShipmentSettlement, ShipmentSettlement.id == Receivable.settlement_id).filter(
            Receivable.invoice_id == invoice.id, Receivable.kind == "freight", ShipmentSettlement.state != "cancelled").all()
        freight = {"state": "ready", "total_amount": "0", "effective_amount": "0", "registered_amount": "0", "message": "", "checked_at": None}
        totals = [Decimal(0), Decimal(0), Decimal(0)]
        freight_items = []
        try:
            if not refresh and payload is None and result["source"] != "local":
                raise ValueError("回款快照尚不可用，独立运费汇总待实时核验")
            for target in targets:
                rows = [r for r in local if r.receivable_id == target.id]
                if target.remote_status in ("failed", "uncertain"):
                    raise ValueError("独立运费目标失败或待核对，请在发货结算中核对原目标")
                if target.remote_order_id:
                    if not refresh and payload is None:
                        raise ValueError("回款快照尚不可用，请刷新实时核验")
                    snapshot = remote.target_snapshot(db, target) if refresh else detail_receipt_snapshot.freight(payload, target)
                else:
                    snapshot = {"rows": [], "target_binding": [target.id, target.remote_order_id, str(target.amount), target.currency, target.customer_id, target.version]}
                funds = balance.calculate_target(db, target, snapshot)
                validate_finance(snapshot["rows"])
                totals[0] += target.amount
                totals[1] += Decimal(funds["effective_amount"])
                totals[2] += Decimal(funds["registered_amount"])
                freight_items.extend(merge_rows(db, invoice, rows, snapshot["rows"], purpose="freight"))
            if {r.id for r in local if r.purpose == "freight" and r.status == "active"} != {r.id for t in targets for r in local if r.receivable_id == t.id and r.status == "active"}:
                raise ValueError("运费回款目标关联待核对")
            freight.update(total_amount=str(totals[0]), effective_amount=str(totals[1]), registered_amount=str(totals[2]), checked_at=beijing_now() if refresh else snapshot_stamp)
        except Exception as exc:
            logger.warning("invoice freight verification unavailable invoice=%s: %s", invoice.id, type(exc).__name__)
            print(f"[invoice_detail] freight verification unavailable invoice={invoice.id}: {type(exc).__name__}", flush=True)
            freight.update(state="unverified", total_amount=None, effective_amount=None, registered_amount=None,
                message=str(exc) if isinstance(exc, ValueError) else "独立运费核验失败，请重试")
            freight_items = [dict(service.describe(db, r, invoice), key=f"local:{r.id}", verified=False, collect_status=None) for r in local if r.purpose == "freight"]
        known = {r["key"] for r in freight_items}
        freight_items += [dict(service.describe(db, r, invoice), key=f"local:{r.id}", verified=False, collect_status=None) for r in local if r.purpose == "freight" and f"local:{r.id}" not in known]
        result["items"] = [r for r in result["items"] if r["purpose"] != "freight"] + freight_items
        result["freight"] = freight
        if refresh and detail_access.allowed(user, "shipment"):
            current = db.query(ShipmentSettlement).filter(ShipmentSettlement.invoice_id == invoice.id,
                ShipmentSettlement.state.in_(("awaiting_payment", "awaiting_verification"))).order_by(ShipmentSettlement.sequence.desc()).first()
            if current:
                try:
                    result["batch_balance"] = settlement_service.funding_balance(db, current) if result["state"] == "ready" and freight["state"] == "ready" else None
                except ValueError as exc:
                    logger.warning("invoice batch balance unavailable: %s", type(exc).__name__)
                    print("[invoice_detail] batch balance unavailable", flush=True)
    return result
