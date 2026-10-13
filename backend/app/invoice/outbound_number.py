"""Recover ordinary-save renames from successful pushes of the same order."""
import json
import logging

from app.invoice.models import InvoiceSyncLog

logger = logging.getLogger(__name__)


def desired_serial(db, invoice, current_serial):
    rows = db.query(InvoiceSyncLog).filter(
        InvoiceSyncLog.invoice_id == invoice.id, InvoiceSyncLog.success == 1,
        InvoiceSyncLog.action.in_(['create', 'update']),
    ).order_by(InvoiceSyncLog.id.desc()).all()
    names = []
    for row in rows:
        try:
            payload = json.loads(row.request_digest or 'null')
            response = json.loads(row.response_body or 'null')
        except (ValueError, TypeError):
            logger.warning('Outbound number push evidence invalid log=%s', row.id)
            print(f'[outbound-number] invalid push evidence log={row.id}', flush=True)
            return None
        if (not isinstance(payload, dict) or not isinstance(response, dict)
                or str(response.get('order_id')) != str(invoice.xiaoman_order_id)
                or (row.action == 'update' and str(payload.get('order_id')) != str(invoice.xiaoman_order_id))
                or not isinstance(payload.get('name'), str) or not payload['name'].strip()):
            return None
        names.append(payload['name'].strip())
    if names and names[0] == invoice.invoice_no and current_serial in names[1:]:
        return invoice.invoice_no
    return None
