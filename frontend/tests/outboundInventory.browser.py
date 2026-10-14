"""Read-only real Vue list/drawer acceptance on desktop and mobile."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

output = Path('tmp/outbound-inventory')
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    results = []
    for width in (1440, 390):
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto('http://127.0.0.1:3038/tests/fixtures/outbound-inventory/index.html')
        page.wait_for_load_state('networkidle')
        buttons = page.get_by_role('button', name='库存详情', exact=True)
        expect(buttons).to_have_count(2)
        buttons.first.click()
        drawer = page.get_by_role('dialog')
        expect(drawer).to_be_visible()
        expect(drawer).to_contain_text('#P2/8/1g')
        expect(drawer).to_contain_text('库存不足')
        expect(drawer).to_contain_text('08:33:31')
        expect(drawer).to_contain_text('不可用数量')
        drawer.get_by_text('只看缺货 / 待核对', exact=True).click()
        expect(page.get_by_role('checkbox', name='只看缺货 / 待核对')).to_be_checked()
        expect(drawer.get_by_text('Super Double Drawn Genius Weft/24/#5AT60/20g', exact=True)).to_have_count(0)
        bounds = drawer.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1
        if width == 390:
            expect(drawer.locator('.inventory-mobile').first).to_be_visible()
            expect(drawer.locator('.inventory-mobile').first).to_contain_text('需要 100 · 可用 40 · 缺 60')
        page.screenshot(path=str(output / f'desktop-{width}.png'))
        page.keyboard.press('Escape')
        expect(drawer).not_to_be_visible()
        buttons.nth(1).click()
        expect(drawer).to_contain_text('可能已占用或扣减库存')
        page.evaluate('inventoryTest.fail = true')
        drawer.get_by_role('button', name='刷新库存详情').click()
        expect(drawer).to_contain_text('库存详情加载失败，请重试')
        page.evaluate('inventoryTest.fail = false')
        drawer.get_by_role('button', name='刷新库存详情').click()
        expect(drawer).to_contain_text('可能已占用或扣减库存')
        assert all(call['method'] == 'get' for call in page.evaluate('inventoryTest.calls'))
        assert not errors, errors
        results.append({'width': width, 'result': 'passed', 'writes': 0})
        page.close()
    browser.close()
print(json.dumps(results))
