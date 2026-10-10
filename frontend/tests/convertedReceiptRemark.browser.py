"""Run against Vite on port 3187; all business API requests are intercepted."""
import copy
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def scenario(browser, legacy):
    page = browser.new_page(viewport={"width": 720, "height": 1100})
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    row = dict(id=11, invoice_id=1, source="auto", status="active", sync_status="synced",
               version=1, remark="old receipt remark", amount="880.91", currency="USD",
               collection_date="2026-10-10", payment_type="Other", purpose="ordinary",
               bank_charge="0", attachments=[dict(id=41, filename="proof.png")])
    conflict = False

    def api(route):
        nonlocal conflict
        request = route.request
        path = request.url.split("/api/")[1]
        if path == "receipts/11/remark":
            body = request.post_data_json
            assert request.method == "PATCH" and set(body) == {"remark", "version"}
            assert body["version"] == row["version"]
            writes.append(body)
            if conflict:
                route.fulfill(status=409, json={"detail": "请刷新后重试"})
                return
            row.update(remark=body["remark"], version=row["version"] + 1)
            data = copy.deepcopy(row)
        elif path == "receipts/11":
            data = copy.deepcopy(row)
        elif path == "receipts/invoice-summary/1":
            data = {"initial_receipt": copy.deepcopy(row), "balance": {
                "effective_amount": 880.91, "registered_amount": 880.91,
                "pending_amount": 0, "remaining_amount": 0}}
        elif path == "receipts/types":
            data = ["Other"]
        elif path == "receipts/attachments/41":
            route.fulfill(status=200, content_type="image/svg+xml",
                          body='<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            return
        else:
            raise AssertionError(f"Unexpected API: {request.method} {path}")
        route.fulfill(status=200, json={"code": 200, "data": data})

    page.route("http://127.0.0.1:3187/api/**", api)
    page.goto("http://127.0.0.1:3187/tests/convertedReceiptRemarkHarness.html" + ("?legacy" if legacy else ""))
    page.wait_for_load_state("networkidle")
    edit = page.get_by_role("button", name="编辑备注", exact=True)
    expect(edit).to_be_enabled()
    page.evaluate("orderSaving(true)")
    expect(edit).to_be_disabled()
    page.evaluate("orderSaving(false)")
    expect(edit).to_be_enabled()
    assert page.locator('textarea:disabled').count() == 0
    assert page.locator('input:disabled').count() >= 2
    edit.click()
    expect(page.get_by_role("button", name="刷新资金汇总")).to_be_disabled()
    assert page.evaluate("form.receipt_remark_editing") is True
    assert page.get_by_role("button", name="上传回款截图").count() == 0
    page.get_by_role("textbox", name="编辑备注").fill("updated from order editor")
    page.get_by_role("button", name="保存备注", exact=True).click()
    expect(edit).to_be_enabled()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("form.receipt_draft.remark") == "updated from order editor"
    assert page.evaluate("form.receipt_draft.receipt_version") == 2
    assert page.evaluate("form.remark") == "unsaved order header"
    assert not page.evaluate("form.receipt_remark_editing || form.receipt_remark_saving")
    expect(page.get_by_role("button", name="刷新资金汇总")).to_be_enabled()
    edit.click()
    page.get_by_role("textbox", name="编辑备注").fill("")
    page.get_by_role("button", name="保存备注", exact=True).click()
    expect(page.get_by_text("暂无备注", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("form.receipt_draft.remark") == ""
    assert page.evaluate("form.receipt_draft.receipt_version") == 3
    conflict = True
    edit.click()
    page.get_by_role("textbox", name="编辑备注").fill("conflict text retained")
    page.get_by_role("button", name="保存备注", exact=True).click()
    expect(page.locator('.document-remark__error')).to_contain_text("请刷新后重试")
    expect(page.get_by_role("textbox", name="编辑备注")).to_have_value("conflict text retained")
    page.get_by_role("button", name="取消", exact=True).click()
    assert page.evaluate("form.receipt_draft.remark") == ""
    assert len(writes) == 3
    page.set_viewport_size({"width": 390, "height": 844})
    expect(edit).to_be_enabled()
    evidence = Path(__file__).resolve().parents[2] / "tmp" / "converted-receipt-remark"
    evidence.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence / ("legacy.png" if legacy else "modern.png")), full_page=True)
    # Check the changed remark area; the existing upload drop zone has independent overflow.
    assert page.locator('.document-remark').evaluate("e => e.getBoundingClientRect().right <= innerWidth")
    page.evaluate("revoke()")
    expect(edit).to_have_count(0)
    assert errors == [], errors
    page.close()
    return {"legacy": legacy, "writes": len(writes), "page_errors": errors, "result": "passed"}


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, channel="chrome")
    try:
        print(json.dumps([scenario(browser, False), scenario(browser, True)]))
    finally:
        browser.close()
