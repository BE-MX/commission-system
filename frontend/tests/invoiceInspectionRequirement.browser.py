"""Real invoice fields with in-memory APIs and independent A4 print marks."""
import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:3057")
parser.add_argument("--output", default="tmp/invoice-inspection")
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    for width in (1440, 390):
        page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(re.compile(r"^https?://[^/]+/api/"), lambda route: route.abort())
        page.goto(args.base_url + "/tests/fixtures/invoice-contact-freight/index.html")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="新建库存单", exact=True).click()
        drawer = page.locator(".el-drawer:visible")
        group = drawer.get_by_role("radiogroup", name="检验要求", exact=True)
        single = group.get_by_role("radio", name="单张检验照片", exact=True)
        detail = group.get_by_role("radio", name="明细检验照片", exact=True)
        flag = drawer.locator(".okki-flag").filter(has_text="新成交").locator(".el-switch")
        expect(detail).to_be_checked()
        flag.click()
        expect(single).to_be_checked()
        group.locator(".el-radio").filter(has_text="明细检验照片").click()
        flag.click()
        flag.click()
        expect(detail).to_be_checked()
        flag.click()
        group.locator(".el-radio").filter(has_text="单张检验照片").click()
        expect(single).to_be_checked()
        # Keyboard operation and mutually exclusive required selection.
        single.focus()
        single.press("ArrowRight")
        expect(detail).to_be_checked()
        detail.press("ArrowLeft")
        expect(single).to_be_checked()
        customer = drawer.locator(".customer-filter-select")
        customer.click()
        page.get_by_role("option", name="complete · 客户", exact=True).click()
        page.evaluate("Object.assign(invoiceTest.editor.form, {express_channel:'FEDEX', items:[]})")
        expect(single).to_be_checked()
        group.scroll_into_view_if_needed()
        for label in group.locator(".el-radio").all():
            box = label.bounding_box()
            assert 0 <= box["x"] and box["x"] + box["width"] <= width, box
        marks_box = drawer.locator(".okki-flags-row").bounding_box()
        assert group.bounding_box()["y"] > marks_box["y"]
        page.screenshot(path=str(out / f"form-{width}.png"), full_page=True)
        drawer.get_by_role("button", name="保存", exact=True).click()
        page.wait_for_function("invoiceTest.saved.length === 1")
        assert page.evaluate("invoiceTest.saved[0].inspection_requirement") == "single"
        page.evaluate("invoiceTest.editor.openEdit(7)")
        expect(single).to_be_checked()
        group.locator(".el-radio").filter(has_text="明细检验照片").click()
        drawer.get_by_role("button", name="保存", exact=True).click()
        page.wait_for_function("invoiceTest.saved.length === 2")
        assert page.evaluate("invoiceTest.saved[1].inspection_requirement") == "detail"
        page.evaluate("invoiceTest.editor.openEdit(7)")
        expect(detail).to_be_checked()
        htmls = page.evaluate("""async () => {
          const {buildOutboundDoc} = await import('/src/views/shipping/print/printDocs.js')
          return [false,true].flatMap(is_new_deal => ['single','detail'].map(inspection_requirement => ({
            is_new_deal, inspection_requirement,
            html:buildOutboundDoc({record:{outbound_no:'TEST-261057', customer_name:'Customer',
              is_new_deal, inspection_requirement, remark:'测试发货备注', outbound_date:'2026-10-27'},
              items:[{product_name:'Super Double Drawn Genius Weft/18/#P8/24/20g',spec:'B1天才发帘',qty:6}]})
          })))
        }""")
        print_page = browser.new_page(viewport={"width": 960, "height": 1100})
        for data in htmls:
            print_page.set_content(data["html"])
            expect(print_page.get_by_text("新签", exact=True)).to_have_count(int(data["is_new_deal"]))
            expect(print_page.get_by_text("拍摄明细照片", exact=True)).to_have_count(int(data["inspection_requirement"] == "detail"))
            if data["is_new_deal"] or data["inspection_requirement"] == "detail":
                mark = print_page.locator(".order-marks")
                style = mark.evaluate("(el) => ({size:getComputedStyle(el).fontSize,weight:getComputedStyle(el).fontWeight})")
                assert style == {"size": "24px", "weight": "800"}, style
                header = print_page.locator(".header").bounding_box()
                box = mark.bounding_box()
                assert box["x"] > header["x"] + header["width"] / 2
                assert box["x"] + box["width"] <= header["x"] + header["width"] + 1
            if data["is_new_deal"] and data["inspection_requirement"] == "detail" and width == 1440:
                print_page.screenshot(path=str(out / "outbound-both-marks.png"), full_page=True)
                print_page.pdf(path=str(out / "outbound-both-marks.pdf"), prefer_css_page_size=True)
        print_page.close()
        assert not errors, errors
        page.close()
    browser.close()
print("PASS: defaults, manual overrides, keyboard radios, save/reopen both choices, 1440/390px, four independent print combinations; no page errors")
