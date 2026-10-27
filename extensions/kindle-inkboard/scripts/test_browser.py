"""Exercise the actual Vue component against local, explicitly synthetic HTTP fixtures."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "docs/evidence"
output.mkdir(exist_ok=True)
notes = [{"id": 1, "title": "本周重点", "body": "完成 Kindle 看板试用，核对消息提醒。", "version": 1}]
devices = [{"id": 1, "name": "Kindle PW3", "created_at": "2026-10-25T12:00:00+08:00", "last_received_at": "2026-10-25T12:05:00+08:00", "revoked_at": None}]
messages, requests, errors = [], [], []

def route_api(route):
    path = route.request.url.split("/api/inkboard")[-1]
    method = route.request.method
    payload = route.request.post_data_json if method in ("POST", "PUT") else None
    if path == "/devices" and method == "GET":
        data = devices
    elif path == "/notes" and method == "GET":
        data = notes
    elif path == "/messages" and method == "GET":
        data = messages
    elif path == "/messages" and method == "POST":
        requests.append(payload)
        # Emulate an accepted write with a lost response; retry must retain its key.
        if not messages:
            messages.append({**payload, "id": 1, "created_at": "2026-10-25T12:10:00+08:00", "withdrawn": False,
                             "received_count": 0, "read_count": 0, "device_count": 1})
            route.abort("failed"); return
        data = messages[0]
    elif path == "/notes" and method == "POST":
        data = {**payload, "id": 2, "version": 1}; notes.append(data)
    elif path == "/messages/1/withdraw":
        messages[0]["withdrawn"] = True; data = messages[0]
    elif path == "/devices" and method == "POST":
        data = {"id": 2, "name": payload["name"], "token": "ink_" + "x" * 43}
    else:
        raise AssertionError(f"Unexpected local QA request: {method} {path}")
    route.fulfill(status=200, content_type="application/json", body=json.dumps({"code": 200, "message": "ok", "data": data}, ensure_ascii=False))

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1360, "height": 1000}, device_scale_factor=1)
    page.add_init_script("localStorage.setItem('ark_access_token','local-qa-only')")
    page.route("**/api/inkboard/**", route_api)
    page.route("https://**", lambda r: r.abort())
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:3017/inkboard-qa.html")
    page.wait_for_load_state("networkidle")
    if errors:
        raise AssertionError(errors)
    expect(page.get_by_text("Kindle PW3", exact=True)).to_be_visible()
    expect(page.get_by_text("本周重点", exact=True)).to_be_visible()
    page.get_by_label("标题", exact=True).first.fill("项目提醒")
    page.get_by_label("内容", exact=True).first.fill("请查看最新待办")
    page.get_by_role("button", name="发送到 Kindle", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="消息提交结果未确认")).to_be_visible()
    page.get_by_role("button", name="重试同一条消息", exact=True).click()
    expect(page.get_by_text("项目提醒", exact=True)).to_be_visible()
    assert len(requests) == 2 and requests[0]["request_key"] == requests[1]["request_key"]
    page.get_by_role("button", name="新建备忘", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("标题", exact=True).fill("会议资料")
    dialog.get_by_label("内容", exact=True).fill("明早带上规划方案")
    dialog.get_by_role("button", name="保存", exact=True).click()
    expect(page.get_by_text("会议资料", exact=True)).to_be_visible()
    expect(dialog).not_to_be_visible()
    expect(page.locator('.el-message')).to_have_count(0)
    page.screenshot(path=str(output / "ark-inkboard-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "ark-inkboard-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile horizontal overflow"
    page.get_by_role("button", name="绑定设备", exact=True).click()
    prompt = page.get_by_role("dialog")
    prompt.get_by_role("button", name="绑定", exact=True).click()
    expect(page.get_by_role("dialog").filter(has_text="设备凭证仅显示这一次")).to_be_visible()
    # Config credentials must be downloadable but not printed into the DOM.
    assert "ink_" + "x" * 43 not in page.content()
    with page.expect_download() as download:
        page.get_by_role("button", name="下载设备配置", exact=True).click()
    assert download.value.suggested_filename == "ark-board.local.json"
    page.get_by_role("button", name="关闭", exact=True).last.click()
    assert not errors, errors
    browser.close()
print("browser: task page, notes, uncertain-send retry, mobile layout, binding and config download passed (synthetic fixtures)")
