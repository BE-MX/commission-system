"""Actual Vue components; all HTTP calls intercepted, no production writes."""
import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from tests.domestic_workflows_fixture import browser_facts

facts = browser_facts()
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3087"
output = ROOT / "tmp/domestic-workflows-browser"
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for width in (1440, 390):
        context = browser.new_context(viewport={"width": width, "height": 1000}, timezone_id="America/New_York", reduced_motion="reduce")
        page = context.new_page()
        errors, unexpected, posts, warnings = [], [], [], []
        page.on("console", lambda message: warnings.append(message.text) if message.type == "warning" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        requests = [
            dict(id=1, customer_id=1, customer_name="测试门店", request_type="recharge", amount=500, status="pending", created_by=1, created_by_name="申请人", created_at="2026-10-12 10:00:00", has_voucher=True, change_membership=False, remark="Original", resubmitted_request_id=None),
            dict(id=2, customer_id=1, customer_name="Other", request_type="recharge", amount=800, status="pending", created_by=2, has_voucher=True),
        ]
        order = dict(id=1, domestic_no="DO-BROWSER", order_no="Synthetic", order_kind="business", customer_id=1, created_by=1, status=5, review_version=1, total_amount=880, charged_amount=0, order_date="2026-10-01", order_category="normal", items=[], customer_name="测试门店")
        def route_handler(route):
            request = route.request
            url = urlparse(request.url)
            path, query = url.path, parse_qs(url.query)
            if not path.startswith("/api/"):
                route.continue_()
                return
            data = None
            if path == "/api/domestic/customer-requests":
                rows = [row for row in requests if not query.get("status") or row["status"] == query["status"][0]]
                data = {"items": rows, "total": len(rows)}
            elif path.endswith("/customer-requests/1/withdraw"):
                posts.append(path); requests[0].update(status="withdrawn", withdrawn_at="2026-10-12 10:05:00"); data = requests[0]
            elif path.endswith("/customer-requests/1/resubmit"):
                posts.append(path)
                payload = json.loads(re.search(r'name="data"\r\n\r\n(.*?)\r\n', request.post_data, re.S).group(1))
                assert payload["amount"] == 650 and payload["remark"] == "Updated voucher"
                requests[0]["resubmitted_request_id"] = 3
                data = {**requests[0], **payload, "id": 3, "status": "pending", "resubmitted_request_id": None}
                requests.append(data)
            elif path == "/api/domestic/orders":
                data = {"items": [order], "total": 1}
            elif path == "/api/domestic/orders/1":
                data = order
            elif path == "/api/domestic/orders/1/withdraw-review":
                assert request.post_data_json["review_version"] == 1
                posts.append(path); order["status"] = 0; data = {"id": 1, "status": 0}
            elif path in ("/api/domestic/options", "/api/domestic/customers/options"):
                data = {"owners": [], "order_categories": [], "order_types": [], "order_channels": []}
            elif path == "/api/domestic/process-routes":
                data = []
            elif path == "/api/domestic-decision/filters":
                data = facts["options"]
            elif path == "/api/domestic-decision/analysis-runs":
                data = facts["analysis"]
            elif path in ("/api/domestic-decision/views", "/api/domestic-decision/actions", "/api/domestic-decision/briefs"):
                data = []
            elif path.endswith("/browser-synthetic-run/rows"):
                rows = copy.deepcopy(facts["analysis"]["stylists"]["details"])
                if query.get("stylist_id"):
                    rows = [row for row in rows if row["user_id"] == int(query["stylist_id"][0])]
                assert query.get("kind") == ["stylist_reports"]
                data = {"items": rows, "total": len(rows)}
            elif "/api/domestic-decision/evidence/reports/" in path:
                data = next(row for row in facts["analysis"]["stylists"]["details"] if row["id"] == int(path.rsplit("/", 1)[1]))
            else:
                unexpected.append(path)
                route.fulfill(status=503, json={"detail": "Unexpected isolated endpoint"})
                return
            route.fulfill(json={"code": 200, "message": "OK", "data": data})
        page.route("**/api/**", route_handler)
        page.goto(base + "/tests/domesticWorkflowsHarness.html")
        page.wait_for_load_state("networkidle")
        if not page.get_by_role("button", name="撤回申请", exact=True).count():
            print(json.dumps({"errors": errors, "unexpected": unexpected, "body": page.locator("body").inner_text()[:3000]}, ensure_ascii=True))
            page.screenshot(path=str(output / "initial-failure.png"), full_page=True)
        expect(page.get_by_role("button", name="撤回申请", exact=True)).to_have_count(1)
        page.get_by_role("button", name="撤回申请", exact=True).click()
        page.locator(".el-message-box").get_by_role("button", name="撤回申请", exact=True).click()
        dialog = page.get_by_role("dialog", name="修改已撤回申请")
        expect(dialog).to_be_visible()
        dialog.get_by_role("spinbutton").fill("650")
        dialog.locator("textarea").fill("Updated voucher")
        page.screenshot(path=str(output / f"withdraw-edit-{width}.png"), full_page=True)
        dialog.get_by_role("button", name="重新提交审核", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.locator("tbody").get_by_text("测试门店", exact=True)).to_be_visible()
        assert posts.count("/api/domestic/customer-requests/1/resubmit") == 1
        page.get_by_role("button", name="orders", exact=True).click()
        expect(page.get_by_role("button", name="撤回申请", exact=True)).to_have_count(1)
        page.get_by_role("button", name="撤回申请", exact=True).click()
        page.locator(".el-message-box").get_by_role("button", name="撤回申请", exact=True).click()
        expect(page.get_by_role("button", name="编辑", exact=True)).to_be_visible()
        page.get_by_role("button", name="编辑", exact=True).click()
        expect(page.get_by_role("dialog", name="编辑订单", exact=True)).to_be_visible()
        page.get_by_role("dialog", name="编辑订单", exact=True).get_by_role("button", name="关闭", exact=True).click()
        page.get_by_role("button", name="decision", exact=True).click()
        page.get_by_role("tab", name="发型师分析", exact=True).click()
        expect(page.get_by_role("heading", name="发型师工作量")).to_be_visible()
        expect(page.locator(".decision-metric").first.locator("strong")).to_have_text("5")
        matrix = page.locator(".decision-chart").nth(2)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(output / f"stylist-inspect-{width}.png"), full_page=True)
        expect(page.locator(".decision-chart")).to_have_count(3)
        assert page.locator(".decision-chart canvas").count() >= 3
        assert not page.get_by_role("heading", name="行动闭环", exact=True).is_visible()
        expect(matrix).to_be_visible()
        assert len(matrix.evaluate("element => window.chartOption(element).xAxis[0].data")) == 2
        page.screenshot(path=str(output / f"stylist-{width}.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.get_by_text("全部发型师", exact=True).click()
        page.get_by_role("option", name="发型师甲", exact=True).click()
        expect(page.locator(".decision-metric").first.locator("strong")).to_have_text("2")
        page.get_by_role("button", name="查看报工明细", exact=True).first.click()
        drawer = page.locator(".el-drawer").filter(has=page.get_by_role("heading", name=re.compile(" · 做发型报工")))
        expect(drawer).to_be_visible()
        drawer.get_by_role("button", name=re.compile("^订单号，")).click()
        page.wait_for_load_state("networkidle")
        assert not errors, errors
        assert not unexpected, unexpected
        assert posts.count("/api/domestic/orders/1/withdraw-review") == 1
        print(f"PASS {width}px: withdraw -> edit -> resubmit; price draft edit; stylist 5 pieces; drill sort")
        context.close()
    browser.close()
