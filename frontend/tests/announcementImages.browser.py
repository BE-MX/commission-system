"""Real Vue/Tiptap image regression with isolated API adapters; no backend writes."""
import argparse
import base64
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:3027')
parser.add_argument('--output', default='tmp/announcement-images')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
image_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGOUq1jFgA0wYRUdtBIA/fwBUFSn/xkAAAAASUVORK5CYII=')
base = args.base_url + '/tests/fixtures/editor-images/index.html'

def paste(page, native=False):
    page.locator('.tiptap p').first.click()
    page.keyboard.press('Home')
    if native:
        page.evaluate('''async bytes => {
          await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([new Uint8Array(bytes)], {type:'image/png'})})]);
        }''', list(image_bytes))
        page.keyboard.press('Control+v')
        return
    page.evaluate('''bytes => {
      const data = new DataTransfer();
      data.items.add(new File([new Uint8Array(bytes)], 'screenshot.png', {type:'image/png'}));
      document.querySelector('.tiptap').dispatchEvent(new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData:data}));
    }''', list(image_bytes))

def choose(page):
    with page.expect_file_chooser() as chooser:
        page.get_by_role('button', name='图片', exact=True).click()
    chooser.value.set_files({'name': 'local.png', 'mimeType': 'image/png', 'buffer': image_bytes})

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    results = []
    for missing_uuid in (False, True):
        context = browser.new_context(viewport={'width':1100,'height':1000}, permissions=['clipboard-read','clipboard-write'])
        if missing_uuid:
            context.add_init_script("Object.defineProperty(crypto, 'randomUUID', {value:undefined})")
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(base)
        page.wait_for_load_state('networkidle')
        expect(page.locator('.tiptap')).to_have_attribute('contenteditable', 'true')
        expect(page.locator('.tiptap')).to_contain_text('原有正文')
        try:
            choose(page)
            expect(page.locator('.knowledge-image img')).to_have_count(1)
            paste(page, native=not missing_uuid)
            expect(page.locator('.knowledge-image img')).to_have_count(2)
        except AssertionError:
            (out / 'failure.json').write_text(json.dumps({'missing_randomUUID':missing_uuid,
                'state':page.evaluate('imageTest'), 'html':page.locator('.tiptap').inner_html(), 'errors':errors}, ensure_ascii=False, indent=2), encoding='utf-8')
            page.screenshot(path=str(out / 'failure.png'), full_page=True)
            raise
        page.get_by_role('button', name='保存草稿', exact=True).click()
        expect(page.get_by_role('button', name='提交审核', exact=True)).to_be_enabled()
        content = page.evaluate('imageTest.saves[0].content')
        images = [n for n in content['content'] if n['type'] == 'knowledgeImage']
        assert sorted(n['attrs']['assetId'] for n in images) == [1,2], images
        assert all(set(n['attrs']) == {'assetId','alt','caption'} for n in images)
        assert page.evaluate('imageTest.uploads.length') == 2
        page.reload()
        expect(page.locator('.knowledge-image img')).to_have_count(2)
        page.wait_for_function("[...document.querySelectorAll('.knowledge-image img')].every(img => img.complete && img.naturalWidth > 0)")
        expect(page.locator('.tiptap')).to_contain_text('原有正文')
        assert not errors, errors
        page.screenshot(path=str(out / ('http-no-uuid.png' if missing_uuid else 'https-capable.png')), full_page=True)
        results.append({'missing_randomUUID':missing_uuid,'uploads':2,'saved_images':2,'page_errors':errors})
        context.close()
    # Pending/failed uploads cannot be silently saved. Removing a failed node unblocks editing.
    context = browser.new_context()
    page = context.new_page()
    page.goto(base)
    page.wait_for_load_state('networkidle')
    page.evaluate('imageTest.delay = 1500; imageTest.fail = true')
    choose(page)
    expect(page.get_by_text('正在安全上传图片…')).to_be_visible()
    page.get_by_role('button', name='保存草稿', exact=True).click()
    assert page.evaluate('imageTest.saves.length') == 0
    expect(page.get_by_text('上传失败', exact=True)).to_be_visible()
    page.get_by_role('button', name='保存草稿', exact=True).click()
    assert page.evaluate('imageTest.saves.length') == 0
    page.get_by_role('button', name='移除', exact=True).click()
    page.get_by_role('button', name='保存草稿', exact=True).click()
    page.wait_for_function('imageTest.saves.length === 1')
    results.append({'pending_and_failed_upload_save_blocked':True})
    context.close()
    # Undo while uploading then paste again: the old result must not bind to the new node.
    context = browser.new_context()
    page = context.new_page()
    page.goto(base)
    page.wait_for_load_state('networkidle')
    page.evaluate('imageTest.delay = 1000')
    choose(page)
    expect(page.get_by_text('正在安全上传图片…')).to_be_visible()
    page.locator('.tiptap p').first.click()
    page.keyboard.press('Control+z')
    expect(page.locator('.knowledge-image')).to_have_count(0)
    paste(page)
    expect(page.locator('.knowledge-image img')).to_have_count(1)
    page.wait_for_function('imageTest.deletes.includes(1)')
    page.get_by_role('button', name='保存草稿', exact=True).click()
    page.wait_for_function('imageTest.saves.length === 1')
    image_nodes = [n for n in page.evaluate('imageTest.saves[0].content.content') if n['type'] == 'knowledgeImage']
    assert [n['attrs']['assetId'] for n in image_nodes] == [2]
    results.append({'undo_then_paste_does_not_reuse_old_upload':True})
    context.close()
    # Overlapping paste operations keep independent placeholder/result associations.
    context = browser.new_context()
    page = context.new_page()
    page.goto(base)
    page.wait_for_load_state('networkidle')
    page.evaluate('imageTest.delay = 800')
    paste(page)
    paste(page)
    expect(page.locator('.knowledge-image img')).to_have_count(2)
    page.get_by_role('button', name='保存草稿', exact=True).click()
    page.wait_for_function('imageTest.saves.length === 1')
    image_nodes = [n for n in page.evaluate('imageTest.saves[0].content.content') if n['type'] == 'knowledgeImage']
    assert sorted(n['attrs']['assetId'] for n in image_nodes) == [1,2]
    results.append({'overlapping_paste_uploads':True})
    context.close()
    # The shared knowledge editor retains image support; viewers cannot insert files.
    for query in ('?knowledge=1', '?viewer=1'):
        context = browser.new_context()
        page = context.new_page()
        page.goto(base + query)
        page.wait_for_load_state('networkidle')
        if 'viewer' in query:
            expect(page.locator('.tiptap')).to_have_attribute('contenteditable','false')
            paste(page)
            page.locator('input[type=file]').set_input_files({'name':'local.png','mimeType':'image/png','buffer':image_bytes})
            assert page.evaluate('imageTest.uploads.length') == 0
            expect(page.locator('.knowledge-image')).to_have_count(0)
        else:
            choose(page)
            expect(page.locator('.knowledge-image img')).to_have_count(1)
            assert page.evaluate('imageTest.uploads.length') == 1
        results.append({'context':query,'verified':True})
        context.close()
    browser.close()
(out / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: picker, native clipboard image, canonical save, reload, missing randomUUID, pending/failure save guard, undo/re-paste, overlapping uploads, knowledge editor, viewer guard')
