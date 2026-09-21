import pytest
from tests.test_domestic_reporting import route, workers, craft_mapping, _item_of, _attrs, _seed_order_values, _pricing_customer, _zero_price_item
from app.domestic import unit_service, report_service
from app.domestic.unit_history_service import get_unit_history
from app.domestic.models import DomesticItemProgress, DomesticSkipLog, DomesticSkipUnit
from app.core.time import beijing_now


def test_history_is_per_piece_and_retains_revoked_and_skipped_events(db, craft_mapping, workers):
    from datetime import date
    from app.domestic.schemas import OrderCreate
    from app.domestic.order_service import create_order
    attrs = _attrs()
    _seed_order_values(db, attrs)
    customer = _pricing_customer(db, workers[0])
    created = create_order(db, OrderCreate(request_id='unit-history-order', order_no='history',
        order_date=date(2026, 9, 21), required_ship_date=date(2026, 9, 30), customer_id=customer.id,
        order_category='normal', order_type='first_order', order_channel='wechat',
        items=[_zero_price_item(db, attrs, 2, 'history-line')]), workers[0].id)
    item = _item_of(db, created['id'])
    units = unit_service.ensure_item_units(db, item)
    steps = db.query(DomesticItemProgress).filter_by(item_id=item.id).order_by(DomesticItemProgress.step_order).all()
    result = report_service.submit_report(db, item_id=item.id, progress_id=steps[0].id, qty=1,
        unit_id=units[0].id, user_id=workers[0].id, request_id='history-first')
    first = get_unit_history(db, units[0].id)
    second = get_unit_history(db, units[1].id)
    assert first['steps'][0]['status'] == '已报工'
    assert second['steps'][0]['status'] == '未报工'
    assert second['steps'][0]['records'] == []
    report_service.revoke_report(db, result['log_id'], workers[0].id)
    first = get_unit_history(db, units[0].id)
    assert first['steps'][0]['status'] == '未报工'
    assert first['steps'][0]['records'][0]['revoked'] is True
    skip = DomesticSkipLog(item_id=item.id, progress_id=steps[1].id, skip_qty=1,
        source='manual', created_by_user_id=workers[0].id)
    db.add(skip)
    db.flush()
    db.add(DomesticSkipUnit(skip_log_id=skip.id, progress_id=steps[1].id, unit_id=units[0].id))
    db.flush()
    assert get_unit_history(db, units[0].id)['steps'][1]['status'] == '已跳过'
    assert get_unit_history(db, units[1].id)['steps'][1]['status'] == '未报工'
    skip.revoked = 1
    skip.revoked_at = beijing_now()
    db.flush()
    assert get_unit_history(db, units[0].id)['steps'][1]['status'] == '未报工'


def test_unknown_unit_is_not_found(db):
    with pytest.raises(ValueError):
        get_unit_history(db, 999)



from tests.test_mini_navigation import context, grant


def test_unit_history_requires_current_domestic_permission_and_signature(context, monkeypatch):
    db, user, role, client = context
    url = '/domestic/unit-history/42?sign=invalid'
    assert client.get(url).status_code == 403
    grant(db, role, 'mini_domestic:write')
    assert client.get(url).status_code == 400
    from app.domestic import unit_history_service
    monkeypatch.setattr(unit_history_service, 'get_unit_history', lambda db, unit_id: {'unit_id': unit_id})
    sign = report_service.generate_unit_qr_data(42).split(':')[-1]
    assert client.get('/domestic/unit-history/42?sign=' + sign).json() == {'unit_id': 42}
    assert client.get('/domestic/unit-history/43?sign=' + sign).status_code == 400
