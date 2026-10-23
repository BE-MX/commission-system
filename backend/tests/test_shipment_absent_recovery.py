"""Original uncertain creation recovery, using only isolated SQLite fixtures."""
from copy import deepcopy
from threading import Lock
from sqlalchemy import inspect
from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.invoice import settlement_service as shipments
from tests.test_shipment_failed_cancel import failed_batch  # noqa: F401
from tests.test_presale_runtime import order  # noqa: F401
from tests.test_presale_runtime import USER
from app.invoice import shipment_absence_recovery as recovery, shipment_creation_facts as facts, shipment_delivery
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentOutbound, SettlementApplication, SettlementEvent, Receivable
from app.invoice.settlement_schemas import OutboundAbsenceRecovery
from app.receipt.models import Receipt, ReceiptLog


@pytest.fixture
def uncertain_batch(db, failed_batch):
    invoice, row, outbound, receipt = failed_batch
    row.state = 'outbound_uncertain'
    outbound.status = 'uncertain'
    db.commit()
    return invoice, row, outbound, receipt


def test_original_uncertain_batch_exposes_admin_recovery_without_freeing_funds(db, uncertain_batch):
    _, row, outbound, _ = uncertain_batch
    result = shipments.describe(db, row)
    action = result['actions'].get('recover_outbound', {})
    assert action.get('allowed') is True, 'Missing verified-absence recovery for the original uncertain task'
    assert action['requires_terminal_confirmation'] is True
    assert len(action['version']) == 64
    assert result['state'] == 'outbound_uncertain' and outbound.status == 'uncertain'
    assert result['receipt_applications'][0]['status'] == 'reserved'


@pytest.fixture
def command(db, uncertain_batch, monkeypatch):
    invoice, row, target, receipt = uncertain_batch
    # SQLite financial adapter only; real JWT/current grants/locks are covered
    # by the separately owned MySQL suite, not represented by these stubs.
    actor = {'allowed': True, 'calls': []}
    def current_user(session, user, *permissions):
        actor['calls'].append(permissions)
        if not actor['allowed']: raise HTTPException(403, 'Current authority revoked')
        return USER
    monkeypatch.setattr(recovery, 'lock_authority', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery.authority, 'current_user', current_user)
    monkeypatch.setattr(recovery.edit_authority, 'lock_document', lambda session, identity, **_: session.get(Invoice, identity))
    monkeypatch.setattr(recovery, 'require_delivery', lambda: None)
    view = shipments.describe(db, row)
    body = OutboundAbsenceRecovery(version=row.version,
        recovery_version=view['actions']['recover_outbound']['version'], original_request_closed=True,
        resolution_reference='OKKI ticket TEST-2026: original request terminated without creation',
        reason='Restore original task after external terminal verification')
    db.rollback()
    return invoice, row, target, receipt, body, actor


def protected(db):
    return {model.__tablename__: [[deepcopy(getattr(r, c.name)) for c in model.__table__.columns]
        for r in db.query(model).order_by(*model.__table__.primary_key.columns)]
        for model in (Invoice, InvoiceItem, Receipt, Receivable, SettlementApplication)}


def test_recovery_preserves_task_serial_payload_quote_and_all_money(db, command, monkeypatch):
    _, row, target, _, body, actor = command
    before = protected(db); quote = deepcopy(row.quote)
    fixed = {k: deepcopy(getattr(target, k)) for k in ('id', 'outbound_no', 'payload', 'payload_hash')}
    db.rollback(); calls = []
    def absent(session, serial):
        assert not session.in_transaction() and session.info.get('stock_executor_fence') is True
        calls.append(serial); return None
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', absent)
    monkeypatch.setattr(recovery.okki_client, 'push_outbound', lambda *_args, **_kwargs: pytest.fail('No POST in recovery'))
    result = recovery.recover(db, inspect(row).identity[0], body, USER)
    assert result['state'] == 'outbound_pending' and result['version'] == body.version + 1
    assert result['outbound']['id'] == target.id and result['outbound']['status'] == 'pending'
    assert result['quote'] == quote and protected(db) == before
    assert {k: getattr(target, k) for k in fixed} == fixed
    assert target.attempt_token is None and target.remote_id is None
    assert calls == [target.outbound_no] and actor['calls'] == [('shipment:write', 'shipment:admin')] * 2
    audit = facts.rows(db, target.id)[0]
    assert audit.action == facts.RECOVERED and audit.actor_id == 1
    assert audit.safe_diff_json['resolution_reference'] == body.resolution_reference
    assert audit.safe_diff_json['terminal_fact_source'] == 'employee_external_confirmation'
    assert db.query(SettlementEvent).filter_by(action='recover_outbound').count() == 1
    db.rollback()
    with pytest.raises(HTTPException): recovery.recover(db, inspect(row).identity[0], body, USER)
    assert db.query(ShipmentOutbound).count() == 1


@pytest.mark.parametrize('patch', [{'original_request_closed': False}, {'original_request_closed': 'true'},
    {'original_request_closed': None}, {'resolution_reference': '    '}, {'resolution_reference': 'x' * 201}])
def test_terminal_fact_must_be_explicit_strict_and_have_nonblank_reference(command, patch):
    body = command[4].model_dump()
    with pytest.raises(ValidationError): OutboundAbsenceRecovery(**{**body, **patch})
    body.pop('original_request_closed')
    with pytest.raises(ValidationError): OutboundAbsenceRecovery(**body)


@pytest.mark.parametrize('outcome', ['exists', 'timeout', 'malformed'])
def test_unavailable_or_existing_remote_never_restores(db, command, monkeypatch, outcome):
    _, row, target, _, body, _ = command
    before = protected(db); db.rollback()
    def lookup(*_):
        if outcome == 'timeout': raise recovery.okki_client.OkkiApiError('PRIVATE_PROVIDER_DETAIL')
        return {'outbound_invoice_id': '401', 'serial_id': target.outbound_no} if outcome == 'exists' else {}
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lookup)
    with pytest.raises(HTTPException) as raised: recovery.recover(db, inspect(row).identity[0], body, USER)
    assert raised.value.status_code == (409 if outcome == 'exists' else 503)
    assert 'PRIVATE_' not in raised.value.detail
    db.rollback()
    assert row.state == 'outbound_uncertain' and target.status == 'uncertain' and protected(db) == before


@pytest.mark.parametrize('change', ['authority', 'receipt', 'token', 'version', 'late_receipt', 'late_outbound'])
def test_remote_lookup_window_rechecks_current_actor_and_exact_graph(db, command, monkeypatch, change):
    _, row, target, receipt, body, actor = command
    def lookup(*_):
        if change == 'authority': actor['allowed'] = False
        elif change == 'receipt': receipt.remark = 'Concurrent edit'
        elif change == 'token': target.attempt_token = 'new_attempt'
        elif change == 'version': row.version += 1
        elif change == 'late_receipt': db.add(ReceiptLog(receipt_id=receipt.id, action='late_result', message='Late fact'))
        else: facts.remember_late_result(db, target, target.attempt_token, '401')
        db.commit(); return None
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lookup)
    with pytest.raises(HTTPException): recovery.recover(db, inspect(row).identity[0], body, USER)
    db.rollback()
    assert row.state == 'outbound_uncertain' and target.status == 'uncertain'
    assert db.query(SettlementEvent).filter_by(action='recover_outbound').count() == 0


def test_old_view_cannot_declare_a_new_attempt_terminal(db, command, monkeypatch):
    _, row, target, _, body, _ = command
    target.attempt_token = 'new_attempt_without_settlement_version_change'; db.commit()
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('Old declaration must not lookup'))
    with pytest.raises(HTTPException): recovery.recover(db, inspect(row).identity[0], body, USER)


@pytest.mark.parametrize('blocker', ['remote_id', 'baseline', 'lease', 'confirmation', 'late'])
def test_active_or_prior_remote_effect_blocks_recovery(db, command, monkeypatch, blocker):
    from app.core.time import beijing_now
    from app.invoice import shipment_confirmation_facts as confirm
    _, row, target, _, body, _ = command
    if blocker == 'remote_id': target.remote_id = '401'
    elif blocker == 'baseline': target.remote_line_snapshot = {'11': {'outbound_record_id': '501'}}
    elif blocker == 'lease': target.lease_until = beijing_now()
    elif blocker == 'confirmation': confirm.append(db, target.id, 'a' * 32, confirm.START, {'attempt_key': 'a' * 32}, 1)
    else: facts.remember_late_result(db, target, target.attempt_token, '401')
    db.commit()
    assert shipments.describe(db, row)['actions']['recover_outbound']['allowed'] is False
    db.rollback()
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('Ineligible target'))
    with pytest.raises(HTTPException): recovery.recover(db, inspect(row).identity[0], body, USER)


def test_busy_executor_fence_cannot_be_bypassed(db, command, monkeypatch):
    from app.invoice.stock_reservations import _sqlite_fences
    _, row, _, _, body, _ = command
    gate = _sqlite_fences.setdefault(db.get_bind(), Lock()); assert gate.acquire(blocking=False)
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lambda *_: pytest.fail('Sender still owns fence'))
    try:
        with pytest.raises(HTTPException) as raised: recovery.recover(db, inspect(row).identity[0], body, USER)
        assert raised.value.status_code == 409
    finally: gate.release()


def test_late_result_after_recovery_blocks_next_delivery(db, command, monkeypatch):
    _, row, target, _, body, _ = command
    old_token = target.attempt_token
    db.rollback()
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lambda *_: None)
    recovery.recover(db, inspect(row).identity[0], body, USER)
    facts.remember_late_result(db, target, old_token, '401'); db.commit()
    monkeypatch.setattr(recovery.okki_client, 'push_outbound', lambda *_args, **_kwargs: pytest.fail('Late result must block POST'))
    shipment_delivery.deliver(db, target.id)
    assert row.state == 'outbound_uncertain' and target.status == 'uncertain'
    assert facts.late_results(db, target.id)[0].safe_diff_json['remote_id'] == '401'


def test_dirty_caller_edit_is_not_rolled_back(db, command):
    invoice, row, _, _, body, _ = command
    invoice.customer_name = 'Unsaved unrelated edit'
    with pytest.raises(HTTPException): recovery.recover(db, inspect(row).identity[0], body, USER)
    assert invoice in db.dirty and invoice.customer_name == 'Unsaved unrelated edit'


def test_delivery_persists_a_late_success_instead_of_only_logging(db, command, monkeypatch):
    _, row, target, _, _, _ = command
    row.state = 'outbound_pending'; target.status = 'pending'; db.commit()
    monkeypatch.setattr(shipment_delivery, 'require_delivery', lambda: None)
    monkeypatch.setattr(shipment_delivery, '_refresh_funding', lambda *_: True)
    monkeypatch.setattr(shipment_delivery, '_dispatchable', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(shipment_delivery, '_live_candidate', lambda *_: deepcopy(target.payload))
    monkeypatch.setattr(shipment_delivery, 'require_additional', lambda *_: None)
    monkeypatch.setattr(shipment_delivery.okki_client, 'find_outbound_by_serial', lambda *_: None)
    tokens = []
    def push(session, payload, *, before_send):
        before_send()
        tokens.append(target.attempt_token)
        # Simulate recover_expired while the supplier response is in flight.
        target.status = 'uncertain'; target.lease_until = None; row.state = 'outbound_uncertain'
        session.commit()
        return {'outbound_invoice_id': '401'}
    monkeypatch.setattr(shipment_delivery.okki_client, 'push_outbound', push)
    shipment_delivery.deliver(db, target.id)
    events = facts.late_results(db, target.id)
    assert len(events) == 1 and events[0].safe_diff_json['remote_id'] == '401'
    assert events[0].safe_diff_json['attempt_token'] == tokens[0]
    assert target.remote_id is None and target.status == 'uncertain'
    events[0].safe_diff_json = {'remote_id': 'different'}
    with pytest.raises(ValueError, match='immutable'): db.flush()
    db.rollback()


@pytest.mark.parametrize('minute,expected', [(59, '2026-10-23T23:59:00'), (61, '2026-10-24T00:01:00')])
def test_recovery_observation_uses_beijing_date_across_midnight_on_a_western_host(db, command, monkeypatch, minute, expected):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from app.core import time as business_time
    instant = datetime(2026, 10, 23, 15, tzinfo=timezone.utc) + timedelta(minutes=minute)
    class WesternHostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None: return instant.astimezone(ZoneInfo('America/Los_Angeles')).replace(tzinfo=None)
            return instant.astimezone(tz)
    monkeypatch.setattr(business_time, 'datetime', WesternHostClock)
    _, row, target, _, body, _ = command
    monkeypatch.setattr(recovery.okki_client, 'find_outbound_by_serial', lambda *_: None)
    recovery.recover(db, inspect(row).identity[0], body, USER)
    audit = facts.rows(db, target.id)[0]
    assert audit.safe_diff_json['remote_observation']['observed_at'] == expected
    assert audit.created_at.isoformat() == expected
