"""Real tree components with isolated client data; no business API requests."""
import sys
from playwright.sync_api import expect, sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3079"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/api/v1/**", lambda route: route.abort())
    page.goto(base + "/tests/fixtures/table-sorting/?route=/tree")
    commission = page.locator(".commission-fixture")
    tasks = page.locator(".task-fixture")
    expect(commission.locator(".el-table__row")).to_have_count(8)
    expect(tasks.locator(".el-table__row")).to_have_count(8)
    snapshot = page.get_by_test_id("source-snapshot").text_content()

    def dates():
        return commission.locator(".el-table__row td:first-child .cell")

    default_dates = ["2026-01（2 笔）", "2026-01-01", "2026-01-02", "2026-02（2 笔）", "2026-02-01", "2026-02-02", "未设置日期（1 笔）", ""]
    expect(dates()).to_have_text(default_dates)
    date_header = commission.locator("th", has_text="回款日期")
    date_header.click()
    expect(dates()).to_have_text(default_dates)
    date_header.click()
    expect(dates()).to_have_text(["2026-02（2 笔）", "2026-02-02", "2026-02-01", "2026-01（2 笔）", "2026-01-02", "2026-01-01", "未设置日期（1 笔）", ""])
    date_header.click()
    expect(dates()).to_have_text(default_dates)

    amount_header = commission.locator("th", has_text="提成金额（美元）")
    amount_header.click()
    expect(dates()).to_have_text(["未设置日期（1 笔）", "", "2026-01（2 笔）", "2026-01-01", "2026-01-02", "2026-02（2 笔）", "2026-02-02", "2026-02-01"])
    expect(commission.locator(".el-table__row td:nth-child(9) .cell")).to_have_text(["$3.00", "$3.00", "$12.00", "$2.00", "$10.00", "$120.00", "$20.00", "$100.00"])
    amount_header.click()
    expect(dates()).to_have_text(["2026-02（2 笔）", "2026-02-01", "2026-02-02", "2026-01（2 笔）", "2026-01-02", "2026-01-01", "未设置日期（1 笔）", ""])
    amount_header.click()
    expect(dates()).to_have_text(default_dates)

    title_header = tasks.locator("th", has_text="任务")
    title_header.click()
    expect(tasks.locator(".task-code")).to_have_text(["T-2", "T-22", "T-21", "T-10", "T-102", "T-101", "T-1002", "T-1001"])
    tasks.locator(".el-table__row", has=page.locator(".task-code", has_text="T-102")).click()
    expect(page.get_by_test_id("opened-task")).to_have_text("102")
    title_header.click()
    expect(tasks.locator(".task-code")).to_have_text(["T-10", "T-101", "T-1001", "T-1002", "T-102", "T-2", "T-21", "T-22"])
    title_header.click()
    expect(tasks.locator(".task-code")).to_have_text(["T-10", "T-101", "T-1002", "T-1001", "T-102", "T-2", "T-21", "T-22"])
    assert page.get_by_test_id("source-snapshot").text_content() == snapshot
    assert not errors, errors
    browser.close()

print("PASS: month and task trees sort every sibling level, dynamic role decimal totals, date/null order, clear and row identity; source unchanged and no JS errors")
