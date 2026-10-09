"""Exercise real shipment inputs and quotes with isolated API responses.

Usage: python tests/shipmentQuantity.browser.py http://127.0.0.1:3017
"""
import json
import sys
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1].rstrip('/')
invoice = {'id': 1, 'invoice_no': 'PI-PRIVATE-ONE', 'currency': 'USD', 'items': [
    {'id': 7, 'product_name': 'Product Z', 'quantity': 4},
    {'id': 8, 'product_name': 'Product A', 'quantity': 3},
    *[{'id': i + 9, 'product_name': f'Other product {i}', 'quantity': q}
      for i, q in enumerate([5, 5, 1, 1])],
]}
quotes, submissions, errors, unexpected = [], [], [], []

def api(route):
    path = route.request.url.split('/api/', 1)[1]
    body = route.request.post_data_json if route.request.method == 'POST' else None
    if path == 'invoice/invoices/1':
        data = invoice
    elif path == 'shipments/order/1':
        data = {'items': []}
    elif path == 'invoices/1/shipment-quotes':
        quotes.append(body)
        data = dict(quote_hash='a' * 64, goods_amount='80', packaging_amount='0',
                    handling_amount='0', freight_amount=body['freight_amount'],
                    deposit_applied='0', new_payment_due='80', is_final=False)
    elif path == 'invoices/1/shipment-settlements':
        submissions.append(body)
        data = dict(id=8, invoice_id=1, request_key=body['request_key'],
                    quote_hash=body['quote_hash'], version=1, settlement_no='S-TEST',
                    state='awaiting_payment', quote={})
    else:
        unexpected.append(path)
        route.fulfill(status=503, json={'detail': 'Unexpected isolated endpoint'})
        return
    route.fulfill(json={'code': 200, 'message': 'ok', 'data': data})

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route(base + '/api/**', api)
    page.goto(base + '/tests/shipmentSubmissionHarness.html')
    page.get_by_role('button', name='打开出库结算', exact=True).click()
    table = page.locator('.el-table').first
    expect(table.get_by_role('spinbutton')).to_have_count(6)
    preview = page.get_by_role('button', name='核算本批金额', exact=True)
    submit = page.get_by_role('button', name='生成本批结算单', exact=True)
    assert preview.evaluate('(el) => el.closest(".shipment-actions") !== null')
    box = preview.bounding_box()
    assert box['y'] >= 0 and box['y'] + box['height'] <= 900, box
    preview.click()
    expect(page.get_by_text('请填写本批出库数量', exact=True)).to_be_visible()
    assert not quotes, 'An empty batch must not reach the API'
    page.locator('.el-form-item').filter(has_text='本批运费').get_by_role('spinbutton').fill('20')
    page.keyboard.press('Tab')
    expect(page.get_by_text('请填写本批出库数量', exact=True)).to_be_visible()
    table.get_by_role('spinbutton').nth(0).fill('2')
    table.get_by_role('spinbutton').nth(1).fill('1')
    expect(page.get_by_text('请填写本批出库数量', exact=True)).to_have_count(0)
    expect(submit).to_be_disabled()
    preview.click()
    expect(submit).to_be_enabled()
    assert quotes[-1]['items'] == [{'invoice_item_id': 7, 'quantity': 2}, {'invoice_item_id': 8, 'quantity': 1}], quotes
    expect(page.get_by_text('请填写本批出库数量', exact=True)).to_have_count(0)
    # Sort rows, then edit by identity, ensuring values follow the invoice item.
    table.locator('th').filter(has_text='产品').click()
    row = table.locator('.el-table__body tr').filter(has_text='Product A')
    row.get_by_role('spinbutton').fill('2')
    page.keyboard.press('Tab')
    expect(submit).to_be_disabled()
    preview.click()
    expect(submit).to_be_enabled()
    assert quotes[-1]['items'] == [{'invoice_item_id': 7, 'quantity': 2}, {'invoice_item_id': 8, 'quantity': 2}], quotes
    row.locator('.el-input-number__increase').click()
    expect(submit).to_be_disabled()
    preview.click()
    expect(submit).to_be_enabled()
    assert quotes[-1]['items'][1] == {'invoice_item_id': 8, 'quantity': 3}
    # Emptying the batch must invalidate the quote and restore validation.
    for product in ['Product Z', 'Product A']:
        table.locator('.el-table__body tr').filter(has_text=product).get_by_role('spinbutton').fill('0')
        page.keyboard.press('Tab')
    expect(submit).to_be_disabled()
    count = len(quotes)
    preview.click()
    expect(page.get_by_text('请填写本批出库数量', exact=True)).to_be_visible()
    assert len(quotes) == count
    table.locator('.el-table__body tr').filter(has_text='Product A').get_by_role('spinbutton').fill('1')
    preview.click()
    expect(submit).to_be_enabled()
    assert quotes[-1]['items'] == [{'invoice_item_id': 8, 'quantity': 1}]
    submit.click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert submissions[-1]['items'] == quotes[-1]['items']
    assert not errors, errors
    assert not unexpected, unexpected
    print(json.dumps({'quotes': quotes, 'submission_items': submissions[-1]['items'], 'errors': errors}, ensure_ascii=False))
    browser.close()
