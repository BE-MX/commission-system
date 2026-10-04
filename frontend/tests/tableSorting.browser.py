"""Isolated table QA: mock APIs, never touch business data."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3079'
requests = []
evidence_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
if evidence_dir:
    evidence_dir.mkdir(parents=True, exist_ok=True)


def api(route):
    url = urlparse(route.request.url)
    params = parse_qs(url.query)
    requests.append(params)
    if 'supervisor' in url.path:
        rows = [{'salesperson_id': str(i), 'salesperson_name': f'业务员{i}', 'supervisor_id': str(i + 50),
                 'supervisor_name': f'主管{i}', 'second_supervisor_id': None,
                 'second_supervisor_name': None, 'effective_start': '2026-06-01'} for i in range(1, 46)]
    elif 'customer' in url.path:
        rows = [{'id': i, 'customer_id': str(i), 'customer_name': f'客户{i}', 'salesperson_name': f'业务员{i}',
                 'salesperson_rate': .02, 'salesperson_attribute': 'develop', 'is_complete': True,
                 'source': 'manual', 'first_receipt_date': '2026-06-01'} for i in range(1, 46)]
    else:
        raise AssertionError(f'Unexpected API {url.path}')
    field = params.get('sort_field', [''])[0]
    if field:
        rows.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=params.get('sort_order') == ['desc'])
    page = int(params.get('page', ['1'])[0]); size = int(params.get('page_size', ['20'])[0])
    route.fulfill(json={'code': 200, 'data': {'items': rows[(page - 1) * size:page * size], 'total': len(rows)}})


def assert_layout(page):
    boxes = page.evaluate('''() => {
      const box = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { top:r.top, bottom:r.bottom } };
      return { filter:box('.filter-bar'), actions:box('.action-bar'), table:box('.el-table') };
    }''')
    assert boxes['filter']['bottom'] <= boxes['actions']['top'] + 1, boxes
    assert boxes['actions']['bottom'] <= boxes['table']['top'] + 1, boxes


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/v1/**', api)
    page.goto(base + '/tests/fixtures/table-sorting/?route=/local')
    expect(page.locator('.el-table__row')).to_have_count(4)
    assert_layout(page)
    amount = page.locator('.el-table th', has_text='金额')
    amount.click()
    expect(page.locator('.el-table__row td:nth-child(3)')).to_have_text(['$2', '$20', '$100', '—'])
    amount.click()
    expect(page.locator('.el-table__row td:nth-child(3)')).to_have_text(['$100', '$20', '$2', '—'])
    amount.click()
    expect(page.locator('.el-table__row td:nth-child(3)')).to_have_text(['$100', '$2', '—', '$20'])
    name = page.locator('.el-table th', has_text='名称')
    name.locator('button').focus(); page.keyboard.press('Enter')
    expect(page.locator('.el-table__row td:nth-child(2)')).to_have_text(['订单1', '订单2', '订单3', '订单10'])
    assert page.locator('th', has_text='基本信息').locator('button').count() == 0
    assert page.locator('th', has_text='操作').locator('button').count() == 0
    native_amount = page.get_by_role('button', name='明细金额，点击升序')
    native_amount.focus(); page.keyboard.press('Space')
    expect(page.locator('.db-detail-table tbody td:nth-child(2)')).to_have_text(['2', '20', '100', '—'])
    expect(page.locator('.db-detail-table th').nth(1)).to_have_attribute('aria-sort', 'ascending')
    page.get_by_role('button', name='明细金额，点击降序').click()
    expect(page.locator('.db-detail-table tbody td:nth-child(2)')).to_have_text(['100', '20', '2', '—'])
    page.get_by_role('button', name='明细金额，点击取消排序').click()
    expect(page.locator('.db-detail-table tbody td:nth-child(2)')).to_have_text(['100', '2', '—', '20'])
    for route, label, field in [('/supervisor', '业务员ID', 'salesperson_id'), ('/customer', '客户ID', 'customer_id')]:
        for width in [1440, 768, 390]:
            page.set_viewport_size({'width': width, 'height': 1000})
            page.goto(base + '/tests/fixtures/table-sorting/?route=' + route)
            expect(page.locator('.el-table__row')).to_have_count(20)
            assert_layout(page)
            if evidence_dir and width in (1440, 390):
                page.locator('.table-card').screenshot(path=str(evidence_dir / f'{route[1:]}-{width}.png'))
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.get_by_role('button', name='下一页').click()
        page.wait_for_timeout(100)
        page.locator('th', has_text=label).click()
        page.wait_for_timeout(200)
        assert requests[-1]['sort_field'] == [field], requests[-1]
        assert requests[-1]['page'] == ['1'], requests[-1]
        page.get_by_role('button', name='全屏', exact=True).click()
        assert_layout(page)
        page.get_by_role('button', name='退出全屏', exact=True).click()
    assert not errors, errors
    browser.close()
print('PASS: real supervisor/customer layouts at 1440/768/390px, fullscreen, cross-page sort request, grouped local sorting and keyboard')
