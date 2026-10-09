"""Read-only employee proposal preparation; never creates acceptance or reserves stock."""
from copy import deepcopy
from types import SimpleNamespace

from app.core.time import beijing_now
from app.portal import admin_service, catalog_service, mapping_service, order_queries, proposal_service
from app.portal.domain import content_hash, normalize_text, total_amount


def managed(db, actor_id, public_id):
    actor, site, access, order = proposal_service.managed_request(db, actor_id, public_id)
    admin_service.employee_principal(db, actor_id, 'portal_order:read')
    return site, access, order


def catalog(db, actor_id, public_id, *, keyword='', page=1, page_size=20):
    site, access, order = managed(db, actor_id, public_id)
    proposal_service.require_proposable(db, site, access, order, order.row_version)
    aliases = {row['item_id']: row for row in mapping_service.current_projection(db, access)}
    needle = normalize_text(keyword).casefold()
    items = []
    for row in catalog_service.authorized_items(db, SimpleNamespace(site=site, access=access)):
        display = aliases[row.public_id]
        standard = row.standard_json
        haystack = ' '.join(str(value or '') for value in [display['model_name'], display['color_name'],
            display['customer_sku'], standard.get('model'), standard.get('color'), row.product_id, row.sku_id])
        if needle and needle not in normalize_text(haystack).casefold():
            continue
        items.append({'item_id': row.public_id, 'display_snapshot': deepcopy(display),
            'standard': {key: standard.get(key) for key in ('model', 'color', 'length', 'weight', 'product_display')},
            'product_id': str(row.product_id), 'sku_id': str(row.sku_id), 'product_kind': row.product_kind,
            'sale_unit': row.sale_unit, 'min_order_qty': row.min_qty, 'step_qty': row.step_qty})
    return {'request_id': order.public_id, 'row_version': order.row_version,
        'catalog_version': access.catalog_version, 'mapping_version': access.mapping_version,
        'items': items[(page - 1) * page_size:page * page_size], 'total': len(items),
        'page': page, 'page_size': page_size}


def preview(db, actor_id, public_id, expected, body):
    site, access, order = managed(db, actor_id, public_id)
    _, term, lines = proposal_service.prepare(db, site, access, order, expected, body)
    original = order_queries.detail_view(db, order, show_price=True)
    fields = ('item_id', 'display_snapshot', 'quantity', 'unit_price', 'discount_amount', 'line_amount', 'inventory_observed_at')
    proposed = [{key: deepcopy(line[key]) for key in fields} for line in lines]
    previous = {line['display_snapshot']['item_id']: line for line in original['items']}
    current = {line['item_id']: line for line in proposed}
    changes = []
    for item_id in sorted(previous.keys() | current.keys()):
        before, after = previous.get(item_id), current.get(item_id)
        changed = []
        if before and after:
            changed = [key for key in ('quantity', 'unit_price', 'discount_amount', 'line_amount', 'display_snapshot') if before[key] != after[key]]
        changes.append({'item_id': item_id, 'kind': 'added' if before is None else 'removed' if after is None else 'changed' if changed else 'unchanged',
            'changed_fields': changed, 'before': deepcopy(before), 'after': deepcopy(after)})
    fees = body.fees.model_dump(mode='json')
    products, total = total_amount([line['line_amount'] for line in lines], body.fees.shipping_amount,
        body.fees.packaging_amount, body.fees.surcharge_amount)
    return {'request_id': order.public_id, 'row_version': order.row_version,
        'input_hash': content_hash(body.model_dump(mode='json')), 'calculated_at': beijing_now().isoformat(),
        'currency': site.currency, 'items': proposed, 'changes': changes,
        'product_amount': format(products, '.2f'), 'fees': fees, 'total_amount': format(total, '.2f'),
        'previous_product_amount': original['product_amount'], 'previous_total_amount': original['total_amount'],
        'previous_fees': original['fees'], 'delivery': body.delivery.model_dump(mode='json'),
        'previous_delivery': original['delivery'], 'payment_terms_snapshot': term.model_dump(mode='json'),
        'previous_payment_terms_snapshot': original['payment_terms_snapshot'],
        'valid_for_hours': body.valid_for_hours, 'requires_customer_acceptance': True,
        'binding': False}
