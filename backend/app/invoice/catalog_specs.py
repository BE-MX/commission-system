"""Bounded active-catalog specifications; no price, stock or customer lookup."""

import re
from sqlalchemy import text
from app.invoice import product_service


def normalized_length(value):
    return re.sub(r'(?:inches|inch|英寸|寸|["“”″])', '', str(value).casefold()).strip()


def can_read_specs(identity):
    return 'super_admin' in identity.get('roles', []) or bool(set(identity.get('permissions', [])).intersection({'invoice:read', 'invoice:write', 'invoice_price:read'}))


def lookup_specs(db, identity, terms, length=None):
    if not can_read_specs(identity):
        return {'status': 'permission_denied', 'matches': [], 'available_lengths': []}
    if not terms or len(terms) > 6 or any(not isinstance(term, str) or not 2 <= len(term) <= 80 for term in terms):
        raise ValueError('invalid product scope')
    columns = product_service._table_columns(db, 'okki_products')
    if not {'model', 'size', 'unit'}.issubset(columns):
        return {'status': 'unavailable', 'matches': [], 'available_lengths': []}
    schema = product_service._schema()
    params = {f'term{i}': '%' + term.casefold().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%' for i, term in enumerate(terms)}
    match = ' OR '.join(f"LOWER(p.model) LIKE :term{i} ESCAPE '!'" for i in range(len(terms)))
    scope = product_service._disable_filter('okki_products', columns, alias='p') + f' AND ({match})'
    sizes = db.execute(text(f'SELECT DISTINCT p.size FROM `{schema}`.okki_products p WHERE {scope} ORDER BY p.size LIMIT 31'), params).scalars().all()
    bounded_sizes = [str(size) for size in sizes[:30] if size]
    requested = normalized_length(length) if length else None
    length_filter = ''
    if requested:
        normalized = 'LOWER(p.size)'
        for marker in ['inches', 'inch', '英寸', '寸', '"', '“', '”', '″']:
            normalized = f"REPLACE({normalized}, '{marker}', '')"
        length_filter = f' AND TRIM({normalized}) = :length'
        params['length'] = requested
    # Exact requested lengths must not depend on the bounded overview list.
    statement = text(f'SELECT DISTINCT p.model, p.size, p.unit FROM `{schema}`.okki_products p WHERE {scope}{length_filter} ORDER BY p.model, p.size, p.unit LIMIT 21')
    rows = db.execute(statement, params).mappings().all()
    return {'status': 'matched' if rows else 'not_found', 'matched_by': 'family',
            'requested_length': requested, 'available_lengths': sorted(set(normalized_length(s) for s in bounded_sizes)),
            'matches': [dict(row) for row in rows[:20]], 'truncated': len(rows) > 20 or len(sizes) > 30,
            'scope': 'active_catalog_specifications_only',
            'limitations': 'Catalog entries are not stock availability or a sales commitment. Family matches are not one unique model. No match does not mean the product is unavailable for sale.'}
