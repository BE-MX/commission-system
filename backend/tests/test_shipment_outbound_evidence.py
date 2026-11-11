from types import SimpleNamespace

import pytest

from app.invoice import linked_outbound_service as outbound, shipment_create_service as shipment
from app.invoice import shipment_outbound_evidence as lookup
from app.invoice.settlement_service import check_outbounds
from app.invoice.settlement_models import OutboundLinkProof
from app.invoice.shipment_outbound_evidence import OutboundEvidenceNotReady
from app.receipt import remote


@pytest.mark.parametrize('scenario', ['stable', 'cross_customer_edit', 'deletion', 'list_changed',
                                      'same_ids_new_version', 'detail_changed', 'no_proofs',
                                      'invalid_proof', 'same_second_proof', 'other_account',
                                      'incomplete_live_detail', 'open_update_second', 'duplicate_live_line'])
def test_presale_evidence_uses_verified_versions_and_never_scans_all_details(db, monkeypatch, scenario):
    stamp = '2026-10-12 12:00:00'
    rows = [{'outbound_invoice_id': i, 'update_time': stamp, 'status': 1, 'company_info': {'id': 999},
             'product_total_count': 1} for i in range(1, 81)]
    if scenario != 'no_proofs':
        for row in rows:
            identity = row['outbound_invoice_id']
            db.add(OutboundLinkProof(
                source_key='other-account' if identity == 2 and scenario == 'other_account' else lookup.source_key(),
                outbound_id=str(identity), remote_version=stamp,
                listed_at=stamp if identity == 2 and scenario == 'same_second_proof' else '2026-10-12 12:00:01',
                remote_status='1', remote_quantity='1',
                order_ids=[None] if identity == 2 and scenario == 'invalid_proof' else ['321' if identity == 1 else '999'],
            ))
        db.flush()
    target = SimpleNamespace(xiaoman_order_id='321', currency='USD', customer_id='123',
                             id=1, total_amount=0, surcharge_amount=0)
    order = {'order_id': '321', 'create_time': '2026-10-12 00:00:00'}
    monkeypatch.setattr(remote, 'order_snapshot', lambda *_: {
        'rows': [], 'invoice_binding': remote.invoice_binding(target)})
    monkeypatch.setattr(remote, 'order_active', lambda *_: True)

    current = {row['outbound_invoice_id']: row for row in rows}
    if scenario == 'cross_customer_edit':
        current[2] = dict(current[2], update_time='2026-10-13 12:00:00', create_time='2026-10-01 12:00:00')
    if scenario == 'duplicate_live_line':
        current[2] = dict(current[2], product_total_count=2)
    if scenario == 'deletion':
        current.pop(1)  # A soft-deleted detail would still be readable by ID.
    list_calls = []

    def read(_db, path, params, **_options):
        if path.endswith('/order/info'):
            return order
        assert params['time_type'] == 1 and params['removed'] == 0
        list_calls.append(path)
        if len(list_calls) == 2 and scenario == 'list_changed':
            current.pop(1)
        if len(list_calls) == 2 and scenario == 'same_ids_new_version':
            current[2] = dict(current[2], update_time='2026-10-13 12:00:00')
        assert _options['include_envelope']
        return {'now': stamp if scenario == 'open_update_second' else '2026-10-14 00:00:00',
                'data': {'list': list(current.values()), 'count': len(current)}}

    monkeypatch.setattr(remote, 'read', read)
    requested = []

    def details(_db, identities, **_options):
        requested.extend(identities)
        related = {'1', '2'} if scenario == 'cross_customer_edit' else {'1'}
        result = [dict(current[int(identity)], record_list=[{
            'order_id': '321' if identity in related else '999',
            'order_record_id': identity, 'outbound_record_id': identity, 'outbound_count': 1,
        }]) for identity in identities]
        if scenario == 'detail_changed':
            result[0]['update_time'] = '2026-10-13 12:00:00'
        if scenario == 'incomplete_live_detail':
            result[0]['record_list'] = []
        if scenario == 'duplicate_live_line':
            result[1]['record_list'] *= 2
        return result

    monkeypatch.setattr(outbound, '_read_details', details)
    def collect():
        return shipment._evidence(db, target, ())
    if scenario == 'no_proofs':
        with pytest.raises(OutboundEvidenceNotReady):
            collect()
        assert requested == []
    elif scenario in {'list_changed', 'same_ids_new_version', 'detail_changed', 'open_update_second'}:
        with pytest.raises(outbound.OutboundListChanged):
            collect()
        assert requested == ([] if scenario == 'open_update_second' else ['1'])
    elif scenario == 'incomplete_live_detail':
        with pytest.raises(ValueError, match='明细数量与列表不一致'):
            collect()
    elif scenario == 'duplicate_live_line':
        with pytest.raises(ValueError, match='明细身份缺失或重复'):
            collect()
    else:
        evidence = collect()
        expected = {'cross_customer_edit': [1, 2], 'deletion': []}.get(scenario, [1])
        unverified = {'invalid_proof', 'same_second_proof', 'other_account'}
        assert requested == (['1', '2'] if scenario in unverified else [str(identity) for identity in expected])
        assert [row['outbound_invoice_id'] for row in evidence['outbounds']] == expected
        if scenario == 'cross_customer_edit':
            with pytest.raises(ValueError, match='尚未核对的远端出库'):
                check_outbounds(db, target, evidence)
