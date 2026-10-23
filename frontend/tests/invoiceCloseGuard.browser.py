"""Exercise the real invoice drawer using the in-memory API fixture."""
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

out = Path('tmp/invoice-close-guard')
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    for width in (1440, 390):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route(re.compile(r'^https?://[^/]+/api/'), lambda route: route.abort())
        page.goto('http://127.0.0.1:3047/tests/fixtures/invoice-contact-freight/index.html')
        page.wait_for_load_state('networkidle')
        page.evaluate('invoiceTest.editor.openEdit(7)')
        drawer = page.locator('.el-drawer:visible')
        close = drawer.get_by_role('button', name='Close this dialog')
        expect(close).to_be_visible()
        close.click()
        expect(drawer).to_have_count(0)
        page.evaluate('invoiceTest.editor.openEdit(7)')
        expect(close).to_be_visible()
        page.evaluate("invoiceTest.editor.form.remark = 'unsaved browser test'")
        close.click()
        expect(page.get_by_text('未保存提醒', exact=True)).to_be_visible()
        page.get_by_role('button', name='继续编辑', exact=True).click()
        expect(drawer).to_be_visible()
        # A real navigation emits Chromium's native beforeunload dialog.
        dialogs = []
        def cancel_unload(dialog):
            dialogs.append(dialog.type)
            dialog.dismiss()
        page.on('dialog', cancel_unload)
        try:
            page.reload(timeout=3000)
        except Exception as error:
            assert 'ERR_ABORTED' in str(error) or 'Timeout' in str(error), str(error)
        assert dialogs == ['beforeunload'], dialogs
        page.remove_listener('dialog', cancel_unload)
        page.wait_for_function("invoiceTest.editor.form.remark === 'unsaved browser test'")
        close.click()
        page.get_by_role('button', name='放弃修改并关闭', exact=True).click()
        expect(drawer).to_have_count(0)
        page.evaluate('invoiceTest.editor.openEdit(7)')
        expect(close).to_be_visible()
        page.evaluate("Object.assign(invoiceTest.editor.form, {invoice_no:'TEST-123', remark:'saved browser test'})")
        drawer.get_by_role('button', name='保存并同步', exact=True).click()
        page.get_by_role('button', name='确认提交', exact=True).click()
        notice = page.get_by_role('dialog', name='保存并同步完成', exact=True)
        expect(notice).to_be_visible()
        expect(notice.get_by_text('TEST-123订单号已保存并同步完成', exact=True)).to_be_visible()
        page.wait_for_timeout(3500)
        expect(notice).to_be_visible()
        notice.click()
        expect(notice).to_be_visible()
        box = notice.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width
        assert abs(box['y'] + box['height'] / 2 - 450) < 5, box
        page.screenshot(path=str(out / f'completion-{width}.png'))
        page.mouse.click(5, 5)
        expect(notice).to_be_hidden()
        assert not errors, errors
        page.close()
    browser.close()
print('PASS: clean/dirty drawer close, cancel/discard, native beforeunload, confirmed sync, persistent centered notice, outside dismissal; desktop and mobile')
