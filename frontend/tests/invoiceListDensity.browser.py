"""Requested invoice list preview: synthetic data and in-memory APIs only."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:3056')
parser.add_argument('--output', default='tmp/invoice-list-requested-layout')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
url = args.base_url + '/tests/fixtures/invoice-list-density/index.html'

def open_page(browser, width=1920, height=1080, saved=None):
    page = browser.new_page(viewport={'width':width, 'height':height}, reduced_motion='reduce')
    page.set_default_timeout(12000)
    blocked, errors, warnings = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: warnings.append(message.text) if message.type in ('error', 'warning') else None)
    def route_request(route):
        parsed = urlparse(route.request.url)
        if parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path.startswith('/api/'):
            blocked.append(route.request.url)
            route.abort()
        else:
            route.continue_()
    page.route('**/*', route_request)
    page.add_init_script('''window.testClipboard={writes:[], fail:false};
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text => {
        if(window.testClipboard.fail) throw new Error('synthetic clipboard failure');
        window.testClipboard.writes.push(text);
      }}});
      document.execCommand = () => false;''')
    if saved is not None:
        page.add_init_script("localStorage.setItem('invoice-manage-table-view', " + json.dumps(json.dumps(saved)) + ")")
    page.goto(url)
    page.wait_for_load_state('networkidle')
    expect(page.locator('.invoice-table tbody tr')).to_have_count(10)
    expect(page.get_by_text('预览 · 全部模拟数据', exact=True)).to_be_visible()
    return page, blocked, errors, warnings

def assert_isolated(page, blocked, errors):
    assert not blocked, blocked
    assert not errors, errors
    assert not page.evaluate('invoiceDensityTest.writes'), page.evaluate('invoiceDensityTest.writes')

def measure(table):
    return table.evaluate('''table => {
      let wrap=table.querySelector('.el-scrollbar__wrap');
      let headers=[...table.querySelectorAll('thead th')].map(e => ({name:e.innerText.trim(),width:e.getBoundingClientRect().width,
        title:e.querySelector('[title]')?.getAttribute('title'), className:e.className}));
      let row=table.querySelector('tbody tr');
      return {clientWidth:wrap.clientWidth,scrollWidth:wrap.scrollWidth,headTop:table.querySelector('thead').getBoundingClientRect().top,
        headers,rowHeight:row.getBoundingClientRect().height,font:getComputedStyle(row.querySelector('td')).fontSize};
    }''')

metrics = {}
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width, height in [(1920,1080), (1366,900), (1440,900), (390,844)]:
        page, blocked, errors, warnings = open_page(browser, width, height)
        table = page.locator('.invoice-table')
        data = measure(table)
        metrics[f'{width}x{height}'] = data
        assert data['font'] == '13px', data
        cols = {header['name']: header['width'] for header in data['headers']}
        assert 152 <= cols['发票号'] <= 215, cols
        assert 84 <= cols['客户'] <= 200, cols
        assert cols['操作'] == 220, cols
        assert table.locator('thead th .cell').evaluate_all(
            '(cells) => cells.every(cell => cell.scrollWidth <= cell.clientWidth)'
        ), data
        assert 95 <= cols['型号/数量'] <= 125, cols
        assert 96 <= cols['应付合计'] <= 155, cols
        assert 84 <= cols['已回款'] <= 155, cols
        if width == 1920:
            assert data['scrollWidth'] <= data['clientWidth'], data
            assert [h['name'] for h in data['headers']] == ['发票号','客户','型号/数量','订单金额（GMV）','应付合计','已回款','订单/小满状态','操作'], data['headers']
        page.screenshot(path=str(out / f'overview-{width}x{height}.png'))
        table.scroll_into_view_if_needed()
        if width == 1920:
            table.screenshot(path=str(out / 'list-detail-1920.png'))
        if width == 1366:
            table.screenshot(path=str(out / 'list-left-1366.png'))
            table.locator('.el-scrollbar__wrap').first.evaluate('(e) => e.scrollLeft = e.scrollWidth')
            table.screenshot(path=str(out / 'list-right-1366.png'))
        if width == 390:
            assert page.evaluate('document.documentElement.scrollWidth') <= width
            wrap = table.locator('.el-scrollbar__wrap').first
            wrap.evaluate('(e) => e.scrollLeft = e.scrollWidth')
            assert wrap.evaluate('(e) => e.scrollLeft') > 0
        assert_isolated(page, blocked, errors)
        data['console'] = warnings
        page.close()

    page, blocked, errors, warnings = open_page(browser)
    table = page.locator('.invoice-table')
    rows = table.locator('tbody tr')
    first = rows.nth(0)
    expect(first.locator('.invoice-number-button')).to_have_text('TEST-1104')
    invoice_style = first.locator('.invoice-number-button').evaluate('e => ({size:getComputedStyle(e).fontSize,weight:getComputedStyle(e).fontWeight})')
    assert invoice_style == {'size':'14px','weight':'600'}, invoice_style
    expect(first.locator('.invoice-meta-line')).to_contain_text('库存单')
    expect(first.locator('.invoice-meta-line')).to_contain_text('2026-11-04')
    expect(first).to_contain_text('Example Salon')
    expect(first.locator('.invoice-model-quantity')).to_have_text('3 / 9')
    expect(first.locator('.invoice-model-quantity')).to_have_attribute('title', re.compile('含配件'))
    expect(first.locator('td').nth(3)).to_contain_text('1,234.56')
    expect(first.locator('td').nth(4)).to_contain_text('1,296.29')
    expect(first.locator('.invoice-sync-text')).to_have_text('小满：已同步')

    payment_cases = [('equal', '1,296.29', '--text-primary', '400'),
                     ('overpaid', '1,400.00', '--color-warning-text', '700'),
                     ('underpaid', '0.00', '--tag-danger-text', '700'),
                     ('unknown', '—', '--text-secondary', '400'),
                     ('equal', '0.30', '--text-primary', '400')]
    payment_metrics = []
    for i, (tone, value, token, weight) in enumerate(payment_cases):
        item = rows.nth(i).locator('.invoice-received')
        expect(item).to_have_class(re.compile('invoice-received--' + tone))
        expect(item).to_have_text(value)
        style = item.evaluate('''(el, token) => {const c=getComputedStyle(el); const probe=document.createElement('span');
          probe.style.color=`var(${token})`; document.body.appendChild(probe); let expected=getComputedStyle(probe).color; probe.remove();
          return {color:c.color,expectedColor:expected,weight:c.fontWeight,text:el.innerText}}''', token)
        assert style['color'] == style['expectedColor'] and style['weight'] == weight, style
        payment_metrics.append({'tone':tone, **style})
    settled_after_return = rows.nth(6).locator('.invoice-received')
    expect(settled_after_return).to_have_class(re.compile('invoice-received--equal'))
    expect(settled_after_return).to_have_text('700.00')
    metrics['paymentCases'] = payment_metrics

    copy = first.get_by_role('button', name='复制发票号 TEST-1104')
    initial_route = page.evaluate('invoiceDensityTest.route()')
    copy.click()
    expect(page.get_by_text('复制成功', exact=True)).to_be_visible()
    expect(copy.locator('.el-icon')).to_be_hidden()
    assert page.evaluate('testClipboard.writes') == ['TEST-1104']
    assert page.locator('.el-drawer:visible').count() == 0
    assert page.evaluate('invoiceDensityTest.route()') == initial_route
    expect(copy.locator('.el-icon')).to_be_visible()
    page.evaluate('testClipboard.fail = true')
    copy.click()
    expect(page.get_by_text('复制失败，请重试', exact=True)).to_be_visible()
    expect(copy.locator('.el-icon')).to_be_visible()
    assert page.evaluate('testClipboard.writes') == ['TEST-1104']
    assert page.locator('.el-drawer:visible').count() == 0
    assert page.evaluate('invoiceDensityTest.route()') == initial_route

    paid_header = table.locator('thead th').filter(has_text='已回款')
    assert paid_header.locator('.caret-wrapper').count() == 0
    for heading, field in [('型号/数量', 'item_count'), ('订单金额（GMV）', 'order_amount')]:
        table.locator('thead th').filter(has_text=heading).click()
        page.wait_for_function("field => invoiceDensityTest.requests.some(r => r.url === '/invoices' && r.params?.sort_field === field && r.params?.sort_order === 'asc')", arg=field)

    page.get_by_role('button', name='列显示设置').click()
    popup = page.locator('.el-popover:visible')
    for hidden in ('正式来源', '真实来源', '对比状态'):
        expect(popup).not_to_contain_text(hidden)
    for label in ('创建人', '创建时间'):
        popup.locator('.el-checkbox').filter(has_text=re.compile('^' + label + '$')).click()
    page.get_by_role('button', name='列显示设置').click()
    expect(table.locator('thead')).to_contain_text('创建人')
    expect(table.locator('thead')).to_contain_text('创建时间')
    page.get_by_role('button', name='列显示设置').click()
    page.get_by_role('button', name='恢复默认列与密度').click()
    page.get_by_role('button', name='列显示设置').click()
    expect(table.locator('thead')).not_to_contain_text('创建人')
    expect(table.locator('thead')).not_to_contain_text('创建时间')
    assert len(table.locator('thead th').all()) == 8
    long_number = rows.nth(3).locator('.invoice-number-button')
    assert long_number.evaluate('(e) => e.scrollWidth <= e.clientWidth')
    assert long_number.evaluate('(e) => e.clientHeight') > 24
    long_customer = rows.nth(3).locator('.invoice-customer-name')
    long_customer.hover()
    expect(page.get_by_role('tooltip').filter(has_text='A Very Long Synthetic Customer Company Name')).to_be_visible()

    before = {h['name']: h['width'] for h in measure(table)['headers']}
    search = page.get_by_role('textbox', name='搜索发票')
    search.fill('TEST-1104')
    search.press('Enter')
    expect(rows).to_have_count(1)
    page.wait_for_function("(w) => document.querySelector('th.invoice-col-customer_name').offsetWidth < w", arg=before['客户'])
    after = {h['name']: h['width'] for h in measure(table)['headers']}
    assert after['发票号'] < before['发票号'] and after['客户'] < before['客户'], (before, after)
    metrics['shortRowColumns'] = after
    assert_isolated(page, blocked, errors)
    page.close()

    old_keys = ['invoice_no','customer_name','order_type','invoice_date','item_count','order_amount','total_amount',
                'status','transaction_route','shadow_status','sync_status','created_by','created_at']
    old = {'version':1, 'knownColumnKeys':old_keys, 'density':'comfort', 'visibleKeys':old_keys}
    page, blocked, errors, warnings = open_page(browser, saved=old)
    saved = page.evaluate("JSON.parse(localStorage.getItem('invoice-manage-table-view'))")
    for key in ('invoice_no','customer_name','item_count','order_amount','total_amount','status','created_by','created_at'):
        assert key in saved['visibleKeys'], saved
    assert not set(('order_type','invoice_date','sync_status','transaction_route','shadow_status')) & set(saved['visibleKeys']), saved
    assert 'received_amount' in saved['visibleKeys'] and saved['density'] == 'comfort', saved
    assert_isolated(page, blocked, errors)
    page.close()
    browser.close()

(out / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: synthetic preview, payment tones, copy/failure, sorting and prior preferences')
