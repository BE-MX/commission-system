"""Isolated evidence for monetary and shipping reconciliation boundaries."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.cross_border.match_service import reconcile
from app.cross_border.ticket_service import calculate_part, in_scope, picked_up, build_tickets


def declaration(amount='100', identity=1, **kwargs):
    values = dict(id=identity, order_no='123456789012345', content_hash=f'd{identity}',
        first_import_id=1, last_import_id=1, first_row_no=identity + 2, status='active',
        head_json={'goodsValue': str(amount), 'currency': '502'}, line_json={'unit': '015', 'currency': '502'},
        suspected_changed=False)
    values.update(kwargs)
    return NS(**values)


def receipt(amount='100', identity=1, **kwargs):
    return NS(id=identity, order_no='123456789012345', content_hash=f'r{identity}',
        first_import_id=1, first_row_no=identity + 2,
        receipt_json={'charge': str(amount), 'currency': '502', 'accountingDate': f'202611{identity:02d}', **kwargs})


def invoice(identity=1, total='100', quantity=10, **kwargs):
    values = dict(id=identity, invoice_no=f'INV{identity}', order_type='stock', total_amount=Decimal(total),
        items=[NS(id=identity, quantity=quantity, total_price=Decimal(total), presale_archived=0)],
        sales_user_name='Sales', sales_user_id=1, internal_payment_method='新莱莎信保便捷发货',
        currency='USD', commerce_status='confirmed', express_channel='DHL9610',
        created_at=datetime(2026, 11, 23), alibaba_order_no='123456789012345')
    values.update(kwargs)
    return NS(**values)


def ticket(identity=1, amount='100', parts=None, **kwargs):
    from app.cross_border.ticket_service import invoice_view
    inv = invoice(total=amount or '100')
    part = dict(calculate_part(inv, {1: 10}), invoice_id=1, total_amount=Decimal(amount or '100'))
    values = dict(shipment_tracking_id=identity, kind='exact', amount=Decimal(amount) if amount is not None else None, product_floor=None,
        bound_at=datetime(2026, 11, identity), picked_up=True, carrier='DHL', waybill_no=f'WB{identity}',
        invoices=[invoice_view(inv)], parts=parts or [part], inspection_ids=[identity], logistics_status='in_transit')
    values.update(kwargs)
    return values


def run(ds, rs, ts, reviews=(), invoices=None):
    no = '123456789012345'
    return reconcile(ds, rs, {no: ts}, {no: invoices if invoices is not None else [i for t in ts for i in t['invoices']]}, reviews)


def codes(row):
    return {i['code'] for i in row['issues']}


def review(action, identity=1, target=None):
    return NS(id=identity, content_hash=f'd{identity}', action=action, target=target, reason='Verified',
              created_by=1, created_at=datetime(2026, 11, 23))


@pytest.mark.parametrize('amount,blocked', [('2196.282', False), ('2196.285', True)])
def test_round_half_up_invoice_comparison(amount, blocked):
    row = run([declaration(amount)], [receipt(amount)], [ticket(amount='2196.28')])[0]
    assert row['blocking'] is blocked
    assert ('amount_mismatch' in codes(row)) is blocked


def test_receipt_uses_exact_decimal_not_rounded_money():
    rows = run([declaration('2196.282')], [receipt('2196.284')], [ticket(amount='2196.28')])
    assert 'missing_receipt' in codes(rows[0])
    assert 'orphan_receipt' in codes(rows[-1])


def test_two_equal_receipts_different_accounting_dates_and_unit():
    ds = [declaration(identity=1), declaration(identity=2, line_json={'unit': '007', 'currency': '502'})]
    rows = run(ds, [receipt('100.00', 1), receipt('100.000', 2)], [ticket(1), ticket(2)])
    assert [r['receipt_hash'] for r in rows] == ['r1', 'r2']
    assert [r['ticket']['shipment_tracking_id'] for r in rows] == [1, 2]
    assert not rows[1]['blocking'] and 'unit_mismatch' in codes(rows[1])


def split_ticket(identity, inv, quantity, **kwargs):
    part = dict(calculate_part(inv, {inv.id: quantity}), invoice_id=inv.id, total_amount=inv.total_amount)
    return ticket(identity, parts=[part], kind=part['kind'], product_floor=part['product_amount'], amount=None, **kwargs)


def test_split_partial_then_complete_and_total_mismatch():
    inv = invoice(total='1100', quantity=10)
    inv.items[0].total_price = Decimal('1000')
    first, second = split_ticket(1, inv, 6), split_ticket(2, inv, 4)
    row = run([declaration('650')], [receipt('650')], [first])[0]
    assert not row['blocking'] and 'split_incomplete' in codes(row)
    rows = run([declaration('650'), declaration('450', 2)], [receipt('650'), receipt('450', 2)], [first, second])
    assert all(not r['blocking'] for r in rows)
    rows = run([declaration('650'), declaration('430', 2)], [receipt('650'), receipt('430', 2)], [first, second])
    assert all('split_total_mismatch' in codes(r) and r['difference'] == Decimal('-20') for r in rows)
    row = run([declaration('590')], [receipt('590')], [first])[0]
    assert 'split_below_floor' in codes(row)


def test_connected_group_with_two_split_invoices_and_whole_invoice():
    a, b, whole = invoice(1, '1100'), invoice(2, '550'), invoice(3, '80', 1)
    a.items[0].total_price, b.items[0].total_price = Decimal('1000'), Decimal('500')
    def part(inv, qty):
        return dict(calculate_part(inv, {inv.id: qty}), invoice_id=inv.id, total_amount=inv.total_amount)
    first = ticket(1, kind='split', amount=None, product_floor=Decimal('830'),
        parts=[part(a, 5), part(b, 5), part(whole, 1)])
    second = ticket(2, kind='split', amount=None, product_floor=Decimal('750'), parts=[part(a, 5), part(b, 5)])
    rows = run([declaration('930'), declaration('800', 2)], [receipt('930'), receipt('800', 2)], [first, second])
    assert all(not row['blocking'] for row in rows)
    rows = run([declaration('930'), declaration('780', 2)], [receipt('930'), receipt('780', 2)], [first, second])
    assert all('split_total_mismatch' in codes(row) for row in rows)


def test_missing_declaration_does_not_skip_completed_group_check():
    inv = invoice(total='1100')
    row = run([declaration('650')], [receipt('650')], [split_ticket(1, inv, 6), split_ticket(2, inv, 4)])[0]
    assert 'split_missing_declaration' in codes(row) and row['blocking']


def test_ambiguity_reserves_candidates_until_specialist_assignment():
    split = split_ticket(2, invoice(total='200'), 5)
    rows = run([declaration(), declaration('110', 2)], [receipt(), receipt('110', 2)], [ticket(), split])
    assert all('ambiguous_match' in codes(r) for r in rows[:2])
    assert all(r['ticket'] is None for r in rows[:2])
    rows = run([declaration(), declaration('110', 2)], [receipt(), receipt('110', 2)],
        [ticket(), split], [review('assign_ticket', target=1)])
    assert rows[0]['ticket']['shipment_tracking_id'] == 1
    assert rows[1]['ticket']['shipment_tracking_id'] == 2


def test_manual_actions_only_remove_their_own_blocker_and_hash():
    row = run([declaration('90')], [], [ticket(picked_up=False)],
        [review('confirm_shipped', target=1), review('assign_ticket', target=1)])[0]
    assert 'not_picked_up' not in codes(row)
    assert {'amount_mismatch', 'missing_receipt'} <= codes(row)
    row = run([declaration(identity=2)], [receipt()], [ticket(picked_up=False)], [review('confirm_shipped')])[0]
    assert 'not_picked_up' in codes(row)
    rebound = run([declaration()], [receipt()], [ticket(2, picked_up=False)], [review('confirm_shipped', target=1)])[0]
    assert 'not_picked_up' in codes(rebound)


def test_unknown_mapping_assignment_keeps_receipt_and_pickup_checks():
    part = dict(calculate_part(invoice(), None), invoice_id=1, total_amount=Decimal('100'))
    unknown = ticket(kind='unknown', amount=None, parts=[part], picked_up=False)
    row = run([declaration()], [], [unknown])[0]
    assert 'unknown_product_amount' in codes(row)
    row = run([declaration()], [], [unknown], [review('assign_ticket', target=1)])[0]
    assert 'unknown_product_amount' not in codes(row)
    assert {'missing_receipt', 'not_picked_up'} <= codes(row)


@pytest.mark.parametrize('source', ['head', 'line', 'receipt'])
def test_foreign_currency_never_compares_as_usd(source):
    d, r = declaration(), receipt()
    {'head': d.head_json, 'line': d.line_json, 'receipt': r.receipt_json}[source]['currency'] = '142'
    row = run([d], [r], [ticket()])[0]
    assert 'non_usd_source' in codes(row) and row['blocking']


def test_cancelled_or_foreign_invoice_does_not_block_other_matched_ticket():
    good = ticket()
    bad = dict(good['invoices'][0], id=99, cancelled=True, currency='EUR')
    row = run([declaration()], [receipt()], [good], invoices=good['invoices'] + [bad])[0]
    assert not row['blocking']
    row = run([declaration()], [receipt()], [], invoices=[bad])[0]
    assert {'invoice_cancelled', 'non_usd'} <= codes(row)


@pytest.mark.parametrize('code,expected', [('SM', False), ('pu', True), ('RS', True), ('???', False), ('', False), ('PY', False), ('RR', False)])
def test_pickup_uses_physical_events_and_both_identity_fields(code, expected):
    event = NS(waybill_no='WB', carrier='dhl', status_code=code)
    assert picked_up([event], 'WB', 'DHL') is expected
    assert not picked_up([event], 'OTHER', 'DHL')
    assert not picked_up([event], 'WB', 'FEDEX')


def test_go_live_uses_beijing_midnight_even_if_server_is_utc(monkeypatch):
    monkeypatch.setenv('TZ', 'UTC')
    inv = invoice(created_at=datetime(2026, 11, 22, 16, 0, tzinfo=timezone.utc))
    assert in_scope(inv, date(2026, 11, 23))
    inv.created_at = datetime(2026, 11, 22, 15, 59, tzinfo=timezone.utc)
    assert not in_scope(inv, date(2026, 11, 23))
    assert not in_scope(inv, None)
    inv.express_channel = 'FEDEX9610'
    assert not in_scope(inv, date(2026, 11, 21))


def test_line_level_quantities_and_net_discount_are_used():
    inv = invoice(total='1100')
    inv.items[0].total_price = Decimal('900')
    assert calculate_part(inv, {1: 6})['product_amount'] == Decimal('540')
    inv.items.append(NS(id=2, quantity=5, total_price=Decimal('100'), presale_archived=0))
    assert calculate_part(inv, {1: 5, 2: 10})['kind'] == 'unknown'


def test_voided_source_does_not_consume_receipt_and_export_identity_survives():
    d1, d2 = declaration(status='voided'), declaration(identity=2)
    rows = reconcile([d1, d2], [receipt()], {'123456789012345': [ticket()]},
        {'123456789012345': ticket()['invoices']}, exports=[NS(id=3, content_hashes=['d2'])])
    assert rows[0]['voided'] and not rows[0]['can_export']
    assert rows[1]['receipt_hash'] == 'r1' and rows[1]['exported_id'] == 3


def test_split_floor_and_group_compare_original_values_before_display_rounding():
    inv = invoice(total='100', quantity=3)
    one, two = split_ticket(1, inv, 1), split_ticket(2, inv, 2)
    rows = run([declaration('33.333'), declaration('66.668', 2)],
               [receipt('33.333'), receipt('66.668', 2)], [one, two])
    assert 'split_below_floor' in codes(rows[0])
    assert all('split_total_mismatch' in codes(r) for r in rows)
    assert rows[0]['split_group']['declared_total'] == Decimal('100.001')
