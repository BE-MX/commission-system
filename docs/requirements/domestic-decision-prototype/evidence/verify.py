"""Browser verification for the standalone demo. Uses only synthetic local data."""
import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8768'

async def main():
    results = []
    async with async_playwright() as p:
        installed = sorted((Path(os.environ['LOCALAPPDATA']) / 'ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
        browser = await p.chromium.launch(executable_path=str(installed[-1]), headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(URL, wait_until='networkidle')
        await page.screenshot(path=str(OUT / 'overview-desktop.png'), full_page=True)
        assert await page.title() == '内贸经营决策台 · 莱莎方舟'
        math = await page.evaluate('''() => {
          const d=DEMO, errors=[];
          d.orders.forEach(o=>{if(o.amount!==o.lines.reduce((s,l)=>s+l.price*l.qty,0))errors.push('order '+o.id)});
          d.customers.forEach(c=>{let b=c.initial;d.ledger.filter(l=>l.customer===c.id).forEach(l=>{if(l.before!==b||l.after!==b+l.amount)errors.push('ledger '+l.id);b=l.after;});if(b!==c.balance)errors.push('balance '+c.id);if(c.mode==='prepay'&&b<0)errors.push('negative prepay')});
          return {errors,orders:d.orders.length,customers:d.customers.length,ledger:d.ledger.length};
        }''')
        assert not math['errors'], math
        results.append({'case':'order and ledger reconciliation','result':'pass','counts':math})
        for tab in ['products','finance','customers','people','trends','actions','overview']:
            await page.locator(f'.tabs [data-page="{tab}"]').click()
            assert await page.locator('#page-content').inner_text()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), tab
            if tab in ['products','finance','customers','people','actions']:
                await page.screenshot(path=str(OUT / f'{tab}-desktop.png'), full_page=True)
        results.append({'case':'all seven pages and desktop overflow','result':'pass'})
        baseline = await page.evaluate('Prototype.summarize().qty')
        await page.select_option('#product-type','cap')
        await page.locator('[data-action="filters"]').click()
        await page.locator('#filter-form select[name="color"]').select_option('自然黑')
        await page.locator('#filter-form select[name="size"]').select_option('M')
        await page.locator('button[form="filter-form"]').click()
        narrowed = await page.evaluate('Prototype.summarize().qty')
        assert 0 < narrowed < baseline
        assert await page.evaluate('Prototype.getLines().every(p=>p.type==="cap"&&p.color==="自然黑"&&p.size==="M")')
        await page.locator('.tabs [data-page="products"]').click()
        await page.locator('[data-action="heat"][data-craft="递顶"][data-length="35厘米"]').click()
        assert await page.locator('#detail').is_visible()
        assert '订单证据' in await page.locator('#dialog-title').inner_text()
        await page.keyboard.press('Escape')
        assert not await page.locator('#detail').is_visible()
        results.append({'case':'same-line multi-attribute filters and heatmap evidence','result':'pass'})
        await page.locator('[data-action="reset"]').first.click()
        await page.locator('.tabs [data-page="customers"]').click()
        await page.locator('#customer-search').fill('杭州')
        assert await page.locator('#page-content tbody tr').count() == 2
        await page.locator('button.customer-name').first.click()
        await page.screenshot(path=str(OUT / 'customer-profile-desktop.png'), full_page=True)
        await page.locator('#detail [data-action="new-task"]').click()
        await page.locator('#task-form input[name="title"]').fill('原型验证：核对门店采购计划')
        await page.locator('button[form="task-form"]').click()
        assert '原型验证：核对门店采购计划' in await page.locator('#page-content').inner_text()
        await page.reload(wait_until='networkidle')
        await page.locator('.tabs [data-page="actions"]').click()
        await page.locator('[data-action="finish"]').first.click()
        await page.locator('#finish-form select').select_option(label='已联系，需求待确认')
        await page.locator('#finish-form textarea').fill('演示回访记录，无外部消息发送。')
        await page.locator('button[form="finish-form"]').click()
        assert '已联系，需求待确认' in await page.locator('#page-content').inner_text()
        results.append({'case':'customer search, profile, task persistence and completion','result':'pass'})
        await page.locator('[data-action="save-view"]').click()
        await page.locator('#view-form input').fill('验证视图')
        await page.locator('button[form="view-form"]').click()
        await page.locator('[data-action="views"]').click()
        assert '验证视图' in await page.locator('#detail').inner_text()
        await page.locator('#detail [data-action="load-view"]').first.click()
        await page.locator('.heading-actions [data-action="brief"]').click()
        assert '未调用模型' in await page.locator('#detail').inner_text()
        await page.screenshot(path=str(OUT / 'brief-desktop.png'), full_page=True)
        await page.keyboard.press('Escape')
        async with page.expect_download() as event:
            await page.locator('.heading-actions [data-action="export"]').click()
        download = await event.value
        assert download.suggested_filename.endswith('.csv')
        results.append({'case':'saved views, simulated AI brief and CSV export','result':'pass'})
        await page.locator('[data-action="reset"]').first.click()
        await page.locator('.tabs [data-page="products"]').click()
        await page.select_option('#product-type','piece')
        await page.locator('[data-action="filters"]').click()
        await page.locator('#filter-form select[name="density"]').select_option('90%')
        await page.locator('button[form="filter-form"]').click()
        assert await page.evaluate('Prototype.getLines().length') == 0
        assert await page.locator('.empty').count() > 0
        results.append({'case':'incompatible attribute empty state','result':'pass'})
        await page.locator('[data-action="reset"]').first.click()
        await page.locator('.tabs [data-page="finance"]').click()
        finance_row = page.locator('#page-content tr').filter(has_text='悦己美发 · 苏州店')
        unfiltered_amount = await finance_row.locator('td.amount').first.inner_text()
        await page.locator('[data-action="filters"]').click()
        await page.locator('#filter-form select[name="color"]').select_option('自然黑')
        await page.locator('button[form="filter-form"]').click()
        assert await finance_row.locator('td.amount').first.inner_text() == unfiltered_amount
        await page.locator('.tabs [data-page="products"]').click()
        matching_qty = await page.evaluate('Prototype.summarize().qty')
        await page.locator('#page-content [data-action="orders"]').first.click()
        assert f'匹配明细 {matching_qty:,} 件' in await page.locator('#detail .notice').inner_text()
        assert '相关整单' in await page.locator('#detail .notice').inner_text()
        await page.keyboard.press('Tab')
        assert await page.evaluate('document.querySelector("#detail").contains(document.activeElement)')
        await page.keyboard.press('Escape')
        await page.locator('[data-action="reset"]').first.click()
        await page.locator('.tabs [data-page="overview"]').click()
        await page.select_option('#period','180')
        assert await page.locator('.compare-line').count() == 0
        assert '上期无历史覆盖' in await page.locator('.kpis').inner_text()
        assert '新增' not in await page.locator('.kpis').inner_text()
        await page.locator('.heading-actions [data-action="brief"]').click()
        assert '无历史覆盖' in await page.locator('#detail').inner_text()
        await page.keyboard.press('Escape')
        results.append({'case':'review regressions: financial scope, matched evidence, missing history and modal focus','result':'pass'})
        mobile = await context.new_page()
        await mobile.set_viewport_size({'width':390,'height':844})
        mobile.on('pageerror', lambda error: errors.append(str(error)))
        await mobile.emulate_media(reduced_motion='reduce')
        await mobile.goto(URL, wait_until='networkidle')
        assert await mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await mobile.screenshot(path=str(OUT / 'overview-mobile.png'), full_page=True)
        await mobile.locator('.mobile-menu').click()
        await mobile.locator('.sidebar [data-page="customers"]').click()
        assert await mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await mobile.locator('button.customer-name').first.click()
        assert await mobile.locator('#detail').is_visible()
        assert await mobile.evaluate('document.querySelector("#detail").getBoundingClientRect().right <= innerWidth')
        await mobile.screenshot(path=str(OUT / 'customer-profile-mobile.png'), full_page=True)
        results.append({'case':'390px mobile layout, navigation and drawer with reduced motion','result':'pass'})
        offline = await browser.new_context(offline=True)
        local = await offline.new_page()
        await local.goto(ROOT.joinpath('index.html').as_uri())
        assert await local.locator('.kpi').count()==6
        results.append({'case':'offline file opening without dependencies','result':'pass'})
        assert not errors, errors
        results.append({'case':'browser runtime errors','result':'pass','errors':errors})
        await browser.close()
    OUT.joinpath('verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True,indent=2))

if __name__=='__main__':
    asyncio.run(main())
