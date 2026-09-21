"""Administrator-reviewed remote changes; original facts remain in the audit log."""
import hashlib
import json
from datetime import date
from app.invoice import lifecycle_remote
from app.invoice.service import get_invoice
from app.receipt import remote, service


def evidence(db, row):
    if row.status != "active" or not row.xiaoman_receipt_id or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("仅已绑定小满的有效回款可核实远端变更")
    data = lifecycle_remote.read(db, "receipt", row.xiaoman_receipt_id)
    if data is None:
        # Verify the active index as well: a transient detail absence alone must
        # never release the reservation of a still-indexed receipt.
        if any(str(r["cash_collection_id"]) == row.xiaoman_receipt_id
               for r in remote.order_receipts(db, row.xiaoman_order_id)):
            raise ValueError("小满列表仍存在原回款，删除证据不一致，请稍后核对")
        current = None
    else:
        if str(data.get("order_id")) != row.xiaoman_order_id or data.get("currency") != row.currency:
            raise ValueError("远端回款已改关联订单或币种，请在小满恢复原关联后再处理")
        amount, charge = remote.money(data.get("amount")), remote.money(data.get("bank_charge"))
        if amount <= 0 or charge > amount or remote.money(data.get("real_amount")) != amount - charge:
            raise ValueError("远端回款金额、手续费或实到账不一致")
        if str(data.get("collect_status")) not in {"0", "1"}:
            raise ValueError("远端财务状态无效")
        current = {"amount": str(amount), "bank_charge": str(charge),
                   "collection_date": date.fromisoformat(str(data.get("collection_date"))[:10]).isoformat(),
                   "collect_status": int(data["collect_status"])}
    result = {"remote_id": row.xiaoman_receipt_id, "version": row.version,
              "before": {k: str(getattr(row, k)) for k in ("amount", "bank_charge", "collection_date", "collect_status")},
              "after": current}
    result["evidence_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def accept(db, row, body, actor):
    if not body.confirmed or len(body.reason.strip()) < 10:
        raise ValueError("请确认已核实实际收款及退款，并填写至少10字依据")
    # Token refresh can commit. Obtain the invoice and receipt locks again and
    # validate the reviewed version after every remote read.
    proof = evidence(db, row)
    get_invoice(db, row.invoice_id, for_update=True)
    db.refresh(row, with_for_update=True)
    if row.version != body.version or proof["version"] != row.version or proof["evidence_hash"] != body.evidence_hash:
        raise ValueError("回款或远端证据已变化，请重新预览后确认")
    if row.status != "active" or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("回款状态已变化，请刷新")
    if proof["after"] is None:
        row.status = "remote_deleted"
        row.collect_status = None
        row.last_error = "已核实小满删除；原ID与凭证保留。此操作不代表资金退款"
    else:
        data = proof["after"]
        row.amount, row.bank_charge = remote.money(data["amount"]), remote.money(data["bank_charge"])
        row.collection_date = date.fromisoformat(data["collection_date"])
        row.collect_status = data["collect_status"]
        row.sync_status, row.last_error = "synced", None
    row.version += 1
    service.log(db, row, "remote_change", json.dumps({"evidence": proof, "reason": body.reason.strip()}, ensure_ascii=False), actor)
