"""Xiaoman order sync boundary.

The official order endpoint requires Xiaoman-side customer/product/sku IDs.
This module keeps the external API integration isolated from invoice editing.
"""

from datetime import datetime

from app.invoice.models import Invoice
from app.invoice.service import validate_invoice


def sync_invoice(invoice: Invoice) -> dict:
    issues = validate_invoice(invoice)
    if issues:
        return {"ok": False, "message": "发票未通过同步前校验", "issues": issues}

    invoice.sync_status = "sync_failed"
    invoice.status = "sync_failed"
    invoice.sync_error = "小满接口凭证和价格/创建订单字段映射尚未配置，已完成本地同步前校验。"
    invoice.synced_at = datetime.utcnow()
    return {
        "ok": False,
        "message": invoice.sync_error,
        "issues": [],
    }

