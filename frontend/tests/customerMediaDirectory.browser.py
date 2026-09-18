"""Run with Vite at 127.0.0.1:3077; all media APIs are mocked, no backend needed."""
import base64
import json
import tempfile
import sys
from urllib.parse import quote
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3077'
FIXTURE_URL = BASE_URL + '/tests/fixtures/customer-media-qa.html'

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
batch = {'id': 1, 'task_id': 1, 'status': 'draft', 'directories': [
    {'id': 7, 'name': '产品图', 'asset_count': 1, 'total_asset_count': 1}], 'assets': [
    {'id': 1, 'directory_id': 7, 'file_name': 'photo.png', 'media_type': 'image', 'file_size': 100,
     'content_url': '/api/customer-media/assets/1/content?expires=100&token=demo'}]}
uploads, deletes, errors = [], [], []


def api(route):
    request = route.request
    if request.method == 'GET' and '/content?' in request.url:
        route.fulfill(body=PNG, content_type='image/png')
        return
    if request.method == 'POST' and request.url.endswith('/assets'):
        uploads.append(request.post_data_buffer.decode('utf-8', errors='replace'))
    elif request.method == 'DELETE':
        deletes.append(request.url)
        batch['directories'] = []
        batch['assets'] = []
    else:
        raise AssertionError(f'Unexpected API: {request.method} {request.url}')
    route.fulfill(json={'code': 200, 'message': 'ok', 'data': batch})


with sync_playwright() as p, tempfile.TemporaryDirectory() as temp:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/customer-media/**', api)
    # Check actual clipping, not only Playwright's visibility: overflowing buttons
    # still have a bounding box and click() can silently scroll them into view.
    for width in [1440, 900, 800]:
        page.set_viewport_size({'width': width, 'height': 1000})
        for name in ['产品图', '客户拍摄素材目录' * 16, 'CustomerMediaFolder' * 7]:
            page.goto(FIXTURE_URL + '?name=' + quote(name))
            button = page.get_by_role('button', name='删除目录 ' + name, exact=True)
            expect(button).to_be_visible()
            bounds = button.evaluate("""el => {
                const button = el.getBoundingClientRect();
                const list = el.closest('.dir-list').getBoundingClientRect();
                const icon = el.querySelector('svg').getBoundingClientRect();
                return {right: button.right, listRight: list.right, iconWidth: icon.width};
            }""")
            assert bounds['right'] <= bounds['listRight'] + 1, (width, name, bounds)
            assert bounds['iconWidth'] >= 12, bounds
    page.goto(FIXTURE_URL + '?readonly')
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_role('button', name='删除目录 产品图', exact=True)).to_have_count(0)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto(FIXTURE_URL)
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('dialog')).to_be_visible()
    photo = page.locator('.asset-card img')
    expect(photo).to_be_visible()
    assert photo.evaluate('(img) => img.complete && img.naturalWidth > 0')
    photo.click()
    viewer = page.locator('.el-image-viewer__wrapper')
    expect(viewer).to_be_visible()
    assert viewer.evaluate('(el) => !el.closest(".el-dialog")')
    page.locator('.el-image-viewer__close').click()
    page.locator('.dir-row').filter(has_text='产品图').click()
    folder = Path(temp) / '新拍摄'
    folder.mkdir()
    (folder / 'test.png').write_bytes(PNG)
    page.locator('input[webkitdirectory]').set_input_files(str(folder))
    expect(page.locator('.el-progress--line')).to_have_count(1)
    page.wait_for_function('!document.querySelector(".upload-drop .el-button").disabled')
    assert len(uploads) == 1
    assert 'name="directory_name"\r\n\r\n新拍摄' in uploads[0]
    assert 'name="directory_id"' not in uploads[0]
    page.get_by_role('button', name='删除目录 产品图', exact=True).click()
    expect(page.get_by_text('删除「产品图」及其中全部', exact=False)).to_be_visible()
    page.get_by_role('button', name='Cancel', exact=True).click()
    assert not deletes
    page.get_by_role('button', name='删除目录 产品图', exact=True).click()
    page.get_by_role('button', name='删除目录及素材', exact=True).click()
    expect(page.get_by_role('button', name='删除目录 产品图', exact=True)).to_have_count(0)
    expect(page.locator('.asset-card')).to_have_count(0)
    assert len(deletes) == 1 and deletes[0].endswith('/batches/1/directories/7')
    assert not errors, errors
    print(json.dumps({'passed': ['directory actions fit short/long names at 3 widths', 'readonly hides deletion', 'image rendered', 'lightbox teleported and closed', 'folder picker name overrides selection', 'delete cancellation', 'confirmed delete refreshes directory and assets'], 'page_errors': errors}))
    browser.close()
