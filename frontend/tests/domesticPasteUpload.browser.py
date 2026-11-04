import json, os, traceback, base64
from io import BytesIO
from PIL import Image
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[2] / 'tmp' / 'domestic-paste-upload'
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:3036/tests/fixtures/domestic-paste-upload/index.html'
results = []
images = {}
for mime, fmt in [('image/png', 'PNG'), ('image/jpeg', 'JPEG'), ('image/webp', 'WEBP')]:
    output = BytesIO()
    Image.new('RGB', (24, 24), '#c27c34').save(output, format=fmt)
    images[mime] = output.getvalue()

def check(name, fn):
    try:
        fn()
        results.append({'name': name, 'status': 'pass'})
        print('PASS', name, flush=True)
    except Exception as exc:
        results.append({'name': name, 'status': 'fail', 'error': str(exc)})
        print('FAIL', name, str(exc), flush=True)
        traceback.print_exc()

def paste(zone, files):
    for f in files:
        f['base64'] = base64.b64encode(images.get(f['type'], b'invalid')).decode()
    zone.evaluate('''(el, files) => { const dt = new DataTransfer(); for (const f of files) { const bytes=Uint8Array.from(atob(f.base64), c=>c.charCodeAt(0)); dt.items.add(new File([f.size ? new Uint8Array(f.size) : bytes], f.name, {type:f.type})); } el.dispatchEvent(new ClipboardEvent('paste', {clipboardData:dt,bubbles:true,cancelable:true})); }''', files)

def count(section, mode):
    return section.locator('.thumb' if mode == 'create' else '.dom-image').count()

def wait_count(section, mode, n):
    section.locator('.thumb' if mode == 'create' else '.dom-image').nth(n - 1).wait_for(timeout=8000) if n else None
    assert count(section, mode) == n, (count(section, mode), n)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='msedge')
    for mode in ('create', 'draft', 'edit'):
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, permissions=['clipboard-read', 'clipboard-write'])
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('http://127.0.0.1:3036/', 'data:', 'blob:')) else route.abort())
        page.goto(BASE + '?mode=' + mode, wait_until='networkidle')
        try:
            page.locator('.app-upload.transfer-zone').first.wait_for(timeout=10000)
            zones = page.locator('.app-upload.transfer-zone')
            sections = page.locator('.el-form-item').filter(has=page.locator('.app-upload.transfer-zone'))
            assert zones.count() == 4 and sections.count() == 4, (zones.count(), sections.count(), page.locator('body').inner_text())
        except Exception as exc:
            results.append({'name': mode + ' mount', 'status': 'fail', 'error': str(exc)})
            page.screenshot(path=str(OUT / (mode + '-mount-failure.png')), full_page=True)
            page.close()
            continue
        def four():
            for i, typ in enumerate(['image/png','image/jpeg','image/webp','image/png']):
                paste(zones.nth(i), [{'name': f'{mode}-{i}.png', 'type': typ}])
                wait_count(sections.nth(i), mode, 1)
                assert [count(sections.nth(j), mode) for j in range(4)] == [1 if j <= i else 0 for j in range(4)]
        check(mode + ' 四区粘贴 PNG/JPG/WebP 与隔离', four)
        def batch():
            paste(zones.nth(0), [{'name': f'batch-{j}.png', 'type':'image/png'} for j in range(3)])
            wait_count(sections.nth(0), mode, 4)
            assert all(count(sections.nth(i), mode) == 1 for i in range(1, 4))
        check(mode + ' 并发批量粘贴', batch)
        def delete_reupload():
            section = sections.nth(0)
            (section.locator('.thumb-del').first if mode == 'create' else section.get_by_text('移除图片').first).click()
            page.wait_for_timeout(150)
            assert count(section, mode) == 3
            paste(zones.nth(0), [{'name':'again.png', 'type':'image/png'}])
            wait_count(section, mode, 4)
        check(mode + ' 删除并重新粘贴', delete_reupload)
        def text_paste():
            before = page.evaluate('window.domesticTest.uploads.length')
            result = zones.nth(1).evaluate("el => { let dt = new DataTransfer(); dt.setData('text/plain','普通文字'); let ev = new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}); el.dispatchEvent(ev); return ev.defaultPrevented }")
            assert result is False and page.evaluate('window.domesticTest.uploads.length') == before
        check(mode + ' 普通文字粘贴未拦截', text_paste)
        if mode == 'create':
            def limit():
                paste(zones.nth(0), [{'name': f'limit-{j}.png','type':'image/png'} for j in range(4)])
                wait_count(sections.nth(0), mode, 6)
                assert page.get_by_text('最多上传 6 个文件').count() > 0
            check('create 六张上限含并发', limit)
            def reject():
                before = page.evaluate('window.domesticTest.uploads.length')
                paste(zones.nth(2), [{'name':'bad.gif','type':'image/gif'}, {'name':'huge.png','type':'image/png','size':20*1024*1024+1}])
                page.wait_for_timeout(300)
                assert page.evaluate('window.domesticTest.uploads.length') == before
                assert page.get_by_text('请上传 PNG / JPG / WebP 图片').count() and page.get_by_text('文件超过 20MB 限制').count()
            check('create 无效格式及超大拒绝', reject)
            def file_and_drop():
                sections.nth(3).locator('input[type=file]').set_input_files({'name':'chosen.jpg','mimeType':'image/jpeg','buffer':images['image/jpeg']})
                wait_count(sections.nth(3), mode, 2)
                zones.nth(3).evaluate("el => { let dt=new DataTransfer();dt.items.add(new File(['x'],'drag.webp',{type:'image/webp'}));el.dispatchEvent(new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true})) }")
                wait_count(sections.nth(3), mode, 3)
            check('create 文件选择和拖拽', file_and_drop)
            def real_clipboard():
                encoded = base64.b64encode(images['image/png']).decode()
                page.evaluate('''async data => { const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0)); await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([bytes],{type:'image/png'})})]); }''', encoded)
                zones.nth(2).focus()
                page.keyboard.press('Control+V')
                wait_count(sections.nth(2), mode, 2)
            check('create 系统剪贴板 Ctrl+V', real_clipboard)
        if mode != 'create':
            def preview():
                sections.nth(0).locator('.dom-image').first.click()
                page.locator('.el-image-viewer__wrapper').wait_for(timeout=5000)
                assert page.locator('.el-image-viewer__img').is_visible()
                page.wait_for_function("document.querySelector('.el-image-viewer__img')?.naturalWidth > 0")
                page.screenshot(path=str(OUT / (mode + '-preview.png')))
                page.locator('.el-image-viewer__close').click()
            check(mode + ' 图片查看器', preview)
        page.wait_for_timeout(3500)
        assert page.locator('img').evaluate_all('imgs => imgs.filter(i => i.src.startsWith("data:image") || i.src.startsWith("blob:")).every(i => i.complete && i.naturalWidth > 0)')
        page.screenshot(path=str(OUT / (mode + '-desktop.png')), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        zones.nth(2).scroll_into_view_if_needed()
        def narrow():
            box = zones.nth(2).bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 391, box
            assert zones.nth(2).get_by_text('拖动截图到此处').is_visible()
        check(mode + ' 窄屏上传区可见', narrow)
        page.screenshot(path=str(OUT / (mode + '-mobile.png')), full_page=True)
        results.append({'name':mode+' request log', 'status':'info', 'requests':page.evaluate('window.domesticTest.requests')})
        page.close()
    browser.close()
OUT.joinpath('results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(1 if any(x['status']=='fail' for x in results) else 0)
