"""Isolated bell -> notice -> original image regression; no backend traffic."""
import argparse
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:3038')
parser.add_argument('--output', default='tmp/announcement-preview')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    results = []
    for width in (1280, 390):
        context = browser.new_context(viewport={'width': width, 'height': 850}, reduced_motion='reduce')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route(re.compile(r'^https?://[^/]+/api/'), lambda route: route.abort())
        page.goto(args.base_url + '/tests/fixtures/announcement-preview/index.html')
        bell = page.get_by_role('button', name='公告，2 条未读', exact=True)
        bell.click()
        assert page.evaluate('previewTest.reads.length') == 0
        page.get_by_role('button', name='图片公告 1').click()
        trigger = page.get_by_role('button', name='查看原图：公告图片 1', exact=True)
        expect(trigger).to_be_visible()
        expect(page.get_by_text('图片暂时无法加载', exact=True)).to_be_visible()
        expect(page.locator('.image-preview-trigger')).to_have_count(1)
        source = trigger.locator('img').get_attribute('src')
        page.wait_for_function('previewTest.reads.length === 1')
        loads = page.evaluate('previewTest.imageLoads.length')
        trigger.click()
        viewer = page.locator('.el-image-viewer__wrapper')
        expect(viewer).to_be_visible()
        image = viewer.locator('img')
        expect(image).to_have_attribute('src', source)
        page.wait_for_function("document.querySelector('.el-image-viewer__img')?.naturalWidth === 1600")
        assert page.evaluate('previewTest.imageLoads.length') == loads
        assert page.evaluate('previewTest.reads') == [1]
        assert viewer.evaluate('(el) => el.parentElement === document.body')
        viewer.locator('.el-image-viewer__actions__inner .el-icon').nth(1).click()
        expect(image).to_have_attribute('style', re.compile(r'scale\(1\.2\)'))
        page.screenshot(path=str(out / f'preview-{width}.png'))
        page.keyboard.press('Escape')
        expect(viewer).to_have_count(0)
        expect(page.locator('.announcement-inbox-dialog')).to_be_visible()
        expect(trigger).to_be_focused()
        page.keyboard.press('Enter')
        expect(viewer).to_be_visible()
        viewer.locator('.el-image-viewer__close').click()
        expect(viewer).to_have_count(0)
        expect(trigger).to_be_focused()
        if width == 390:
            page.get_by_role('button', name='返回公告列表', exact=True).click()
        page.get_by_role('button', name='图片公告 2').click()
        next_trigger = page.get_by_role('button', name='查看原图：公告图片 2', exact=True)
        expect(next_trigger).to_be_visible()
        next_trigger.focus()
        page.keyboard.press('Space')
        expect(viewer).to_be_visible()
        expect(viewer.locator('img')).to_have_attribute('src', next_trigger.locator('img').get_attribute('src'))
        page.keyboard.press('Escape')
        page.keyboard.press('Escape')
        expect(page.locator('.announcement-inbox-dialog')).to_have_count(0)
        expect(page.locator('.announcement-bell')).to_be_focused()
        assert not errors, errors
        results.append({'width': width, 'original_width': 1600, 'zoom_keyboard_focus_and_switch': 'pass', 'page_errors': errors})
        context.close()
    browser.close()
(out / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: bell, read tracking, original image, zoom, Escape, keyboard, focus, switch, failed image; desktop and mobile')
