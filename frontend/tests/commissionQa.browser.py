"""Commission pages isolated browser QA. Run with Vite at 127.0.0.1:3077; all APIs mocked.

Covers: admin batch list/detail, my commission list/detail, dialogs, month grouping,
selected-row metrics linking, amount/rate formatting, 1440px/390px overflow.
"""
import sys

from playwright.sync_api import sync_playwright, expect

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3077'
FIXTURE_URL = BASE_URL + '/tests/fixtures/commission-qa.html'

batch = {
    'id': 1, 'batch_name': '2026年Q3提成', 'period_type': 'quarterly',
    'period_start': '2026-07-01', 'period_end': '2026-09-30', 'status': 'confirming',
    'confirmed_count': 1, 'expected_confirm_count': 3, 'confirmation_status': 'partial_confirmed',
    'feedback_count': 2, 'created_at': '2026-09-28 10:00:00',
}
my_batch = {
    'id': 1, 'batch_name': '2026年Q3提成', 'period_start': '2026-07-01', 'period_end': '2026-09-30',
    'status': 'confirming', 'is_confirmed_by_me': False, 'related_roles': ['salesperson', 'supervisor'],
    'total_payment_amount': 15234.5, 'detail_count': 2,
}
summary = {
    'batch_name': '2026年Q3提成', 'status': 'confirming',
    'total_payment_amount': 15234.5, 'total_salesperson_commission': 761.73,
    'total_supervisor_commission': 152.35, 'total_second_supervisor_commission': 0,
    'total_commission': 914.08, 'confirmed_count': 1, 'expected_confirm_count': 3, 'feedback_count': 2,
}
my_detail = {
    'batch': {**my_batch},
    'summary': {k: summary[k] for k in (
        'total_payment_amount', 'total_salesperson_commission', 'total_supervisor_commission',
        'total_second_supervisor_commission', 'total_commission')},
    'monthly_summary': [
        {'month': '2026-08', 'total_commission_usd': 300, 'average_exchange_rate': 7.12345, 'total_commission_rmb': 2137.04},
        {'month': '2026-09', 'total_commission_usd': 614.08, 'average_exchange_rate': 7.11, 'total_commission_rmb': 4366.11},
    ],
    'salesperson_details': [
        {'id': 11, 'collection_date': '2026-09-02', 'salesperson_name': 'QA', 'order_name': '订单A',
         'customer_name': 'Acme Corp', 'customer_country': 'US', 'payment_amount': 10000,
         'service_fee': 12.5, 'salesperson_rate': 0.05, 'salesperson_commission': 500,
         'type': 'TT', 'order_source': '阿里', 'calc_rule_note': '标准'},
        {'id': 12, 'collection_date': '2026-08-11', 'salesperson_name': 'QA', 'order_name': '订单B',
         'customer_name': 'Beta LLC', 'customer_country': 'DE', 'payment_amount': 5234.5,
         'service_fee': 0, 'salesperson_rate': 0.05, 'salesperson_commission': 261.73,
         'type': 'TT', 'order_source': '官网', 'calc_rule_note': '标准'},
    ],
    'supervisor_details': [
        {'id': 11, 'collection_date': '2026-09-02', 'salesperson_name': 'QA', 'order_name': '订单A',
         'customer_name': 'Acme Corp', 'customer_country': 'US', 'payment_amount': 10000,
         'service_fee': 12.5, 'supervisor_rate': 0.01, 'supervisor_commission': 100,
         'type': 'TT', 'order_source': '阿里', 'calc_rule_note': ''},
    ],
    'second_supervisor_details': [],
}
admin_details = {
    'items': [
        {'payment_id': 'PAY-1', 'order_id': 'SO-1', 'customer_name': 'Acme Corp', 'payment_amount': 10000,
         'salesperson_name': 'QA', 'salesperson_rate': 0.05, 'salesperson_commission': 500,
         'supervisor_name': 'Boss', 'supervisor_rate': 0.01, 'supervisor_commission': 100,
         'second_supervisor_name': None, 'second_supervisor_rate': None, 'second_supervisor_commission': None,
         'calc_rule_note': '标准'},
    ],
    'total': 1,
}
posted = {'feedback': 0, 'confirm': 0}


def api(route):
    request = route.request
    url = request.url.split('?')[0]
    if url.endswith('/commission/batch/list'):
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': {'items': [batch], 'total': 1}})
    if url.endswith('/commission/batch/1/summary'):
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': summary})
    if url.endswith('/commission/batch/1/details'):
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': admin_details})
    if url.endswith('/commission/self/batch/list'):
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': {'items': [my_batch], 'total': 1}})
    if url.endswith('/commission/self/batch/1'):
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': my_detail})
    if url.endswith('/commission/self/batch/1/feedback'):
        posted['feedback'] += 1
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': {}})
    if url.endswith('/commission/self/batch/1/confirm'):
        posted['confirm'] += 1
        return route.fulfill(json={'code': 200, 'message': 'ok', 'data': {}})
    raise AssertionError(f'Unexpected API: {request.method} {request.url}')


def open_page(page, route, width=1440):
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(FIXTURE_URL + '?route=' + route, wait_until='domcontentloaded', timeout=120000)
    page.wait_for_selector('.commission-page', timeout=120000)
    page.wait_for_load_state('networkidle')


def no_horizontal_overflow(page):
    return page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1')


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/v1/commission/**', api)

    # ── 管理端批次列表 ──
    open_page(page, '/commission/batch')
    expect(page.get_by_role('button', name='新建批次', exact=True)).to_be_visible()
    expect(page.locator('.el-table__row')).to_have_count(1)
    for name in ['明细', '撤销确认', '确认', '作废', '导出']:
        expect(page.get_by_role('button', name=name, exact=True).first).to_be_visible()
    page.get_by_role('button', name='导出', exact=True).click()
    expect(page.get_by_role('menuitem', name='按业务员', exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    page.get_by_role('button', name='新建批次', exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button', name='取消', exact=True).click()
    assert no_horizontal_overflow(page), 'batch list 1440px overflow'

    # ── 管理端批次明细：玻璃页头 + 指标卡 + 金额/比例口径 ──
    open_page(page, '/commission/batch/1/details')
    expect(page.locator('.commission-page-header h2')).to_have_text('2026年Q3提成')
    expect(page.locator('.commission-page-header .el-tag')).to_have_text('确认中')
    expect(page.locator('.commission-metric')).to_have_count(5)
    expect(page.locator('.commission-metric--payment strong')).to_have_text('$15,234.50')
    expect(page.locator('.commission-metric--total strong')).to_have_text('$914.08')
    expect(page.get_by_text('确认进度 1/3 · 反馈 2 条', exact=True)).to_be_visible()
    row = page.locator('.el-table__row').first
    expect(row.locator('td').nth(3)).to_have_text('$10,000.00')
    expect(row.locator('td').nth(5)).to_have_text('5.00%')
    expect(row.locator('td').nth(11)).to_have_text('-')
    assert no_horizontal_overflow(page), 'admin detail 1440px overflow'

    # ── 我的提成列表：指标卡联动 + 反馈/确认对话框 ──
    open_page(page, '/commission/my')
    expect(page.locator('.commission-metric')).to_have_count(5)
    expect(page.locator('.commission-metric--payment strong')).to_have_text('$15,234.50')
    expect(page.locator('.commission-selected-row')).to_have_count(1)
    page.get_by_role('button', name='问题反馈', exact=True).click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    dialog.locator('textarea').fill('回款金额有疑问')
    dialog.get_by_role('button', name='提交', exact=True).click()
    expect(page.get_by_text('反馈已提交', exact=True)).to_be_visible()
    assert posted['feedback'] == 1
    page.get_by_role('button', name='提交确认', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.locator('input').fill('我已确认')
    dialog.get_by_role('button', name='提交', exact=True).click()
    expect(page.get_by_text('确认成功', exact=True)).to_be_visible()
    assert posted['confirm'] == 1
    assert no_horizontal_overflow(page), 'my list 1440px overflow'

    # ── 我的提成明细：月度分组 + 选中月指标卡口径 ──
    open_page(page, '/commission/my/1/details')
    expect(page.locator('.commission-metric--payment strong')).to_have_text('$15,234.50')
    # cm-enter-N 必须带完整动画（独立审查 P1：只有 delay 没有 animation 的回归）
    for cls in ['.cm-enter', '.cm-enter-1']:
        anim = page.locator(cls).first.evaluate("el => getComputedStyle(el).animationName")
        assert anim.startswith('commission-surface-in'), (cls, anim)
    expect(page.locator('.month-table .el-table__row')).to_have_count(2)
    active_pane = page.locator('.el-tab-pane:visible')
    expect(active_pane.locator('.cm-month-group-row')).to_have_count(2)
    expect(active_pane.locator('.cm-detail-table .el-table__row')).to_have_count(4)
    page.locator('.month-table .el-table__row').filter(has_text='2026-08').click()
    expect(page.locator('.commission-selected-row')).to_have_count(1)
    expect(page.locator('.commission-metric--payment span')).to_have_text('回款总额 · 2026-08')
    expect(page.locator('.commission-metric--payment strong')).to_have_text('$5,234.50')
    page.get_by_role('tab', name='一级主管提成 (1)').click()
    active_pane = page.locator('.el-tab-pane:visible')
    expect(active_pane.locator('.cm-detail-table .el-table__row')).to_have_count(2)
    assert no_horizontal_overflow(page), 'my detail 1440px overflow'

    # ── 窄屏 390px ──
    for route in ['/commission/batch', '/commission/batch/1/details', '/commission/my', '/commission/my/1/details']:
        open_page(page, route, width=390)
        assert no_horizontal_overflow(page), f'{route} 390px overflow'

    browser.close()
    assert not errors, f'page errors: {errors}'
    print('commission QA ok: admin list/detail, my list/detail, dialogs, month grouping, 390px narrow')
