"""Readonly display snapshots; never used to authorize a payment or send."""
from datetime import datetime, timedelta
from app.core.time import beijing_now
from app.receipt import receipt_index, remote


def load(db):
    payload = receipt_index._load(db, receipt_index._source())
    if payload is None:
        raise ValueError("回款快照尚未就绪，已显示方舟回款单；可刷新实时核验")
    stamp = datetime.strptime(payload["watermark"], "%Y-%m-%d %H:%M:%S")
    if beijing_now() - stamp > timedelta(minutes=2):
        raise ValueError("回款快照已超过2分钟，已显示方舟回款单；请刷新实时核验")
    return payload, stamp


def order(payload, invoice):
    return {"rows": [row for row in payload["rows"] if str(row["order_id"]) == str(invoice.xiaoman_order_id)],
            "invoice_binding": remote.invoice_binding(invoice)}


def freight(payload, target):
    if target.remote_status != "bound":
        raise ValueError("独立运费目标尚未核验，请刷新实时核验")
    return {"rows": [row for row in payload["rows"] if str(row["order_id"]) == str(target.remote_order_id)],
            "target_binding": [target.id, target.remote_order_id, str(target.amount),
                               target.currency, target.customer_id, target.version]}
