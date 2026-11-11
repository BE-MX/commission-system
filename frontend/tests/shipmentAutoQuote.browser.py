"""Isolated browser regression for shipment auto quote; requires local Vite and Playwright.

Run: python frontend/tests/shipmentAutoQuote.browser.py [base_url]
All API calls are mocked; requests outside the local Vite origin are blocked.
"""
import asyncio
import json
import sys
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5179'
CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
FACTS = {name: str(index) * 64 for index, name in enumerate(
    ('items', 'amounts', 'exchange_rates', 'funding', 'outbounds', 'freight', 'document'), start=1)}


async def run_case(browser, width, case):
    context = await browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
    page = await context.new_page()
    errors, unexpected, quotes, submissions = [], [], [], []
    active = max_active = 0
    hold = asyncio.Event()
    hold_second = asyncio.Event()
    hold_started = asyncio.Event()
    invoice = {'id': 1, 'invoice_no': 'TEST-AUTO-QUOTE', 'currency': 'USD',
               'items': [{'id': 7, 'product_name': '测试产品', 'quantity': 10}]}
    page.on('pageerror', lambda error: errors.append(str(error)))

    async def respond(route, data):
        await route.fulfill(json={'code': 200, 'message': 'ok', 'data': data})

    async def route_request(route):
        nonlocal active, max_active
        request = route.request
        if not request.url.startswith(BASE + '/'):
            unexpected.append('external ' + request.url)
            return await route.abort()
        path, method = urlsplit(request.url).path, request.method
        if not path.startswith('/api/'):
            return await route.continue_()
        if method == 'GET' and path == '/api/invoice/invoices/1':
            return await respond(route, invoice)
        if method == 'GET' and path == '/api/invoices/1/shipment-inventory':
            return await respond(route, {'invoice_id': 1, 'source': 'okki_live', 'warehouse_id': '17',
                'queried_at': '2026-10-16T00:01:00', 'items': [{'invoice_item_id': 7,
                'product_id': None, 'sku_id': None, 'available_stock': '100', 'reason': ''}]})
        if method == 'GET' and path == '/api/shipments/order/1':
            return await respond(route, {'items': []})
        if method == 'POST' and path == '/api/invoices/1/shipment-quotes':
            body = request.post_data_json
            quotes.append(body)
            index = len(quotes)
            active += 1
            max_active = max(max_active, active)
            try:
                if case in ('race', 'clear', 'close') and index == 1:
                    hold_started.set()
                    await hold.wait()
                if case == 'race' and index == 2:
                    await hold_second.wait()
                quantity = body['items'][0]['quantity']
                return await respond(route, {'quote_hash': str(index) * 64, 'quote_facts': FACTS,
                    'goods_amount': str(quantity * 10), 'packaging_amount': '0', 'handling_amount': '0',
                    'freight_amount': '0', 'deposit_applied': '0', 'advance_applied': '0',
                    'new_payment_due': str(quantity * 10), 'is_final': False, 'pool_balances': []})
            finally:
                active -= 1
        if method == 'POST' and path == '/api/invoices/1/shipment-settlements':
            submissions.append(request.post_data_json)
            if case == 'stale':
                return await route.fulfill(status=409, json={'detail': 'QUOTE_STALE：商品单价已变化，请重新核算后提交'})
            if case == 'timeout':
                return await route.abort('timedout')
        unexpected.append(method + ' ' + path)
        await route.abort()

    await page.route('**/*', route_request)
    try:
        await page.goto(BASE + '/tests/shipmentSubmissionHarness.html')
        await page.get_by_role('button', name='打开出库结算', exact=True).click()
        spin = page.locator('.shipment-products-table').get_by_role('spinbutton').first
        await spin.wait_for()
        await page.get_by_text('小满预售出库仓库', exact=False).wait_for()

        async def quantity(value):
            await spin.fill(str(value))
            await spin.press('Tab')

        async def wait_quotes(count):
            for _ in range(100):
                if len(quotes) >= count:
                    return
                await page.wait_for_timeout(50)
            raise AssertionError(f'{case}: expected {count} quote requests, got {quotes}')

        async def wait_amount(amount):
            await page.locator('.quote-summary').get_by_text(f'USD {amount:.2f}', exact=True).first.wait_for()

        if case == 'race':
            await quantity(1)
            await page.wait_for_timeout(150)
            await quantity(2)
            await page.wait_for_timeout(150)
            await quantity(3)
            await page.wait_for_timeout(400)
            assert not quotes, quotes
            await asyncio.wait_for(hold_started.wait(), 5)
            assert len(quotes) == 1 and quotes[0]['items'][0]['quantity'] == 3, quotes
            await quantity(4)
            await page.wait_for_timeout(800)
            assert len(quotes) == 1, quotes
            hold.set()
            await wait_quotes(2)
            assert await page.locator('.quote-summary').count() == 0
            hold_second.set()
            await wait_amount(40)
            assert quotes[1]['items'][0]['quantity'] == 4, quotes
            assert max_active == 1, max_active
            assert await page.locator('.quote-summary').get_by_text('USD 30.00', exact=True).count() == 0
        elif case in ('clear', 'close'):
            await quantity(2)
            await asyncio.wait_for(hold_started.wait(), 5)
            if case == 'clear':
                await quantity(0)
            else:
                await page.get_by_role('button', name='关闭', exact=True).click()
                await page.locator('.el-message-box__btns .el-button--primary').click()
                await page.get_by_role('dialog').wait_for(state='hidden')
            hold.set()
            await page.wait_for_timeout(850)
            assert len(quotes) == 1, quotes
            assert await page.locator('.quote-summary').count() == 0
            if case == 'clear':
                assert await page.get_by_role('button', name='生成本批结算单', exact=True).is_disabled()
            else:
                await page.get_by_role('button', name='打开出库结算', exact=True).click()
                await page.wait_for_timeout(700)
                assert await page.locator('.quote-summary').count() == 0
        else:
            await quantity(2)
            await wait_quotes(1)
            await wait_amount(20)
            await page.get_by_role('button', name='生成本批结算单', exact=True).click()
            for _ in range(100):
                if submissions:
                    break
                await page.wait_for_timeout(50)
            assert len(submissions) == 1, submissions
            assert submissions[0]['quote_hash'] == '1' * 64 and submissions[0]['quote_facts'] == FACTS, submissions
            assert submissions[0]['items'] == [{'invoice_item_id': 7, 'quantity': 2}], submissions
            if case == 'stale':
                await page.get_by_text('QUOTE_STALE：商品单价已变化，请重新核算后提交', exact=True).first.wait_for()
                await wait_quotes(2)
                await wait_amount(20)
                assert await spin.input_value() == '2'
                assert len(submissions) == 1
            else:
                await page.get_by_text('原订单、数量、运费、报价和回款凭证已冻结。尚未查到不代表未提交，请勿另建结算。', exact=True).wait_for()
                await page.wait_for_timeout(900)
                assert len(submissions) == 1 and len(quotes) == 1
                slot = await page.evaluate("sessionStorage.getItem('ark_shipment_pending_v1:1')")
                frozen = json.loads(slot)
                assert frozen['body'] == submissions[0]
        assert not errors, errors
        assert not unexpected, unexpected
        print(json.dumps({'width': width, 'case': case, 'result': 'passed', 'quotes': len(quotes),
                          'submissions': len(submissions), 'maxQuoteInFlight': max_active}, ensure_ascii=False), flush=True)
    finally:
        hold.set()
        hold_second.set()
        await context.close()


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=CHROME, headless=True)
        try:
            for width in (1440, 390):
                for case in ('race', 'stale', 'timeout', 'clear', 'close'):
                    await run_case(browser, width, case)
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
