"""Synthetic specifications only; never query price, stock or customer records."""
from types import SimpleNamespace
import pytest
from sqlalchemy import text
from app.invoice import product_service
from app.invoice.catalog_specs import lookup_specs
from app.whatsapp_translation.reply_catalog import retrieve_catalog


@pytest.fixture
def catalog(db, monkeypatch):
    monkeypatch.setattr(product_service.settings, 'BUSINESS_DB_NAME', 'lsordertest')
    db.execute(text('CREATE TABLE lsordertest.okki_products (model TEXT, size TEXT, unit TEXT, disable_flag INTEGER)'))
    db.execute(text("INSERT INTO lsordertest.okki_products VALUES ('Synthetic Weft A','14','20g',0),('Synthetic Weft B','14','30g',0),('Synthetic Weft A','18','25g',0),('Disabled Weft','14','99g',1),('Other Product','14','1g',0)"))
    return db


def test_directory_answers_length_weight_without_claiming_unique_model(catalog):
    result = lookup_specs(catalog, {'permissions': ['invoice_price:read']}, ['weft'], '14 inches')
    assert result['matched_by'] == 'family' and result['status'] == 'matched'
    assert result['available_lengths'] == ['14', '18']
    assert [row['unit'] for row in result['matches']] == ['20g', '30g']
    assert all(set(row) == {'model', 'size', 'unit'} for row in result['matches'])


def test_no_match_retains_known_lengths_without_claiming_unavailability(catalog):
    result = lookup_specs(catalog, {'roles': ['super_admin']}, ['weft'], '16')
    assert result['status'] == 'not_found' and result['matches'] == []
    assert result['available_lengths'] == ['14', '18']


def test_permission_denial_does_not_touch_database():
    assert lookup_specs(None, {'permissions': ['whatsapp_reply:write']}, ['weft'], '14')['status'] == 'permission_denied'


def test_catalog_is_bounded_and_wildcards_are_literal(catalog):
    for i in range(25):
        catalog.execute(text('INSERT INTO lsordertest.okki_products VALUES (:model, :size, :unit, 0)'), {'model': f'Synthetic Weft {i}', 'size': '14', 'unit': '20g'})
    result = lookup_specs(catalog, {'roles': ['super_admin']}, ['weft'], '14')
    assert len(result['matches']) == 20 and result['truncated']
    assert lookup_specs(catalog, {'roles': ['super_admin']}, ['weft%'], '14')['matches'] == []


def test_latest_query_drives_lookup_and_reports_outage_without_private_details(monkeypatch):
    from app.whatsapp_translation import reply_catalog
    calls = []
    monkeypatch.setattr(reply_catalog, 'lookup_specs', lambda db, actor, terms, length: calls.append((terms, length)) or {'status': 'matched'})
    request = SimpleNamespace(messages=[SimpleNamespace(role='salesperson', text='Synthetic Genius Weft.'), SimpleNamespace(role='customer', text='Is the 14 inch option 20g?')])
    assert retrieve_catalog(None, {}, request)['status'] == 'matched'
    assert calls == [(['genius', '天才'], '14')]


def test_requested_length_is_queried_even_outside_overview_limit(catalog):
    for i in range(40):
        catalog.execute(text('INSERT INTO lsordertest.okki_products VALUES (:model, :size, :unit, 0)'), {'model': 'Synthetic Weft', 'size': str(i), 'unit': '17g'})
    result = lookup_specs(catalog, {'roles': ['super_admin']}, ['weft'], '39 inches')
    assert result['status'] == 'matched' and result['matches'][0]['size'] == '39'
    assert result['truncated'] and len(result['available_lengths']) <= 30
