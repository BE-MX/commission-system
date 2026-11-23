"""Deterministic, read-only declaration/ticket/receipt reconciliation."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from app.cross_border.ticket_service import build_tickets

LABELS = {
    'no_invoice': '申报无发票', 'no_waybill': '申报无运单', 'amount_mismatch': '金额对不上',
    'split_below_floor': '分票低于产品金额', 'split_total_mismatch': '分票合计不符',
    'split_incomplete': '分票未发完', 'unknown_product_amount': '分票产品金额无法计算',
    'ambiguous_match': '配对歧义', 'missing_receipt': '缺收款单', 'orphan_receipt': '收款单无订单',
    'suspected_changed': '可能已被修改', 'not_picked_up': '未揽收', 'invoice_cancelled': '发票已取消',
    'ticket_without_declaration': '票无申报', 'unit_mismatch': '单位不统一', 'non_dhl': '非 DHL 承运',
    'non_usd': '非 USD 发票', 'go_live_not_configured': '尚未配置上线日期',
    'mixed_waybill': '同运单含非 9610 发票', 'split_missing_declaration': '分票组缺少申报',
    'non_usd_source': '申报或收款币制不是 USD',
    'exported_rebind': '导出报关后更换物流单',
}
WARNINGS = {'split_incomplete', 'orphan_receipt', 'suspected_changed', 'ticket_without_declaration',
            'unit_mismatch', 'non_dhl', 'mixed_waybill'}


def money(value):
    return Decimal(str(value or '0')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def issue(row, code, **details):
    if not any(i['code'] == code for i in row['issues']):
        row['issues'].append({'code': code, 'label': LABELS[code], 'blocking': code not in WARNINGS, **details})


def _order(item):
    return (item.first_import_id, item.first_row_no, item.id)


def _base(order_no, kind, identity):
    return {'order_no': order_no, 'row_type': kind, 'content_hash': identity, 'issues': [],
            'ticket': None, 'candidate_tickets': [], 'invoices': [], 'receipt_hash': None,
            'receipt_json': None, 'head_json': {}, 'line_json': {}, 'difference': None,
            'excluded': False, 'voided': False, 'exported': False, 'exported_id': None,
            'suspected_changed': False, 'blocking': False}


def reconcile(declarations, receipts, tickets_by_order, invoices_by_order, reviews=(), exports=()):
    """Pure domain calculation; callers may supply isolated/desensitized evidence."""
    rows, by_order, review_map, exported = [], defaultdict(list), defaultdict(list), {}
    for review in sorted(reviews, key=lambda r: r.id):
        review_map[review.content_hash].append(review)
    for batch in sorted(exports, key=lambda e: e.id):
        for identity in batch.content_hashes or []:
            exported[identity] = batch.id
    for declaration in sorted(declarations, key=_order):
        row = _base(declaration.order_no, 'declaration', declaration.content_hash)
        actions = review_map[declaration.content_hash]
        row.update(head_json=declaration.head_json, line_json=declaration.line_json,
                   first_import_id=declaration.first_import_id, last_import_id=declaration.last_import_id,
                   first_row_no=declaration.first_row_no, goods_value=money(declaration.head_json['goodsValue']),
                   suspected_changed=bool(getattr(declaration, 'suspected_changed', False)),
                   voided=declaration.status == 'voided' or any(a.action == 'void' for a in actions),
                   excluded=any(a.action == 'exclude' for a in actions),
                   exported=declaration.content_hash in exported, exported_id=exported.get(declaration.content_hash))
        row['invoices'] = invoices_by_order.get(declaration.order_no, [])
        row['candidate_tickets'] = tickets_by_order.get(declaration.order_no, [])
        row['reviews'] = [{'action': a.action, 'target': a.target, 'reason': a.reason,
                           'created_by': a.created_by, 'created_at': a.created_at} for a in actions]
        if any(str(data.get('currency', '')).strip().upper() not in {'502', 'USD'}
               for data in (row['head_json'], row['line_json'])):
            issue(row, 'non_usd_source')
        rows.append(row)
        if not row['voided']:
            by_order[declaration.order_no].append(row)
    receipt_buckets = defaultdict(list)
    for receipt in sorted(receipts, key=_order):
        receipt_buckets[(receipt.order_no, Decimal(receipt.receipt_json['charge']))].append(receipt)
    # Excluded declarations still own their historical receipt; voided versions do not.
    for row in rows:
        if row['voided']:
            continue
        bucket = receipt_buckets[(row['order_no'], Decimal(row['head_json']['goodsValue']))]
        if bucket:
            receipt = bucket.pop(0)
            row.update(receipt_hash=receipt.content_hash, receipt_json=receipt.receipt_json)
            if str(receipt.receipt_json.get('currency', '')).strip().upper() not in {'502', 'USD'}:
                issue(row, 'non_usd_source')
        else:
            issue(row, 'missing_receipt')
    for group in receipt_buckets.values():
        for receipt in group:
            row = _base(receipt.order_no, 'receipt', receipt.content_hash)
            row.update(receipt_hash=receipt.content_hash, receipt_json=receipt.receipt_json)
            issue(row, 'orphan_receipt')
            rows.append(row)
    for order_no in sorted(set(by_order) | set(tickets_by_order)):
        declarations_ = by_order[order_no]
        tickets = tickets_by_order.get(order_no, [])
        available = {t['shipment_tracking_id']: t for t in tickets}
        assigned = {}
        reserved = set()
        # Explicit choices take priority. Conflicting historical assignments block.
        for row in declarations_:
            choices = [a for a in review_map[row['content_hash']] if a.action == 'assign_ticket']
            if not choices:
                continue
            target = str(choices[-1].target)
            ticket = next((t for k, t in available.items() if str(k) == target), None)
            if ticket:
                row['ticket'] = ticket
                assigned[ticket['shipment_tracking_id']] = row
                available.pop(ticket['shipment_tracking_id'])
                row['_assigned'] = True
            else:
                issue(row, 'ambiguous_match')
        for row in declarations_:
            if row['ticket'] or any(i['code'] == 'ambiguous_match' for i in row['issues']):
                continue
            exact = [t for t in available.values() if t['kind'] == 'exact' and money(t['amount']) == row['goods_value']]
            uncertain = [t for t in available.values() if t['kind'] != 'exact']
            if exact and uncertain:
                issue(row, 'ambiguous_match')
                reserved.update(t['shipment_tracking_id'] for t in exact + uncertain)
                continue
            if exact:
                ticket = exact[0]
                row['ticket'] = ticket
                assigned[ticket['shipment_tracking_id']] = row
                available.pop(ticket['shipment_tracking_id'])
        for row in declarations_:
            if row['ticket'] or any(i['code'] == 'ambiguous_match' for i in row['issues']):
                continue
            uncertain = [t for t in available.values() if t['kind'] != 'exact']
            if uncertain:
                if any(t['shipment_tracking_id'] in reserved for t in uncertain):
                    issue(row, 'ambiguous_match')
                    continue
                ticket = uncertain[0]
                row['ticket'] = ticket
                assigned[ticket['shipment_tracking_id']] = row
                available.pop(ticket['shipment_tracking_id'])
        for row in declarations_:
            ticket, invoices = row['ticket'], row['invoices']
            if not invoices:
                issue(row, 'no_invoice')
            if not ticket and any(i['cancelled'] for i in invoices):
                issue(row, 'invoice_cancelled')
            if not ticket and any(i['currency'] != 'USD' for i in invoices):
                issue(row, 'non_usd')
            if invoices and not tickets and not any(i['cancelled'] or i['currency'] != 'USD' for i in invoices):
                issue(row, 'no_waybill')
            if not ticket and tickets and not any(i['code'] == 'ambiguous_match' for i in row['issues']):
                issue(row, 'amount_mismatch')
                exact = [t for t in tickets if t['kind'] == 'exact']
                if exact:
                    nearest = min(exact, key=lambda t: abs(row['goods_value'] - money(t['amount'])))
                    row['reference_ticket'] = nearest
                    row['difference'] = row['goods_value'] - money(nearest['amount'])
            if ticket:
                row['invoices'] = ticket['invoices']
                if ticket['kind'] == 'exact':
                    row['difference'] = row['goods_value'] - money(ticket['amount'])
                    if row['difference']:
                        issue(row, 'amount_mismatch')
                elif ticket['kind'] == 'split':
                    row['difference'] = Decimal(row['head_json']['goodsValue']) - ticket['product_floor']
                    if row['difference'] < 0:
                        issue(row, 'split_below_floor')
                elif not row.get('_assigned'):
                    issue(row, 'unknown_product_amount')
                confirmed = any(a.action == 'confirm_shipped' and a.target == ticket['shipment_tracking_id']
                                for a in review_map[row['content_hash']])
                if not ticket['picked_up'] and not confirmed:
                    issue(row, 'not_picked_up')
                if str(ticket['carrier']).upper() != 'DHL':
                    issue(row, 'non_dhl')
                if ticket.get('mixed_waybill'):
                    issue(row, 'mixed_waybill')
                if ticket.get('exported_rebind'):
                    issue(row, 'exported_rebind')
            if str(row['line_json'].get('unit', '')) != '015':
                issue(row, 'unit_mismatch')
            if row['suspected_changed']:
                issue(row, 'suspected_changed')
        _split_groups(tickets, assigned)
        for ticket in available.values():
            if ticket['picked_up']:
                row = _base(order_no, 'ticket', None)
                row.update(ticket=ticket, invoices=ticket['invoices'])
                issue(row, 'ticket_without_declaration')
                rows.append(row)
    for row in rows:
        row.pop('_assigned', None)
        row['blocking'] = any(i['blocking'] for i in row['issues'])
        row['can_export'] = row['row_type'] == 'declaration' and not (row['blocking'] or row['voided'] or row['excluded'])
    return rows


def _split_groups(tickets, assigned):
    """Connected components join split invoices sharing any ticket."""
    parent = {}
    def find(item):
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]
    split_ids = {p['invoice_id'] for t in tickets for p in t['parts'] if p['kind'] != 'exact'}
    for ticket in tickets:
        ids = [p['invoice_id'] for p in ticket['parts'] if p['invoice_id'] in split_ids]
        for identity in ids:
            parent[find(identity)] = find(ids[0])
    groups = defaultdict(set)
    for identity in split_ids:
        groups[find(identity)].add(identity)
    for ids in groups.values():
        members = [t for t in tickets if any(p['invoice_id'] in ids for p in t['parts'])]
        affected = [assigned[t['shipment_tracking_id']] for t in members if t['shipment_tracking_id'] in assigned]
        totals, expected, actual = {}, {}, defaultdict(Decimal)
        known = True
        for ticket in members:
            for part in ticket['parts']:
                if part['invoice_id'] not in ids:
                    continue
                identity = part['invoice_id']
                totals[identity] = part['total_amount']
                expected[identity] = part['expected']
                if part['quantities'] is None:
                    known = False
                else:
                    for item_id, qty in part['quantities'].items():
                        actual[(identity, item_id)] += qty
        complete = known and all(actual[(identity, item_id)] == qty for identity, items in expected.items() for item_id, qty in items.items())
        declared = sum((Decimal(r['head_json']['goodsValue']) for r in affected), Decimal(0))
        # Only subtract the whole-invoice portion of declarations counted in this subtotal.
        whole = sum((p['total_amount'] for r in affected for p in r['ticket']['parts']
                     if p['invoice_id'] not in ids), Decimal(0))
        expected_total = money(sum(totals.values(), Decimal(0)))
        for row in affected:
            row['split_group'] = {
                'declared_total': declared - whole, 'invoice_total': expected_total,
                'complete': complete and len(affected) == len(members),
                'shipped_quantity': sum(actual.values()) if known else None,
                'total_quantity': sum(q for lines in expected.values() for q in lines.values()),
            }
        if not complete:
            for row in affected:
                issue(row, 'split_incomplete')
            continue
        if len(affected) != len(members):
            for row in affected:
                issue(row, 'split_missing_declaration')
            continue
        difference = declared - whole - expected_total
        if difference:
            for row in affected:
                issue(row, 'split_total_mismatch', difference=str(difference))
                row['difference'] = difference


def build_rows(db, *, order_nos=None):
    from app.cross_border.models import Declaration, Receipt, Review, ExportBatch
    from app.core.config import get_settings
    declarations_query, receipts_query = db.query(Declaration), db.query(Receipt)
    if order_nos is not None:
        declarations_query = declarations_query.filter(Declaration.order_no.in_(order_nos))
        receipts_query = receipts_query.filter(Receipt.order_no.in_(order_nos))
    declarations, receipts = declarations_query.all(), receipts_query.all()
    identities = [d.content_hash for d in declarations]
    reviews = db.query(Review).filter(Review.content_hash.in_(identities)).all() if identities else []
    exports = db.query(ExportBatch).all()
    tickets, invoices = build_tickets(db, order_nos=order_nos)
    rows = reconcile(declarations, receipts, tickets, invoices, reviews, exports)
    if get_settings().CROSS_BORDER_GO_LIVE_DATE is None:
        for row in rows:
            if row['row_type'] == 'declaration':
                issue(row, 'go_live_not_configured')
                row.update(blocking=True, can_export=False)
    return rows
