"""Exercise the actual knowledge workbench against a local fixture adapter."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:5176")
parser.add_argument("--output")
args = parser.parse_args()
url = f"{args.base_url}/tests/fixtures/knowledge-authoring/index.html"
title = "编辑器往返验证"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 920})
    page.set_default_timeout(9000)
    page.route(f"{args.base_url}/api/**", lambda route: route.abort())
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_role("button", name="新建文档").click()
    dialog = page.get_by_role("dialog", name="新建文档")
    dialog.get_by_role("textbox").fill(title)
    dialog.get_by_role("button", name="创建", exact=True).click()

    editor = page.locator(".document-canvas .tiptap")
    expect(editor).to_be_visible()
    expect(page.get_by_role("textbox", name="文档标题")).to_have_value(title)
    def settle_editor_focus():
        expect(editor).to_be_focused()
        # Tiptap restores DOM selection in an animation frame after a toolbar command.
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")

    toolbar = page.get_by_role("toolbar", name="文档格式工具栏")
    editor.click()
    page.keyboard.insert_text("样式示例")
    settle_editor_focus()
    editor.press("Control+a")
    page.wait_for_function("window.getSelection().toString() === '样式示例'")
    toolbar.get_by_role("button", name="下划线", exact=True).click()
    expect(editor.locator("u")).to_have_text("样式示例")
    toolbar.get_by_role("combobox", name="字号").select_option("24")
    expect(editor.locator("span[data-knowledge-size='24']")).to_have_text("样式示例")
    toolbar.get_by_role("button", name="文字高亮").click()
    page.get_by_role("menuitemradio", name="重点").click()
    toolbar.get_by_role("combobox", name="段落对齐").select_option("center")
    expect(editor.locator("p").first).to_have_css("text-align", "center")
    expect(editor.locator("u")).to_have_text("样式示例")
    expect(editor.locator("span[data-knowledge-size='24']")).to_have_text("样式示例")
    expect(editor.locator("mark[data-knowledge-highlight='gold']")).to_have_text("样式示例")

    # Clear text formatting while retaining alignment, and undo to keep the sample.
    toolbar.get_by_role("button", name="清除文字格式").click()
    expect(editor.locator("u, mark, [data-knowledge-size]")).to_have_count(0)
    expect(editor.locator("p").first).to_have_css("text-align", "center")
    editor.press("Control+z")
    expect(editor.locator("u")).to_have_text("样式示例")

    settle_editor_focus()
    # Set up the initial caret independently of the previous history command.
    editor.evaluate("element => element.editor.commands.setTextSelection(element.editor.state.doc.content.size - 1)")
    editor.press("Enter")
    expect(editor.locator(":scope > p")).to_have_text(["样式示例", ""])
    page.keyboard.insert_text("／callout")
    menu = page.get_by_role("listbox", name="插入内容")
    expect(menu.get_by_role("option", name="高亮块", exact=False)).to_be_visible()
    editor.press("Enter")
    expect(menu).to_be_hidden()
    settle_editor_focus()
    page.keyboard.insert_text("操作提示")
    expect(editor.locator("[data-knowledge-callout='info']")).to_have_text("操作提示")

    editor.locator(":scope > p").last.click()
    toolbar.get_by_role("button", name="插入", exact=True).click()
    menu.get_by_role("option", name="折叠块", exact=False).click()
    details = editor.locator("[data-type='details']")
    expect(details).to_be_visible()
    details.locator("summary").click()
    page.keyboard.insert_text("展开步骤")
    details.get_by_role("button", name="展开折叠块").click()
    details.locator("[data-type='detailsContent'] p").click()
    page.keyboard.insert_text("折叠正文")
    details.get_by_role("button", name="收起折叠块").click()
    expect(details.get_by_text("折叠正文")).to_be_hidden()
    settle_editor_focus()

    editor.locator(":scope > p").last.click()
    page.keyboard.insert_text("/image")
    expect(menu.get_by_role("option", name="图片", exact=False)).to_be_visible()
    settle_editor_focus()
    with page.expect_file_chooser():
        editor.press("Enter")
    expect(menu).to_be_hidden()

    toolbar.get_by_role("button", name="插入 3×3 表格").click()
    cells = editor.locator("tr").first.locator("th")
    expect(cells).to_have_count(3)
    a = cells.nth(0).bounding_box()
    b = cells.nth(1).bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=8)
    page.mouse.up()
    toolbar.get_by_role("button", name="合并单元格").click()
    expect(editor.locator("th[colspan='2']")).to_have_count(1)
    editor.locator("th[colspan='2']").click()
    toolbar.get_by_role("button", name="拆分单元格").click()
    expect(cells).to_have_count(3)

    save = page.get_by_role("button", name="保存草稿")
    save.click()
    expect(save).to_be_disabled()
    first_payload = page.evaluate("fixtureRequests.find(request => request.method === 'put').payload")
    assert first_payload["title"] == title
    assert {node["type"] for node in first_payload["content"]["content"]} >= {"paragraph", "knowledgeCallout", "details", "table"}

    page.reload()
    page.get_by_text(title, exact=True).click()
    expect(editor.locator("u")).to_have_text("样式示例")
    expect(editor.locator("[data-knowledge-callout]")).to_have_text("操作提示")
    expect(editor.locator("summary")).to_have_text("展开步骤")
    editor.locator(":scope > p").last.click()
    page.keyboard.insert_text("二次编辑")
    save.click()
    expect(save).to_be_disabled()

    if args.output:
        page.screenshot(path=str(Path(args.output).with_suffix(".png")))

    page.goto(f"{url}?preview")
    preview = page.locator(".knowledge-preview")
    expect(preview.locator("mark")).to_have_text("样式示例")
    expect(preview.locator("span[data-knowledge-size]")).to_have_css("font-size", "24px")
    expect(preview.get_by_text("二次编辑")).to_be_visible()
    preview.get_by_role("button", name="展开折叠块").click()
    expect(preview.get_by_text("折叠正文")).to_be_visible()

    page.goto(f"{url}?viewer")
    page.get_by_text(title, exact=True).click()
    expect(toolbar).to_have_count(0)
    expect(editor).to_have_attribute("contenteditable", "false")
    editor.get_by_role("button", name="展开折叠块").click()
    expect(editor.get_by_text("折叠正文")).to_be_visible()
    assert not errors, errors
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            json.dump(first_payload["content"], output, ensure_ascii=False)
    browser.close()

print("Knowledge workbench create, edit, save, reopen and preview passed.")
