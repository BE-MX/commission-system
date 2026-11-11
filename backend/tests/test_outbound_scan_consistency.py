"""A busy outbound list must not drift while unrelated details are being read."""
import pytest
from types import SimpleNamespace as NS
from fastapi import HTTPException
from sqlalchemy import event, text
from app.invoice import linked_outbound_service as outbound


ORDER = {'order_id': '123', 'create_time': '2026-10-09 08:00:00'}


def test_collects_pages_before_slow_details_can_reorder_list(monkeypatch):
    detail_started = False
    pages = []

    def read(_db, _path, params):
        page = params['start_index']
        pages.append(page)
        # A normal update moves row 2 ahead of row 1 without changing the total.
        identities = ([2, 1] if detail_started else [1, 2])
        return {'count': 2, 'list': [{'outbound_invoice_id': identities[page-1]}]}

    def details(_db, identities):
        nonlocal detail_started
        detail_started = True
        return [{'outbound_invoice_id': identity, 'record_list': [{'order_id': '123'}]}
                for identity in identities]

    monkeypatch.setattr(outbound.remote, 'read', read)
    monkeypatch.setattr(outbound, '_read_details', details)
    result = outbound.find_related(None, ORDER)
    assert {str(row['outbound_invoice_id']) for row in result} == {'1', '2'}
    assert pages == [1, 2, 1, 2]


def test_same_count_replacement_after_details_is_not_verified_absence(monkeypatch):
    detail_started = False

    def read(_db, _path, params):
        identities = [1, 3] if detail_started else [1, 2]
        return {'count': 2, 'list': [{'outbound_invoice_id': identity} for identity in identities]}

    def details(_db, identities):
        nonlocal detail_started
        detail_started = True
        return [{'outbound_invoice_id': identity, 'record_list': [{'order_id': '456'}]}
                for identity in identities]

    monkeypatch.setattr(outbound.remote, 'read', read)
    monkeypatch.setattr(outbound, '_read_details', details)
    with pytest.raises(outbound.OutboundListChanged, match='变化'):
        outbound.find_related(None, ORDER)


def test_incomplete_detail_batch_never_becomes_absence(monkeypatch):
    monkeypatch.setattr(outbound.remote, 'read', lambda *_: {
        'count': 2, 'list': [{'outbound_invoice_id': 1}, {'outbound_invoice_id': 2}]})
    monkeypatch.setattr(outbound, '_read_details', lambda *_: [])
    with pytest.raises(ValueError, match='详情'):
        outbound.find_related(None, ORDER)


def test_changed_page_count_stops_before_reading_any_details(monkeypatch):
    def read(_db, _path, params):
        page = params['start_index']
        return {'count': 2 if page == 1 else 3,
                'list': [{'outbound_invoice_id': page}]}
    def details(*_):
        pytest.fail('An incomplete list must never start detail reads')
    monkeypatch.setattr(outbound.remote, 'read', read)
    monkeypatch.setattr(outbound, '_read_details', details)
    with pytest.raises(outbound.OutboundListChanged, match='变化'):
        outbound.find_related(None, ORDER)


@pytest.mark.parametrize('operation', ['quote', 'create'])
@pytest.mark.parametrize('failure_kind', ['list_changed', 'proof_missing', 'bad_shape'])
def test_evidence_conflict_releases_transaction_without_business_write(db, monkeypatch, operation, failure_kind):
    from app.invoice import shipment_quote_service as quotes, shipment_create_service as facts
    from app.invoice.shipment_outbound_evidence import OutboundEvidenceNotReady
    invoice, user = NS(), {'sub': '1'}
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
            statements.append(statement)
    def authorize(*_):
        db.execute(text('SELECT 1'))
        return (invoice, user) if operation == 'quote' else (invoice, user, None)
    def evidence(*_):
        db.execute(text('SELECT 1'))
        if failure_kind == 'proof_missing':
            raise OutboundEvidenceNotReady('出库关联同步中')
        error = outbound.OutboundListChanged if failure_kind == 'list_changed' else ValueError
        raise error('private-provider-diagnostic')
    module = quotes if operation == 'quote' else facts
    monkeypatch.setattr(module, '_authorize', authorize)
    monkeypatch.setattr(facts, '_capture', lambda *_args, **_kwargs: ('hash', None, (), ()))
    monkeypatch.setattr(facts, '_evidence', evidence)
    monkeypatch.setattr(facts.inventory, 'capture', lambda _: None)
    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', observe)
    body = NS(items=[], payment=None, request_key='a' * 16)
    try:
        with pytest.raises(HTTPException) as failure:
            getattr(module, operation)(db, 1, body, user)
        assert failure.value.status_code == (503 if failure_kind == 'bad_shape' else 409)
        assert failure.value.headers['Cache-Control'] == 'private, no-store'
        assert 'private-provider-diagnostic' not in failure.value.detail
        if failure_kind == 'list_changed':
            assert failure.value.detail == '小满出库记录在核验期间发生变化，请重新获取报价'
        if failure_kind == 'proof_missing':
            assert failure.value.detail == '出库关联同步中'
        assert not statements and not db.in_transaction()
        assert not db.new and not db.dirty and not db.deleted
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
