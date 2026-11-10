"""Recover ordinary-save renames from successful pushes of the same order."""
import json
import logging

from app.invoice import order_push_facts as facts
from app.invoice.models import InvoiceSyncLog

logger = logging.getLogger(__name__)


def _recorded_payload(db, invoice_id, order_id, action, key):
    if not isinstance(key, str) or not key:
        return None
    start = facts.get(db, invoice_id, key, facts.START)
    if start is None or start.object_type != 'invoice' or start.action != facts.START:
        return None
    data = start.safe_diff_json
    if (not isinstance(data, dict) or data.get('invoice_id') != invoice_id or data.get('attempt_key') != key
            or data.get('action') != action
            or (action == 'update' and str(data.get('original_order_id')) != order_id)):
        return None
    command = data.get('command_input')
    payload = command.get('original_payload') if isinstance(command, dict) else None
    if not isinstance(payload, dict) or data.get('payload_fingerprint') != facts.digest(payload):
        return None
    accepted = set()
    for record in facts.observations(db, invoice_id, key):
        observation = record.safe_diff_json
        if (not isinstance(observation, dict) or record.object_type != 'invoice'
                or record.action != facts.FACT or observation.get('attempt_key') != key
                or (record.object_public_id, record.access_id) != (start.object_public_id, start.access_id)):
            return None
        if observation.get('result_class') == 'accepted':
            accepted.add(str(observation.get('provider_reference')))
    return payload if accepted == {order_id} else None


def desired_serial(db, invoice, current_serial):
    if not current_serial or current_serial == invoice.invoice_no or not invoice.xiaoman_order_id:
        return None
    order_id = str(invoice.xiaoman_order_id)
    rows = db.query(InvoiceSyncLog).filter(
        InvoiceSyncLog.invoice_id == invoice.id, InvoiceSyncLog.success == 1,
        InvoiceSyncLog.action.in_(['create', 'update']),
    ).order_by(InvoiceSyncLog.id.desc()).all()
    names = []
    for row in rows:
        try:
            response = json.loads(row.response_body or 'null')
            if not isinstance(response, dict) or str(response.get('order_id')) != order_id:
                return None
            if 'attempt_reference' in response:
                payload = _recorded_payload(db, invoice.id, order_id, row.action, response['attempt_reference'])
            else:
                payload = json.loads(row.request_digest or 'null')
        except (ValueError, TypeError):
            logger.warning('Outbound number push evidence invalid log=%s', row.id)
            print(f'[outbound-number] invalid push evidence log={row.id}', flush=True)
            return None
        if (not isinstance(payload, dict)
                or (row.action == 'update' and str(payload.get('order_id')) != order_id)
                or not isinstance(payload.get('name'), str) or not payload['name'].strip()):
            return None
        names.append(payload['name'].strip())
    if names and names[0] == invoice.invoice_no and current_serial in names[1:]:
        return invoice.invoice_no
    return None
