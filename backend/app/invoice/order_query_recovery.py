"""Bounded automatic first-stock-order recovery; never POST orders or receipts."""
import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.queue_scan import take
from app.core.time import beijing_now
from app.invoice import edit_authority, linked_sync_service, okki_client, outbound_mode
from app.invoice import order_push_facts as facts, order_query_plan as plan
from app.invoice import order_sync_execution as push, outbound_task_service, xiaoman_service, sync_recovery
from app.invoice.models import Invoice, InvoiceSyncLog
from app.portal.event_models import AuditEvent
from app.portal.errors import PortalError
from app.semifinished.models import InvoiceAllocation

logger = logging.getLogger(__name__)
CLAIM = 'invoice_order_query'
RESULT = 'invoice_order_query_result'
MAX_QUERIES = 3


def context(db, invoice_id, source):
    invoice, actor = edit_authority.prepare_recovery(db, invoice_id,
        {'id': source['original_actor_id']}, 'invoice:sync')
    attempt = invoice.sync_attempt or {}
    if (invoice.order_type != 'stock' or invoice.status != 'sync_uncertain'
            or invoice.sync_status != 'sync_uncertain' or invoice.xiaoman_order_id
            or invoice.linked_sync_id or source.get('auto_query_version') != 1
            or source.get('action') != 'create' or source.get('inventory_operation_key')
            or attempt.get('attempt_key') != source['attempt_key']
            or not attempt.get('lease_until')
            or datetime.fromisoformat(attempt['lease_until']) > beijing_now()):
        raise ValueError('Original attempt is not eligible for automatic order query')
    starts = facts.unresolved(db, invoice)
    if len(starts) != 1 or starts[0].safe_diff_json != source:
        raise ValueError('Original unresolved execution changed')
    records = facts.observations(db, invoice.id, source['attempt_key'])
    if not records or records[-1].safe_diff_json.get('result_class') != 'unknown':
        raise ValueError('Original request has no unknown response')
    if linked_sync_service.edit_version(invoice) != source['query_content_fingerprint']:
        raise ValueError('Original invoice content changed')
    if db.scalar(select(InvoiceAllocation.id).where(InvoiceAllocation.invoice_id == invoice.id)):
        raise ValueError('Semifinished allocations require manual recovery')
    payload, _, issues = xiaoman_service.build_push_payload(db, invoice)
    request = plan.request_snapshot(payload) if not issues else None
    if request != source['query_request'] or facts.digest(payload) != source['payload_fingerprint']:
        raise ValueError('Original request mapping changed')
    binding = (push.capture(db, invoice, payload), facts.observation_fingerprint(db, invoice.id, source['attempt_key']),
        sync_recovery.claim_binding(db,invoice,source['attempt_key']))
    lower, upper = plan.window(starts[0].created_at, source['query_window_end'])
    return invoice, actor, binding, lower, upper


def recover(db, invoice_id):
    if not db.info.get('stock_executor_fence'):
        raise RuntimeError('Automatic order recovery requires the shared executor fence')
    candidates = db.scalars(select(AuditEvent).where(AuditEvent.action == facts.START,
        AuditEvent.safe_diff_json['invoice_id'].as_integer() == invoice_id).order_by(AuditEvent.id.desc())).all()
    source = deepcopy(candidates[0].safe_diff_json) if candidates else None
    db.rollback(); db.expire_all()
    if not isinstance(source, dict) or source.get('auto_query_version') != 1:
        return {'status': 'deferred'}
    key = source['attempt_key']
    try:
        invoice, actor, binding, lower, upper = context(db, invoice_id, source)
        claims = [facts.get(db, invoice_id, key, CLAIM + ':' + str(n)) for n in range(1, MAX_QUERIES + 1)]
        used = [record for record in claims if record is not None]
        if len(used) == MAX_QUERIES or (used and
                datetime.fromisoformat(used[-1].safe_diff_json['next_query_at']) > beijing_now()):
            return {'status': 'deferred'}
        number = len(used) + 1
        start = facts.get(db, invoice_id, key, facts.START)
        facts.append(db, invoice_id, key, CLAIM + ':' + str(number), {
            'round': number, 'binding_fingerprint': facts.digest(binding),
            'next_query_at': (beijing_now() + timedelta(minutes=2 ** number)).isoformat()},
            start.object_public_id, start.access_id)
        target_amount, target_surcharge = invoice.total_amount, invoice.surcharge_amount
        db.commit(); db.expire_all()  # No authority, invoice or task row lock crosses GET.
        detail, outcome = None, 'unverified'
        try:
            access_token = push.token(db)
            deadline = monotonic() + 40
            def read(path, params):
                nonlocal access_token
                if db.in_transaction():
                    raise RuntimeError('Remote order query has an open database transaction')
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ValueError('Original order query time budget exhausted')
                data = okki_client._get_json(path, access_token, context='超时订单自动核对', params=params,
                                            timeout=min(10, remaining))
                if data is None:
                    access_token = push.token(db, force=True)
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise ValueError('Original order query time budget exhausted')
                    data = okki_client._get_json(path, access_token, context='超时订单自动核对', params=params,
                                                timeout=min(10, remaining))
                return data
            # The detached immutable view survives token cache expiration/reload.
            from types import SimpleNamespace
            target = SimpleNamespace(customer_id=source['query_request']['company_id'],
                currency=source['query_request']['currency'], total_amount=target_amount,
                surcharge_amount=target_surcharge)
            db.rollback(); db.expire_all()
            detail = plan.find(read, target, source['query_request'], lower, upper)
            outcome = 'verified'
        except (ValueError, KeyError, TypeError, ArithmeticError, HTTPException) as error:
            logger.warning('Automatic original order query unverified (%s)', type(error).__name__)
            print('[invoice-query] original order remains unverified', flush=True)
        finally:
            db.rollback(); db.expire_all()
        invoice, actor, current, _, _ = context(db, invoice_id, source)
        if current != binding:
            raise ValueError('Invoice, receipt or original facts changed during GET')
        start = facts.get(db, invoice_id, key, facts.START)
        result = {'round': number, 'outcome': outcome, 'order_post_count': 0}
        if detail is not None and outcome == 'verified':
            identity = str(detail['order_id'])
            facts.check_review(db, invoice, key, 'bind_order', identity)
            if db.scalar(select(Invoice.id).where(Invoice.xiaoman_order_id == identity).with_for_update()):
                raise ValueError('Provider order is already bound')
            validated = plan.verify(invoice, source['query_request'], detail, lower, upper)
            _, bindings, issues, _ = xiaoman_service._build_product_rows(db, invoice,
                xiaoman_service.get_settings_row(db), editing=True, reconciling=True)
            if issues or xiaoman_service._assign_unique_ids(invoice, bindings, validated):
                raise ValueError('Original response cannot bind local item identities')
            invoice.xiaoman_order_id = identity
            invoice.xiaoman_order_no = str(detail.get('order_no') or '') or None
            invoice.status = invoice.sync_status = 'synced'
            invoice.sync_error = None; invoice.sync_attempt = None; invoice.synced_at = beijing_now()
            invoice.outbound_auto_requested = int(source.get('query_outbound_requested') is True
                                                 and get_settings().OKKI_OUTBOUND_AUTO_ENABLED)
            facts.review(db, invoice, key, 'bind_order')
            db.add(InvoiceSyncLog(invoice_id=invoice.id, action='create', success=1, operator_id=actor['id'],
                request_digest=json.dumps({'name': invoice.invoice_no, 'recovery': 'automatic_get_only',
                    'original_attempt_key': key}), response_body=json.dumps({'order_id': identity,
                    'recovery': 'automatic_get_only', 'product_list': validated})))
            db.flush()
            if invoice.outbound_auto_requested:
                try:
                    with db.begin_nested():outbound_task_service.enqueue_outbound_task(db, invoice)
                except (ValueError,RuntimeError,SQLAlchemyError) as error:
                    logger.warning('Recovered order outbound enrollment requires recovery (%s)',type(error).__name__)
                    print('[invoice-query] outbound enrollment requires recovery',flush=True)
                    result['outbound_pending']=True
            sync_recovery.settle_original_claims(db,invoice,key,'automatic_original_get',detail,identity,formal=True)
            result['order_id'] = identity
            # Receipt intentions are deliberately not released by GET recovery.
        facts.append(db, invoice_id, key, RESULT + ':' + str(number), result,
            start.object_public_id, start.access_id)
        db.commit()
        return {'status': outcome}
    finally:
        db.rollback(); db.expire_all()


def run_once(factory):
    if not get_settings().INVOICE_ORDER_QUERY_RECOVERY_ENABLED:
        return {'status': 'disabled', 'processed': 0}
    counts = {'status': 'complete', 'processed': 0, 'verified': 0}
    with factory() as db:
        eligible = select(AuditEvent.id).where(AuditEvent.action == facts.START,
            AuditEvent.safe_diff_json['invoice_id'].as_integer() == Invoice.id,
            AuditEvent.safe_diff_json['auto_query_version'].as_integer() == 1).exists()
        query = db.query(Invoice.id).filter(Invoice.sync_status == 'sync_uncertain',
            Invoice.order_type == 'stock', eligible)
        ids = take(query, Invoice.id, 'invoice_order_query_recovery', 5)
        db.rollback()
    for identity in ids:
        with factory() as db:
            with outbound_mode.executor_fence(db) as acquired:
                if not acquired:
                    return {**counts, 'status': 'busy'}
                try:
                    result = recover(db, identity)
                    counts['processed'] += 1
                    counts['verified'] += int(result['status'] == 'verified')
                except (HTTPException, ValueError, KeyError, TypeError, SQLAlchemyError, PortalError) as error:
                    db.rollback(); db.expire_all()
                    logger.warning('Automatic order query deferred (%s)', type(error).__name__)
                    print('[invoice-query] current order requires manual review', flush=True)
                finally:
                    db.rollback()
    return counts
