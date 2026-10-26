"""Whole-order skipping is atomic, audited and never invents work or delivery."""
import pytest
from app.domestic import constants as C, order_skip_service, progress_service, report_service
from app.domestic.models import DomesticOrder, DomesticOrderItem, DomesticReportLog, DomesticSkipLog
from app.domestic.shipment_service import ready_units
from tests.test_domestic_conditional_routing import conditional_route, conditional_order, _submit


def test_skip_all_preserves_reports_replays_and_revokes(db, conditional_order):
    ctx = conditional_order
    _submit(db, ctx, 0, 3)
    first = order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'whole-order-skip', ctx.worker.id)
    assert first['status'] == C.ORDER_DONE and ctx.item.status == C.ITEM_DONE
    assert db.query(DomesticReportLog).count() == 1
    assert ctx.rows[0].completed_qty == 3 and ctx.rows[-1].completed_qty == 0
    assert ready_units(db, ctx.item)[0] == []
    logs = db.query(DomesticSkipLog).order_by(DomesticSkipLog.id).all()
    assert len(logs) == len(ctx.rows)
    replay = order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'whole-order-skip', ctx.worker.id)
    assert replay['replayed'] and db.query(DomesticSkipLog).count() == len(logs)
    report_service.revoke_manual_skip(db, logs[-1].id, ctx.worker.id)
    assert ctx.item.status == C.ITEM_PRODUCING
    order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'whole-order-skip', ctx.worker.id)
    assert ctx.item.status == C.ITEM_PRODUCING and logs[-1].revoked == 1
    with pytest.raises(ValueError, match='请求号'):
        order_skip_service.skip_all(db, ctx.item.order_id, '更换跳过原因文字', 'whole-order-skip', ctx.worker.id)


def add_unconfigured(db, ctx):
    item = DomesticOrderItem(order_id=ctx.item.order_id, line_no=2, product_id=ctx.item.product_id,
        product_name='未配路线', order_qty=1, unit_price=0, original_price=0, discount_amount=0,
        pricing_rule='legacy_manual', pricing_version='legacy', base_price_version_snapshot=0)
    db.add(item); db.commit()
    return item


def test_skip_all_failure_rolls_back_entire_order(db, conditional_order):
    ctx = conditional_order
    add_unconfigured(db, ctx)
    with pytest.raises(ValueError, match='未配工艺路线'):
        order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'atomic-skip-test', ctx.worker.id)
    assert db.query(DomesticSkipLog).count() == 0
    assert ctx.item.status == C.ITEM_PRODUCING
    assert not db.get(DomesticOrder, ctx.item.order_id).skip_all_records


def test_replay_never_skips_later_added_items(db, conditional_order):
    ctx = conditional_order
    order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'original-scope-test', ctx.worker.id)
    later = add_unconfigured(db, ctx)
    replay = order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'original-scope-test', ctx.worker.id)
    assert replay['replayed'] and later.status == C.ITEM_PRODUCING
    assert db.query(DomesticSkipLog).filter_by(item_id=later.id).count() == 0


def test_shipped_sibling_and_skipped_item_finish_order(db, conditional_order):
    ctx = conditional_order
    shipped = add_unconfigured(db, ctx)
    shipped.status = C.ITEM_SHIPPED
    db.commit()
    order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'mixed-order-test', ctx.worker.id)
    assert db.get(DomesticOrder, ctx.item.order_id).status == C.ORDER_DONE
    assert shipped.status == C.ITEM_SHIPPED
    assert db.query(DomesticSkipLog).filter_by(item_id=shipped.id).count() == 0


@pytest.mark.parametrize('status', [C.ORDER_DRAFT, C.ORDER_TERMINATED, C.ORDER_PENDING_REVIEW, C.ORDER_REJECTED])
def test_skip_all_rejects_frozen_orders(db, conditional_order, status):
    ctx = conditional_order
    db.get(DomesticOrder, ctx.item.order_id).status = status; db.commit()
    with pytest.raises(ValueError):
        order_skip_service.skip_all(db, ctx.item.order_id, '主管确认无需加工', 'frozen-order-test', ctx.worker.id)
    assert db.query(DomesticSkipLog).count() == 0


def test_skip_endpoint_enforces_specific_permission(db, conditional_order):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.domestic.router import router
    ctx = conditional_order
    current = {'sub': str(ctx.worker.id), 'permissions': ['domestic:write'], 'roles': []}
    app = FastAPI(); app.include_router(router, prefix='/api/domestic')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    payload = {'reason': '主管确认无需加工', 'request_id': 'endpoint-order-skip'}
    with TestClient(app) as client:
        url = f'/api/domestic/orders/{ctx.item.order_id}/skip-all'
        assert client.post(url, json=payload).status_code == 403
        current['permissions'] = ['domestic_skip:write']
        assert client.post(url, json={**payload, 'reason': '短'}).status_code == 422
        response = client.post(url, json=payload)
        assert response.status_code == 200 and response.json()['data']['status'] == C.ORDER_DONE
