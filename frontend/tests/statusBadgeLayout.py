"""Browser layout regression. Requires a running frontend Vite server and Playwright."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:3198/tests/fixtures/status-badge/")
parser.add_argument("--output", default="../tmp/status-badge")
parser.add_argument("--record-only", action="store_true")
parser.add_argument("--channel", default="chrome", help="Installed browser channel; no download required.")
args = parser.parse_args()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, channel=args.channel)
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until="networkidle")
        page.locator(".status-badge").first.wait_for()
        if not args.record_only:
            label = page.locator('.slot-status .status-badge__label')
            expect(label).to_have_attribute('title', 'First')
            page.get_by_role('button', name='更新槽内容').click()
            expect(label).to_have_text('Second')
            expect(label).to_have_attribute('title', 'Second')
            expect(page.locator('.zero-status .status-badge__label')).to_have_attribute('title', '0')
            expect(page.locator('.explicit-title-status .status-badge__label')).to_have_attribute('title', '指定说明')
            expect(page.locator('.empty-title-status .status-badge__label')).to_have_attribute('title', '')
            group = page.locator('td.multiple-status .status-badge')
            positions = group.evaluate_all('badges => badges.map(b => b.getBoundingClientRect().top)')
            assert positions[1] > positions[0], positions
            action_style = page.locator('td.table-action-column > .cell').evaluate("cell => ({display:getComputedStyle(cell).display,wrap:getComputedStyle(cell).flexWrap})")
            assert action_style == {'display': 'flex', 'wrap': 'wrap'}, action_style
        metrics = page.locator(".status-badge").evaluate_all("""badges => badges.map(badge => {
            const content = badge.querySelector('.status-badge__label') || badge.querySelector('.el-tag__content');
            const rect = badge.getBoundingClientRect();
            const range = document.createRange();
            range.selectNodeContents(content);
            return {
                text: badge.textContent.trim(),
                title: content.getAttribute('title'),
                height: rect.height,
                width: rect.width,
                textHeight: range.getBoundingClientRect().height,
                whiteSpace: getComputedStyle(badge).whiteSpace,
                // clientWidth rounds to integer pixels; allow that rounding only.
                clipped: range.getBoundingClientRect().width > content.clientWidth + 1,
                column: badge.closest('td')?.className || 'flex',
            };
        })""")
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        if not args.record_only:
            assert not errors, errors
            assert all(item["whiteSpace"] == "nowrap" for item in metrics), metrics
            assert all(item["height"] <= 26 and item["textHeight"] <= 22 for item in metrics), metrics
            for item in metrics:
                if "invoice-status" in item["column"] and not item["text"].startswith("未知"):
                    assert not item["clipped"], item
                if "invoice-sync" in item["column"] or "invoice-type" in item["column"]:
                    assert not item["clipped"], item
                if "registered-status" in item["column"] or "multiple-status" in item["column"]:
                    assert not item["clipped"], item
                if not item["column"] == 'flex':
                    assert item["title"] == item["text"], item
            # Unknown codes may truncate, but the complete label must remain accessible.
            page.locator("td.invoice-status").nth(3).hover()
            tooltip = page.get_by_role("tooltip")
            tooltip.wait_for(state="visible")
            assert "未知状态（future_long_status_code）" in tooltip.inner_text()
            close_geometry = page.locator('.closable-status .el-tag__close').evaluate("""button => {
                const rect = button.getBoundingClientRect();
                const badge = button.closest('.status-badge').getBoundingClientRect();
                return {left: rect.left, right: rect.right, badgeLeft: badge.left, badgeRight: badge.right};
            }""")
            assert close_geometry["left"] >= close_geometry["badgeLeft"], close_geometry
            assert close_geometry["right"] <= close_geometry["badgeRight"], close_geometry
            page.locator('.closable-status .el-tag__close').click()
            page.locator('.close-result').wait_for()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        mobile_heights = page.locator(".status-badge").evaluate_all("badges => badges.map(b => b.getBoundingClientRect().height)")
        if not args.record_only:
            assert all(height <= 26 for height in mobile_heights), mobile_heights
        report = {"desktop": metrics, "mobile_heights": mobile_heights, "page_errors": errors, "record_only": args.record_only}
        (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        browser.close()
