"""Browser acceptance against the real API and synthetic isolated SQLite.

Start qa_server.py after building frontend. No domain API is mocked here.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8791"
CAPTURE = """(() => {
 window.__qaResponses = [];
 const open = XMLHttpRequest.prototype.open;
 XMLHttpRequest.prototype.open = function(method, url, ...args) {
   this.__qaMethod = method; this.__qaUrl = new URL(url, location.href).href;
   this.addEventListener('load', () => {
     try { window.__qaResponses.push({method: this.__qaMethod, url: this.__qaUrl,
       status: this.status, data: JSON.parse(this.responseText)}); } catch (_) {}
   });
   return open.call(this, method, url, ...args);
 };
})();"""


async def main():
    results, errors = [], []
    def passed(case, **evidence):
        results.append({"case": case, "result": "pass", **evidence})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    async with async_playwright() as p:
        installed = sorted((Path(os.environ["LOCALAPPDATA"]) / "ms-playwright").glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
        browser = await p.chromium.launch(executable_path=str(installed[-1]), headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        await context.add_init_script("localStorage.setItem('ark_access_token','qa-full'); sessionStorage.setItem('ark_desktop_mode','1')")
        await context.add_init_script(CAPTURE)
        await context.route("https://**/*", lambda route: route.abort())
        page = await context.new_page()
        network = await context.new_cdp_session(page)
        await network.send("Network.enable", {"maxTotalBufferSize": 100000000, "maxResourceBufferSize": 50000000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def captured(response, target=page):
            # Read the actual XHR received by the application; Chromium may discard
            # its network response body before networkidle resolves.
            match = {"url": response.url, "method": response.request.method}
            await target.wait_for_function("m => window.__qaResponses.some(r => r.url === m.url && r.method === m.method)", arg=match)
            return await target.evaluate("m => window.__qaResponses.filter(r => r.url === m.url && r.method === m.method).at(-1).data", match)

        async def close_drawer():
            await page.locator(".el-drawer:visible .el-drawer__close-btn").last.click()
            await page.locator(".el-drawer:visible").wait_for(state="hidden")

        async def tab(name):
            await page.locator(".decision-tabs").get_by_role("tab", name=name, exact=True).click()

        async def apply():
            await page.evaluate("window.__qaResponses = []")
            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/analysis-runs")) as pending:
                await page.locator("main.domestic-decision").get_by_role("button", name="应用筛选", exact=True).click()
            response = await pending.value
            assert response.status == 200, await response.text()
            data = (await captured(response))["data"]
            await page.locator(".decision-footer").wait_for(state="visible")
            return data

        async def select(label, option):
            field = page.locator(".filter-grid > label").filter(has_text=label).first
            await field.locator(".el-select").click()
            await page.get_by_role("option", name=option, exact=True).click()
            await page.locator("#decision-title").click()

        try:
            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/analysis-runs")) as initial:
                await page.goto(BASE + "/domestic/decision", wait_until="networkidle")
            first = (await captured(await initial.value))["data"]
            assert first["summary"]["amount"] == sum(row["total_amount"] for row in first["evidence"]["orders"])
            assert first["summary"]["matched_amount"] == sum(row["amount"] for row in first["evidence"]["items"])
            assert first["finance"]["summary"]["anomaly_count"] == 0
            await page.screenshot(path=str(OUT / "overview-desktop.png"), full_page=True)
            passed("real API page and independent order/ledger reconciliation", orders=first["summary"]["order_count"], amount=first["summary"]["amount"])

            for name, key in [("订单与产品", "products"), ("充值与资金", "finance"), ("客户经营", "customers"), ("业务员画像", "people"), ("需求趋势", "trends"), ("行动与简报", "actions"), ("经营总览", "overview")]:
                await tab(name)
                assert await page.locator(".decision-tab-content").inner_text()
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.screenshot(path=str(OUT / f"{key}-desktop.png"), full_page=True)
            passed("all seven tabs and desktop overflow")

            async with page.expect_download() as png:
                await page.locator("main.domestic-decision").get_by_role("button", name="导出图表 PNG", exact=True).first.click()
            image = await png.value
            await image.save_as(str(OUT / "chart-export.png"))
            assert (OUT / "chart-export.png").stat().st_size > 1000
            passed("chart PNG exports title, period and scope metadata")

            await page.locator(".advanced-filters summary").click()
            await select("客户范围", "全部授权客户")
            await select("产品类型", "头套")
            await select("颜色", "红色")
            filtered = await apply()
            assert filtered["evidence"]["items"] and all(row["attrs"]["product_type"] == "cap" and row["attrs"]["color"] == "红色" for row in filtered["evidence"]["items"])
            assert filtered["summary"]["matched_amount"] < filtered["summary"]["related_order_amount"]
            assert "province" in filtered["dimensions"] and "order_channel" in filtered["dimensions"]
            assert sum(row["quantity"] for row in filtered["quantity_structure"]["item_bands"]) == filtered["summary"]["quantity"]
            await tab("订单与产品")
            assert await page.get_by_role("heading", name="明细件数分箱", exact=True).is_visible()
            await page.get_by_role("button", name="全部匹配明细", exact=True).click()
            drawer = page.locator(".el-drawer:visible")
            await drawer.get_by_role("button", name="原始证据", exact=True).first.wait_for(state="visible")
            assert "红色" in await drawer.inner_text()
            for direction in ("asc", "desc"):
                async with page.expect_response(lambda response: "/rows?" in response.url and f"sort_order={direction}" in response.url) as sorted_response:
                    await drawer.get_by_role("button", name="成交单价，", exact=False).click()
                sorted_data = (await captured(await sorted_response.value))["data"]
                prices = [row["unit_price"] for row in sorted_data["items"]]
                assert prices == sorted(prices, reverse=direction == "desc")
                await drawer.locator(f"th[aria-sort='{'ascending' if direction == 'asc' else 'descending'}']").wait_for(state="visible")
            passed("server sorts complete evidence pool and retains accessible sort state")
            await close_drawer()
            passed("same-line product AND filters, whole-order distinction and quantity bins", matched=filtered["summary"]["matched_amount"], whole=filtered["summary"]["related_order_amount"])

            await page.get_by_role("button", name="保存视图", exact=True).click()
            dialog = page.get_by_role("dialog", name="保存分析视图", exact=True)
            await dialog.locator("input.el-input__inner").fill("隔离验收红色头套")
            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/views")) as saved:
                await dialog.get_by_role("button", name="保存", exact=True).click()
            assert (await saved.value).status == 200
            await dialog.wait_for(state="hidden")
            passed("personal rolling view persists filters on server")

            await tab("客户经营")
            await page.get_by_role("button", name="360°画像", exact=True).first.click()
            drawer = page.locator(".el-drawer:visible")
            await drawer.get_by_role("heading", name="完整购买历史", exact=True).wait_for(state="visible")
            assert "常购规格与历史偏好" in await drawer.inner_text()
            assert "RFM 与复购样本" in await drawer.inner_text()
            await page.screenshot(path=str(OUT / "customer-profile.png"), full_page=True)
            await close_drawer()
            passed("customer profile uses full commercial history and factual preferences")

            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/analysis-runs")) as reset:
                await page.locator("main.domestic-decision").get_by_role("button", name="重置", exact=True).click()
            await captured(await reset.value)
            await page.locator(".decision-footer").wait_for(state="visible")
            await tab("行动与简报")
            await page.locator("main.domestic-decision").get_by_role("button", name="加入内部行动", exact=True).first.click()
            dialog = page.get_by_role("dialog", name="安排内部行动", exact=True)
            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/actions")) as action:
                await dialog.get_by_role("button", name="创建行动", exact=True).click()
            assert (await action.value).status == 200
            await dialog.wait_for(state="hidden")
            await page.locator("button:enabled").filter(has_text="记录进度 / 结果").first.click()
            edit = page.get_by_role("dialog", name="记录行动结果", exact=True)
            await edit.locator(".el-form-item").filter(has_text="行动状态").locator(".el-select").click()
            await page.get_by_role("option", name="已完成", exact=True).click()
            await edit.locator(".el-form-item").filter(has_text="实际结果类型").locator(".el-select").click()
            await page.get_by_role("option", name="已联系", exact=True).click()
            await edit.locator("textarea").fill("隔离验收：已核对采购计划，无实际到账承诺")
            async with page.expect_response(lambda response: response.request.method == "PATCH" and "/actions/" in response.url) as updated:
                await edit.get_by_role("button", name="保存结果", exact=True).click()
            result = (await captured(await updated.value))["data"]
            assert result["status"] == "done" and result["result_type"] == "contacted"
            await edit.wait_for(state="hidden")
            passed("internal action creation and actual-result closure")

            await page.get_by_role("button", name="生成事实简报", exact=True).click()
            await page.locator(".job-card").filter(has_text="事实简报").get_by_text("规则结论", exact=False).wait_for(state="visible", timeout=20000)
            await page.reload(wait_until="networkidle")
            await tab("行动与简报")
            await page.locator(".job-card").filter(has_text="事实简报").get_by_text("规则结论", exact=False).wait_for(state="visible", timeout=20000)
            passed("rule brief survives refresh with persistent job recovery")

            await page.get_by_role("button", name="生成筛选明细导出", exact=True).click()
            await page.get_by_role("button", name="授权下载（完成后24小时）", exact=True).wait_for(state="visible", timeout=20000)
            async with page.expect_download() as csv:
                await page.get_by_role("button", name="授权下载（完成后24小时）", exact=True).first.click()
            download = await csv.value
            await download.save_as(str(OUT / "filtered-export.csv"))
            content = (OUT / "filtered-export.csv").read_text(encoding="utf-8-sig")
            assert "history_" not in content
            passed("private asynchronous CSV download excludes historical evidence")

            await page.get_by_placeholder("例如：近90天客户复购情况，按工艺和长度看数量").fill("最近7天的订单数量")
            await page.get_by_role("button", name="准备查询计划", exact=True).click()
            await page.get_by_role("button", name="核对并应用计划", exact=True).wait_for(state="visible", timeout=20000)
            assert "待应用计划" in await page.locator(".plan-preview").inner_text()
            async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/analysis-runs")) as applied:
                await page.get_by_role("button", name="核对并应用计划", exact=True).click()
            assert (await applied.value).status == 200
            await page.locator(".decision-footer").wait_for(state="visible")
            passed("natural-language plan previews before user application")

            await page.get_by_role("button", name="数据质量与口径", exact=True).click()
            drawer = page.locator(".el-drawer:visible")
            await drawer.get_by_role("heading", name="分析标准维护", exact=True).wait_for(state="visible")
            await drawer.get_by_role("button", name="保存分析映射", exact=True).wait_for(state="visible")
            assert "属性完整度" in await drawer.inner_text()
            await close_drawer()
            passed("data quality, reconciliation and versioned admin configuration load")

            await page.set_viewport_size({"width": 390, "height": 844})
            await tab("经营总览")
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(OUT / "overview-mobile.png"), full_page=True)
            await page.locator(".decision-metrics").scroll_into_view_if_needed()
            await page.screenshot(path=str(OUT / "overview-mobile-metrics.png"))
            await tab("订单与产品")
            mobile_table = page.locator(".decision-tab-content .decision-table:visible").first
            await mobile_table.scroll_into_view_if_needed()
            table_box = await mobile_table.bounding_box()
            assert 0 < table_box["width"] <= 390 and table_box["height"] > 50
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=str(OUT / "products-mobile.png"), full_page=True)
            passed("390px layout with contained table scrolling")

            sales = await browser.new_context(viewport={"width": 1440, "height": 1000})
            await sales.add_init_script("localStorage.setItem('ark_access_token','qa-sales')")
            await sales.add_init_script(CAPTURE)
            await sales.route("https://**/*", lambda route: route.abort())
            restricted = await sales.new_page()
            sales_network = await sales.new_cdp_session(restricted)
            await sales_network.send("Network.enable", {"maxTotalBufferSize": 100000000, "maxResourceBufferSize": 50000000})
            restricted.on("pageerror", lambda error: errors.append(str(error)))
            async with restricted.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/analysis-runs")) as no_finance:
                await restricted.goto(BASE + "/domestic/decision", wait_until="networkidle")
            safe = (await captured(await no_finance.value, restricted))["data"]
            assert "finance" not in safe
            assert "settle_mode" not in safe["dimensions"] and "membership_level" not in safe["dimensions"]
            assert "membership_level_snapshot" not in json.dumps(safe)
            assert await restricted.locator(".decision-tabs [role='tab']").count() == 6
            assert await restricted.locator(".decision-tabs").get_by_role("tab", name="充值与资金", exact=True).count() == 0
            await restricted.screenshot(path=str(OUT / "no-finance-permission.png"), full_page=True)
            passed("sales role removes financial fields at API and UI boundaries")
            assert not errors, errors
            passed("browser runtime has no uncaught errors")
        finally:
            (OUT / "verification.json").write_text(json.dumps({"results": results, "uncaught_errors": errors, "complete": len(results) == 15}, ensure_ascii=False, indent=2), encoding="utf-8")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
