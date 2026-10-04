from copy import deepcopy
from datetime import date

from app.order_intelligence import service


def test_customer_action_headers_sort_full_derived_result_before_page(monkeypatch):
    rows = {str(i): {'company_id': str(i), 'company_name': name, 'country': 'US', 'user_name': 'Owner',
                    'risk_status': 'due', 'profile_label': 'Profile', 'typical_cycle_days': i,
                    'last_order_date': date(2026, 1, i), 'expected_order_date': None, 'abnormal_date': None,
                    'overdue_days': i, 'lifetime_amount_usd': i * 100,
                    'top_models': [{'name': 'Model', 'quantity': i * 2}], 'top_colors': []}
            for i, name in [(1, 'Zulu'), (2, 'Alpha'), (3, 'Middle')]}
    monkeypatch.setattr(service, '_load_orders', lambda *a: [])
    monkeypatch.setattr(service, '_load_product_rows', lambda *a: [])
    monkeypatch.setattr(service, '_profile_analysis', lambda *a: {'customer_cycles': deepcopy(rows)})
    def query(field, direction, page=1):
        return service.get_customer_actions(None, None, date(2026, 10, 4), page, 1, sort_field=field, sort_order=direction)
    assert query('company_name', 'asc')['items'][0]['company_id'] == '2'
    assert query('lifetime_amount_usd', 'desc', 2)['items'][0]['company_id'] == '2'
    assert query('preference', 'asc')['items'][0]['company_id'] == '1'
    assert query('preference', 'desc')['items'][0]['company_id'] == '3'
    for field in ('country', 'user_name', 'risk_status', 'profile_label', 'typical_cycle_days', 'last_order_date',
                  'expected_order_date', 'abnormal_date', 'overdue_days', 'recommended_action'):
        assert query(field, 'asc')['total'] == 3
    assert rows['1']['last_order_date'] == date(2026, 1, 1)
