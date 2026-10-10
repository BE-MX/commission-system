"""Missing outbound models must remain visible in print and Word output."""
import io
from copy import deepcopy

import pytest
from docx import Document
from sqlalchemy import text

from app.shipping_inspection import outbound_service
from app.shipping_inspection.print_service import annotate_print_items
from tests.test_shipping_inspection import _pc_client, _user, product_display_source


@pytest.mark.parametrize('spec', [None, '', '   '])
def test_print_and_word_use_product_model_when_outbound_spec_is_blank(db, spec):
    model = 'B1天才发帘（帘宽12“）'
    db.execute(text('UPDATE lsordertest.okki_products SET model=:model WHERE product_id=101'), {'model': model})
    db.execute(text('UPDATE lsordertest.okki_outbound_record_items SET spec=:spec WHERE id=\'IT001\''), {'spec': spec})
    db.commit()
    original = outbound_service.list_outbound_items(db, 'OB001')
    with _pc_client(db, _user(db), [], roles=['super_admin']) as client:
        payload = client.get('/api/shipping-inspection/outbound-records/OB001/print-data')
        assert payload.status_code == 200
        printed = {item['item_id']: item for item in payload.json()['data']['items']}
        assert printed['IT001']['spec'] == model
        assert printed['IT001']['qty'] == 10
        assert printed['IT002']['spec'] == '14inch'  # Keep explicit outbound specs.
        response = client.get('/api/shipping-inspection/outbound-records/OB001/word')
        assert response.status_code == 200
        document = Document(io.BytesIO(response.content))
        assert model in [row.cells[2].text for row in document.tables[-1].rows[1:-1]]
    assert outbound_service.list_outbound_items(db, 'OB001') == original


def test_print_model_resolution_handles_snapshot_items_and_absent_products(db):
    items = [
        {'item_id': 'okki:1', 'product_id': '101', 'spec': '', 'model': None, 'qty': 4},
        {'item_id': 'okki:2', 'product_id': '999', 'product_name': 'Do not infer a model', 'spec': None, 'qty': 3},
        {'item_id': 'okki:3', 'product_id': '102', 'spec': None, 'model': None, 'qty': 5},
        {'item_id': 'okki:4', 'product_id': '101', 'spec': 'Outbound override', 'model': 'Catalog model', 'qty': 5},
        {'item_id': 'okki:5', 'product_id': None, 'spec': None, 'model': 'Joined model', 'qty': 1},
    ]
    original = deepcopy(items)
    result = annotate_print_items(db, items)
    assert [item['spec'] for item in result] == ['MODEL-13x4', None, None, 'Outbound override', 'Joined model']
    assert sum(item['qty'] for item in result) == 18
    assert [item['item_id'] for item in result] == [item['item_id'] for item in items]
    assert items == original
