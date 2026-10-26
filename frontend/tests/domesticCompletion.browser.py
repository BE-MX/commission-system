"""Actual Vue -> intercepted HTTP -> real service/SQLite, never shared database."""
import sys
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from tests.conftest import engine as engine_fixture, db as db_fixture
from tests.test_domestic_item_delete import saved_order
from tests.test_domestic_conditional_routing import conditional_route
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.domestic import order_service, progress_service
from app.domestic.router import router

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3089'
output = ROOT / 'tmp/domestic-completion-browser'
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width in (1440, 390):
        engine = engine_fixture.__wrapped__()
        generator = db_fixture.__wrapped__(engine)
        db = next(generator)
        user, customer, order, items = saved_order(db)
        route = conditional_route.__wrapped__(db)
        for item in items:
            item.route_id = route.id
            progress_service.init_item_progress(db, item)
        db.commit()
        app = FastAPI(); app.include_router(router, prefix='/api/domestic')
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: {'sub': str(user.id), 'roles': [], 'permissions': ['domestic:read', 'domestic:write', 'domestic_skip:write']}
        client = TestClient(app)
        context = browser.new_context(viewport={'width': width, 'height': 1000}, timezone_id='America/New_York', reduced_motion='reduce')
        page = context.new_page()
        errors, posts, unexpected = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def intercept(route):
            request = route.request
            parsed = urlparse(request.url)
            path = parsed.path
            if not path.startswith('/api/'):
                if parsed.hostname != '127.0.0.1':
                    route.abort(); return
                route.continue_(); return
            if path == '/api/domestic/orders':
                detail = order_service.get_order_detail(db, order.id)
                row = {**detail, 'item_count': 2, 'total_qty': sum(item.order_qty for item in items)}
                route.fulfill(json=jsonable_encoder({'code': 200, 'data': {'items': [row], 'total': 1}}), content_type='application/json'); return
            if path == '/api/domestic/options':
                route.fulfill(json={'code': 200, 'data': {'owners': [], 'order_categories': [], 'order_types': [], 'order_channels': []}}); return
            if path == '/api/domestic/process-routes':
                route.fulfill(json={'code': 200, 'data': []}); return
            if path == '/api/domestic/customers/options':
                route.fulfill(json={'code': 200, 'data': []}); return
            if path == f'/api/domestic/orders/{order.id}' or path.endswith('/terminate') or path.endswith('/skip-all'):
                if request.method == 'POST': posts.append((path, request.post_data_json))
                response = client.request(request.method, path, json=request.post_data_json if request.method == 'POST' else None)
                route.fulfill(status=response.status_code, body=response.content, content_type='application/json'); return
            unexpected.append(path)
            route.fulfill(status=503, json={'detail': 'Unexpected isolated API'})
        page.route('**/*', intercept)
        page.goto(base + '/tests/domesticWorkflowsHarness.html?tab=orders&testSkip=1')
        page.wait_for_load_state('networkidle')
        page.get_by_role('button', name='详情', exact=True).click()
        drawer = page.get_by_role('dialog', name='内贸订单详情')
        expect(drawer.get_by_role('button', name='一键跳过全部工序', exact=True)).to_be_visible()
        drawer.get_by_role('button', name='终止明细', exact=True).first.click()
        dialog = page.get_by_role('dialog', name='终止明细', exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role('spinbutton').fill('1')
        dialog.locator('textarea').fill('客户取消一件产品')
        page.screenshot(path=str(output / f'termination-{width}.png'), full_page=True)
        bounds = dialog.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1
        dialog.get_by_role('button', name='确认终止', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(drawer.get_by_text('已终止 1 件', exact=False)).to_be_visible()
        assert items[0].order_qty == 1 and customer.balance == 150
        assert posts[0][1]['qty'] == 1 and posts[0][1]['request_id']
        drawer.get_by_role('button', name='一键跳过全部工序', exact=True).click()
        box = page.locator('.el-message-box')
        expect(box).to_be_visible()
        box.locator('input').fill('主管确认无需继续加工')
        box.get_by_role('button', name='确认跳过', exact=True).click()
        expect(drawer.get_by_text('状态：已完成', exact=True)).to_be_visible()
        expect(drawer.get_by_role('button', name='一键跳过全部工序', exact=True)).to_have_count(0)
        expect(drawer.get_by_role('button', name='登记发货', exact=True)).to_have_count(0)
        page.screenshot(path=str(output / f'completed-{width}.png'), full_page=True)
        assert order.status == 2 and order.charged_amount == 150
        assert len(posts) == 2 and not errors and not unexpected, (errors, unexpected)
        print(f'{width}px: quantity cancel, refund, skip all and completed readback passed')
        context.close(); client.close(); generator.close(); engine.dispose()
    browser.close()
