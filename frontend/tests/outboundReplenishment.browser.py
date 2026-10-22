"""Real components: immediate recheck, permissions, loading, failure and single free-stock column."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:3039/tests/fixtures/outbound-replenishment/index.html')
parser.add_argument('--browser', help='Optional installed Chromium executable')
parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'tmp/outbound-replenishment')
args = parser.parse_args()
output = args.output
output.mkdir(parents=True, exist_ok=True)
url = args.url
results = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=args.browser, headless=True)
    for width in (1440, 390):
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url); page.wait_for_load_state('networkidle')
        button = page.get_by_role('button', name='补货同步', exact=True)
        expect(button).to_have_count(1)
        page.evaluate('replenishmentTest.delay = 500')
        button.click(); expect(button).to_be_disabled()
        expect(page.get_by_text('已同步目标仓库实时库存，仍有明细库存不足', exact=True)).to_be_visible()
        assert sum(call['method'] == 'post' for call in page.evaluate('replenishmentTest.calls')) == 1
        page.evaluate('replenishmentTest.fail = true')
        button.click()
        expect(page.get_by_text('补货同步结果暂未确认，请刷新核对原任务；不要重复提交', exact=True)).to_be_visible()
        page.evaluate('replenishmentTest.fail = false; replenishmentTest.outcome = "done"')
        button.click()
        expect(page.get_by_text('小满出库单已生成并核验', exact=True)).to_be_visible()
        expect(button).to_have_count(0)
        page.screenshot(path=str(output / f'outbound-{width}.png'), full_page=True)
        page.goto(url+'?readOnly=1'); page.wait_for_load_state('networkidle')
        expect(page.get_by_role('button', name='补货同步', exact=True)).to_have_count(0)
        page.goto(url+'?view=invoice'); page.wait_for_load_state('networkidle')
        expect(page.get_by_role('columnheader', name='自由可用', exact=True)).to_have_count(1)
        expect(page.get_by_role('columnheader', name='可用库存 / 未发货', exact=True)).to_have_count(0)
        expect(page.locator('.stock-shortage-row')).to_have_count(0)
        expect(page.locator('.stock-count').first).to_have_text('0')
        page.evaluate('replenishmentTest.capacity = 6')
        page.get_by_role('button', name='刷新库存与出库进度', exact=True).click()
        expect(page.locator('.stock-shortage-row')).to_have_count(1)
        page.screenshot(path=str(output / f'invoice-{width}.png'), full_page=True)
        assert not errors, errors
        results.append({'width': width, 'passed': True, 'native_writes': 0})
        page.close()
    browser.close()
print(json.dumps(results))
