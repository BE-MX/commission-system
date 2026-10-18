"""Real invoice create/edit UI with in-memory APIs; never uses the backend."""
import argparse
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:3043')
parser.add_argument('--output', default='tmp/invoice-contact-freight')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    for width in (1440, 1280, 390):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        page.set_default_timeout(10000)
        errors = []
        page.on('pageerror', lambda error: errors.append(error.stack))
        page.route(re.compile(r'^https?://[^/]+/api/'), lambda route: route.abort())
        page.goto(args.base_url + '/tests/fixtures/invoice-contact-freight/index.html')
        page.get_by_role('button', name='新建库存单', exact=True).click()
        drawer = page.locator('.el-drawer:visible')
        currency = drawer.locator('.el-form-item').filter(has=page.locator('label', has_text=re.compile(r'^币种$')))
        expect(currency).to_have_count(0)
        number = drawer.locator('.invoice-no-gold input')
        expect(number).to_be_visible()
        number_style = number.evaluate('(el) => ({color: getComputedStyle(el).color, size: getComputedStyle(el).fontSize, weight: getComputedStyle(el).fontWeight})')
        assert number_style['size'] == '16px', number_style
        assert number_style['weight'] == '700', number_style
        assert number_style['color'] == 'rgb(184, 134, 11)', number_style
        wrapper = drawer.locator('.invoice-no-gold .el-input__wrapper')
        assert wrapper.evaluate('(el) => getComputedStyle(el).borderTopWidth') == '2px'
        heading = drawer.locator('.contact-details-heading')
        for label in ('订单号/发票号', '下单日期', '小满标记'):
            field = drawer.locator('.el-form-item').filter(has=page.locator('.el-form-item__label', has_text=re.compile('^' + re.escape(label) + '$')))
            field.scroll_into_view_if_needed()
            assert field.bounding_box()['y'] < heading.bounding_box()['y']
        number.scroll_into_view_if_needed()
        page.screenshot(path=str(out / f'order-header-{width}.png'))
        contact_input = drawer.locator('input[placeholder="To"]')
        expect(contact_input).to_be_visible()
        customer = drawer.locator('.customer-filter-select')
        customer.click()
        page.get_by_role('option', name='complete · 客户', exact=True).click()
        expand = drawer.get_by_role('button', name='展开联系与收货信息', exact=True)
        expect(expand).to_be_visible()
        expect(contact_input).to_be_hidden()
        expand.focus()
        page.keyboard.press('Enter')
        expect(contact_input).to_have_value('Alice')
        phone = drawer.locator('input[placeholder="TEL/Fax"]')
        phone.fill('')
        expect(drawer.get_by_text('联系与收货信息（待补全）', exact=True)).to_be_visible()
        phone.fill('999')
        expect(phone).to_be_visible()
        address = drawer.locator('textarea[placeholder="Delivery address"]')
        short_height = address.evaluate('(el) => el.offsetHeight')
        address.fill('\n'.join(['Long delivery address'] * 8))
        address.press('Tab')
        page.wait_for_function('(args) => args.el.offsetHeight > args.height', arg={'el': address.element_handle(), 'height': short_height})
        drawer.get_by_role('button', name='收起联系与收货信息', exact=True).click()
        expand.click()
        expect(address).to_be_visible()
        assert address.evaluate('(el) => el.offsetHeight') > short_height
        page.screenshot(path=str(out / f'contact-{width}.png'))
        drawer.get_by_role('button', name='收起联系与收货信息', exact=True).click()
        customer.click()
        page.get_by_role('option', name='incomplete · 客户', exact=True).click()
        expect(phone).to_be_visible()
        expect(phone).to_have_value('')
        phone.fill('999')
        drawer.get_by_role('button', name='收起联系与收货信息', exact=True).click()
        main = drawer.locator('.pane-main')
        freight = main.locator('.el-form-item').filter(has=page.locator('label', has_text=re.compile(r'^运费$'))).locator('input')
        readout = drawer.locator('.settlement-card .el-form-item').filter(has=page.locator('label', has_text=re.compile(r'^运费$'))).locator('input')
        main.locator('.el-radio').filter(has_text='FEDEX').click()
        freight.fill('123.45')
        freight.press('Tab')
        expect(readout).to_have_value('123.45')
        expect(readout).to_have_attribute('readonly', '')
        freight.fill('0')
        freight.press('Tab')
        expect(readout).to_have_value('0.00')
        freight.fill('123.45')
        freight.press('Tab')
        def fee_input(label, scope):
            return scope.locator('.el-form-item').filter(has=page.locator('label', has_text=re.compile('^' + label + '$'))).locator('input')
        quantity = fee_input('包装数量', main)
        packaging = fee_input('包装费用', main)
        quantity_readout = fee_input('包装数量', drawer.locator('.settlement-card'))
        packaging_readout = fee_input('包装费用', drawer.locator('.settlement-card'))
        for read_only in (quantity_readout, packaging_readout):
            expect(read_only).to_have_attribute('readonly', '')
            assert read_only.locator('..').evaluate('(el) => getComputedStyle(el).backgroundColor') == readout.locator('..').evaluate('(el) => getComputedStyle(el).backgroundColor')
        quantity.fill('4')
        quantity.press('Tab')
        packaging.fill('12.34')
        packaging.press('Tab')
        expect(quantity_readout).to_have_value('4')
        expect(packaging_readout).to_have_value('12.34')
        page.evaluate('invoiceTest.editor.form.items = []')
        page.wait_for_function('invoiceTest.editor.formTotal.value === 135.79')
        quantity.fill('8')
        quantity.press('Tab')
        expect(quantity_readout).to_have_value('8')
        # Quantity is only a record; it must never multiply the packaging fee.
        page.wait_for_function('invoiceTest.editor.formTotal.value === 135.79')
        for control, zero, read_only in ((quantity, '0', quantity_readout), (packaging, '0.00', packaging_readout)):
            control.fill('0')
            control.press('Tab')
            expect(read_only).to_have_value(zero)
            control.fill('-1')
            control.press('Tab')
            expect(read_only).to_have_value(zero)
        quantity.fill('4')
        quantity.press('Tab')
        packaging.fill('12.345')
        packaging.press('Tab')
        expect(packaging_readout).to_have_value('12.35')
        packaging.fill('12.34')
        packaging.press('Tab')
        fees = main.locator('.logistics-fees-row')
        fees.scroll_into_view_if_needed()
        positions = [control.bounding_box() for control in (freight, quantity, packaging)]
        if width > 900:
            assert len({round(pos['y']) for pos in positions}) == 1, positions
            assert positions[0]['x'] < positions[1]['x'] < positions[2]['x'], positions
        else:
            assert positions[0]['y'] < positions[1]['y'] < positions[2]['y'], positions
        assert all(pos['x'] >= 0 and pos['x'] + pos['width'] <= width for pos in positions)
        page.screenshot(path=str(out / f'logistics-fees-{width}.png'))
        drawer.get_by_role('button', name='保存', exact=True).click()
        page.wait_for_function('invoiceTest.saved.length === 1')
        saved = page.evaluate('invoiceTest.saved[0]')
        assert saved['shipping_fee'] == 123.45
        assert saved['packaging_quantity'] == 4
        assert saved['internal_accessory'] == 12.34
        assert saved['currency'] == 'USD'
        assert saved['contact_phone'] == '999'
        assert saved['contact_name'] == 'Alice'
        page.evaluate('invoiceTest.editor.openEdit(7)')
        expect(expand).to_be_visible()
        expect(readout).to_have_value('123.45')
        expect(freight).to_have_value('123.45')
        expect(currency).to_be_visible()
        expect(quantity).to_have_value('4')
        expect(packaging).to_have_value('12.34')
        expect(quantity_readout).to_have_value('4')
        expect(packaging_readout).to_have_value('12.34')
        readout.scroll_into_view_if_needed()
        if width == 390:
            side = drawer.locator('.pane-side').bounding_box()
            left = main.bounding_box()
            assert side['y'] >= left['y'] + left['height'] - 1
            assert side['x'] + side['width'] <= width
        page.screenshot(path=str(out / f'edit-{width}.png'), full_page=True)
        page.evaluate("invoiceTest.editor.form.order_type = 'presale'")
        expect(freight).to_be_disabled()
        expect(readout).to_have_value('0.00')
        expect(quantity).to_be_enabled()
        expect(packaging).to_be_enabled()
        expect(packaging_readout).to_have_value('12.34')
        assert not errors, errors
        page.close()
    browser.close()
print('PASS: hidden new currency, gold header, order before contacts, packaging entry/readout/zero/clamp/precision/total/save, 3 widths;  create/edit contact collapse, keyboard, missing field, freight readout, zero, save/readback, presale; desktop and mobile')
