"""Real invoice UI: persistent groups, entry targets, local-only saves and outbound states."""
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = 'http://127.0.0.1:3051/tests/fixtures/invoice-item-groups/index.html'
OUT = Path('tmp/invoice-item-groups')
OUT.mkdir(parents=True, exist_ok=True)


def expect_groups(drawer, expected):
    normalize = lambda values: [re.sub(r'\s+', '', value) for value in values]
    expect(drawer.locator('.item-group-tab')).to_have_count(len(expected))
    actual = drawer.locator('.item-group-tab').all_inner_texts()
    assert normalize(actual) == normalize(expected), (actual, expected)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    for width in (1440, 390):
        page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
        page.set_default_timeout(12000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(URL)
        page.wait_for_load_state('networkidle')
        page.evaluate('invoiceGroupTest.editor.openEdit(7)')
        drawer = page.locator('.el-drawer:visible')
        expect_groups(drawer, ['全部明细 2', 'A首批 2'])
        expect(drawer.locator('.outbound-linked-row')).to_have_count(2)
        expect(drawer.get_by_text('已发货 5/5', exact=True)).to_be_visible()
        expect(drawer.get_by_text('已发 1/3', exact=True)).to_be_visible()

        drawer.get_by_role('button', name='新建分组', exact=True).click()
        prompt = page.locator('.el-message-box:visible')
        prompt.locator('input').fill('B补单')
        prompt.get_by_role('button', name='新建分组', exact=True).click()
        expect_groups(drawer, ['全部明细 2', 'A首批 2', 'B补单 0'])

        drawer.get_by_role('button', name='从 Excel 粘贴', exact=True).click()
        dialog = page.locator('.invoice-paste-dialog:visible')
        expect(dialog.locator('.context-bar')).to_contain_text('B补单')
        dialog.locator('textarea').fill('Product\tLength\tColor\tWeight\tQuantity\tUnit Price\nImported B1\t18\t#1B\t100g\t2\t30')
        dialog.get_by_role('button', name='校验数据', exact=True).click()
        dialog.get_by_role('button', name='加入当前分组', exact=True).click()
        expect_groups(drawer, ['全部明细 3', 'A首批 2', 'B补单 1'])

        drawer.get_by_role('button', name='明细操作', exact=True).click()
        page.get_by_role('menuitem', name='复制一行', exact=True).click()
        expect_groups(drawer, ['全部明细 4', 'A首批 2', 'B补单 2'])
        drawer.get_by_role('button', name='添加空行', exact=True).click()
        expect_groups(drawer, ['全部明细 5', 'A首批 2', 'B补单 3'])
        rows = drawer.locator('.line-table .el-table__body tr')
        rows.last.get_by_role('button', name='删除产品', exact=True).click()
        expect_groups(drawer, ['全部明细 4', 'A首批 2', 'B补单 2'])

        drawer.get_by_role('button', name='保存', exact=True).click()
        page.wait_for_function('invoiceGroupTest.saved.some(call => call.method === "put")')
        page.evaluate('invoiceGroupTest.editor.closeEditor()')
        page.evaluate('invoiceGroupTest.editor.openEdit(7)')
        drawer = page.locator('.el-drawer:visible')
        expect_groups(drawer, ['全部明细 4', 'A首批 2', 'B补单 2'])
        expect(drawer.locator('.line-table .el-table__body tr')).to_have_count(2)

        drawer.get_by_role('button', name='重命名', exact=True).click()
        prompt = page.locator('.el-message-box:visible')
        prompt.locator('input').fill('B改名')
        prompt.get_by_role('button', name='保存名称', exact=True).click()
        expect_groups(drawer, ['全部明细 4', 'A首批 2', 'B改名 2'])

        selected_rows = drawer.locator('.line-table .el-table__body tr')
        for index in range(selected_rows.count()):
            selected_rows.nth(index).get_by_role('checkbox').evaluate('(input) => input.click()')
        expect(drawer.locator('.selection-hint')).to_have_text('已选 2 行')
        drawer.locator('.item-group-move').click()
        page.get_by_role('option', name='A首批', exact=True).click()
        expect_groups(drawer, ['全部明细 4', 'A首批 4', 'B改名 0'])
        drawer.get_by_role('button', name='保存', exact=True).click()
        page.wait_for_function('invoiceGroupTest.saved.at(-1).method === "patch"')
        assert page.evaluate('invoiceGroupTest.saved.at(-1).payload.expected_version') == 'a' * 64
        assert page.evaluate('invoiceGroupTest.saved.at(-1).payload.items.every(row => row.group_key === "a")')

        drawer.get_by_role('button', name='删除空组', exact=True).click()
        page.get_by_role('button', name='确定删除', exact=True).click()
        drawer.get_by_role('button', name='保存', exact=True).click()
        page.wait_for_function('invoiceGroupTest.saved.at(-1).method === "patch"')
        expect_groups(drawer, ['全部明细 4', 'A首批 4'])
        assert page.evaluate('invoiceGroupTest.saved.filter(call => call.method === "patch").length') == 2
        assert page.evaluate('invoiceGroupTest.calls.filter(call => call.method === "post" && call.url.endsWith("/linked-sync")).length') == 0
        assert page.evaluate('invoiceGroupTest.editor.form.items.length') == 4

        page.evaluate('invoiceGroupTest.outboundMode = "unknown"')
        drawer.get_by_role('button', name='刷新库存与出库进度', exact=True).click()
        expect(drawer.locator('.outbound-linked-row')).to_have_count(0)
        expect(drawer.get_by_text('状态待核对', exact=True)).to_have_count(4)
        expect(drawer.locator('.item-group-navigation')).to_be_visible()
        expect(drawer.get_by_role('button', name='新建分组', exact=True)).to_be_visible()
        page.screenshot(path=str(OUT / f'groups-{width}.png'), full_page=True)

        page.evaluate('invoiceGroupTest.editor.closeEditor()')
        page.evaluate('invoiceGroupTest.editor.openLegacyCreate("stock")')
        legacy = page.locator('.el-drawer:visible')
        expect(legacy.locator('.item-group-tab')).to_have_count(2)
        expect(legacy.get_by_role('button', name='新建分组', exact=True)).to_be_visible()
        assert not errors, errors
        page.close()
    browser.close()
print('PASS: group create/Excel/copy/blank save/reopen/rename/move/delete, local PATCH, outbound grey/unknown, legacy and mobile')
