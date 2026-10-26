"""Real deletion decision with synthetic supplier GETs; no supplier writes."""
from types import SimpleNamespace
import pytest

from app.invoice import shipment_deleted_cancellation as cancels


@pytest.mark.parametrize('case', ['deleted', 'active', 'incomplete', 'changing', 'replacement',
    'id_missing_serial_readable', 'both_missing', 'shipped', 'wrong_customer'])
def test_exact_id_and_serial_observations_need_consistent_absence(monkeypatch, case):
    original = SimpleNamespace(remote_id='401', serial='TEST-02', customer_id='200',
        keep_freight=False)
    detail = {'outbound_invoice_id': '401', 'serial_id': 'TEST-02', 'company_info': {'id': '200'},
        'status': 1, 'create_time': '2026-10-23 23:01:10'}
    if case == 'shipped': detail['status'] = 2
    if case == 'wrong_customer': detail['company_info'] = {'id': '201'}
    monkeypatch.setattr(cancels.okki_client, 'ensure_access_token', lambda *_: 'isolated')
    monkeypatch.setattr(cancels.outbound_delete_client, '_request',
        lambda *_: None if case in {'id_missing_serial_readable', 'both_missing'} else detail)
    found = None if case == 'both_missing' else dict(detail,
        outbound_invoice_id='402' if case == 'replacement' else '401')
    monkeypatch.setattr(cancels.okki_client, 'find_outbound_by_serial', lambda *_: found)
    scans = []
    def page(_token, start, end, number):
        scans.append((start, end, number))
        assert start == '2026-10-23 00:00:00' and end == '2026-10-23 23:59:59'
        if case in {'active', 'id_missing_serial_readable'}:
            return [{'outbound_invoice_id': '401'}], 1
        if case == 'incomplete':
            return [], 1
        if case == 'changing':
            return [{'outbound_invoice_id': str(500 + len(scans))}], 1
        return [], 0
    monkeypatch.setattr(cancels.outbound_presence, '_page', page)
    if case in {'deleted', 'both_missing'}:
        proof = cancels._observe(None, original)
        assert proof['result'] == 'verified_deleted'
        assert len(scans) == (0 if case == 'both_missing' else 2)
    else:
        with pytest.raises(ValueError):
            cancels._observe(None, original)
        if case == 'id_missing_serial_readable':
            assert len(scans) == 1
