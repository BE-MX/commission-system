"""Request-local catalog reads for browsing only; checkout always re-resolves prices."""
from functools import cached_property

from sqlalchemy import and_, literal, select, union_all

from app.portal.models import CatalogGrant
from app.invoice import price_service
from app.invoice.models import PriceColorType, StdPrice


def _inputs(values, names):
    # Bound parameters only; chunks avoid driver/SQLite compound-select limits.
    for offset in range(0, len(values), 200):
        yield union_all(*(select(literal(index).label('lookup_id'),
            *(literal(value).label(name) for name, value in zip(names, entry)))
            for index, entry in enumerate(values[offset:offset + 200], offset))).subquery()


class BrowsePrices:
    def __init__(self, db, access, items):
        self.db, self.access = db, access
        self.metadata = [item.standard_json for item in items if isinstance(item.standard_json, dict)]

    @cached_property
    def overrides(self):
        return dict(self.db.execute(select(CatalogGrant.catalog_item_id, CatalogGrant.unit_price).where(
            CatalogGrant.access_id == self.access.id, CatalogGrant.status == "enabled")).all())

    @cached_property
    def rule(self):
        return price_service.get_customer_rule_row(self.db, self.access.okki_company_id)

    @cached_property
    def colors(self):
        codes = sorted({price_service.normalize_color(row.get('color')) for row in self.metadata} - {''})
        result = {}
        for inputs in _inputs([(code,) for code in codes], ('code',)):
            # Same SQL IN + LIMIT 1 as resolve_color_type: retain database collation
            # and index selection when both code and #code have explicit mappings.
            mapped = select(PriceColorType.color_type).where(
                PriceColorType.color_code.in_([inputs.c.code, literal('#') + inputs.c.code])
            ).correlate(inputs).limit(1).scalar_subquery()
            for index, value in self.db.execute(select(inputs.c.lookup_id, mapped)):
                code = codes[index]
                result[code] = value if value is not None else price_service._infer_color_type(code)
        return result

    def color_type(self, color):
        return self.colors.get(price_service.normalize_color(color))

    @cached_property
    def standards(self):
        keys = sorted({(price_service.normalize_length(row.get('length')),
                       price_service.normalize_text(row.get('price_unit')),
                       self.color_type(row.get('color')))
                      for row in self.metadata if self.color_type(row.get('color'))})
        grouped = {}
        for inputs in _inputs(keys, ('length', 'unit', 'color_type')):
            query = select(inputs.c.lookup_id, StdPrice).join(StdPrice, and_(
                StdPrice.product_kind == 'hair', StdPrice.length == inputs.c.length,
                StdPrice.weight_unit == inputs.c.unit, StdPrice.color_type == inputs.c.color_type))
            for index, row in self.db.execute(query):
                grouped.setdefault(keys[index], []).append(row)
        return grouped

    def resolve(self, standard):
        color_type = self.color_type(standard['color'])
        key = (price_service.normalize_length(standard['length']),
               price_service.normalize_text(standard['price_unit']), color_type)
        row = price_service.match_standard_price(self.standards.get(key, []), standard['product_display']) if color_type else None
        return {'standard_price': row.price if row else None,
                'customer_price': price_service.apply_rule(row.price, self.rule) if row else None,
                'currency': row.currency if row else 'USD', 'color_type': color_type}
