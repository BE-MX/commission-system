"""Unified media upload with customer labels. Run with Vite at 127.0.0.1:3077."""
import base64
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
dimensions = [{'id': 3, 'name': 'customer_general', 'label': '客户标签', 'is_single_select': 0,
               'is_visible': 1, 'is_managed': 0, 'tag_scope': 'customer',
               'values': [{'id': 11, 'value': '婚纱'}]}]
customer_tags = [{'dimension_id': 3, 'dimension_label': '客户标签', 'tag_value_id': 11, 'value': '婚纱'}]
batch = {'id': 1, 'task_id': 1, 'customer_name': '测试客户', 'customer_id': 'C001',
         'status': 'draft', 'lock_version': 1, 'directories': [], 'assets': []}
uploads, errors = [], []


def respond(route, data):
    route.fulfill(json={'code': 200, 'message': 'ok', 'data': data})


def api(route):
    request = route.request
    path = request.url.split('/api/customer-media', 1)[-1]
    if request.method == 'GET' and '/content?' in request.url:
        route.fulfill(body=PNG, content_type='image/png')
    elif request.method == 'GET' and path == '/tasks/1/batch':
        respond(route, batch)
    elif request.method == 'GET' and path == '/tasks/1/customer-tags':
        respond(route, customer_tags)
    elif request.method == 'GET' and path == '/tags/dimensions':
        respond(route, dimensions)
    elif request.method == 'POST' and path == '/batches/1/assets':
        body = request.post_data_buffer.decode('utf-8', errors='replace')
        uploads.append(body)
        batch['assets'].append({'id': 501, 'file_name': 'a.png', 'media_type': 'image',
                                'file_size': 100, 'directory_id': None, 'tags': customer_tags,
                                'content_url': '/api/customer-media/assets/501/content?expires=100&token=demo'})
        respond(route, batch)
    else:
        raise AssertionError(f'Unexpected API: {request.method} {request.url}')


with sync_playwright() as p, tempfile.TemporaryDirectory() as temp:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/customer-media/**', api)
    page.goto('http://127.0.0.1:3077/tests/fixtures/customer-media-workspace-qa.html')
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('heading', name='客户拍摄素材')).to_be_visible()
    page.get_by_role('button', name='上传素材').click()
    dialog = page.get_by_role('dialog', name='上传客户拍摄素材')
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text('婚纱', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name='选择文件夹')).to_be_disabled()
    dialog.get_by_role('button', name='婚纱').click()
    expect(dialog.get_by_role('button', name='选择文件夹')).to_be_enabled()

    folder = Path(temp) / '随意文件夹' / '二级目录'
    folder.mkdir(parents=True)
    (folder / 'a.png').write_bytes(PNG)
    dialog.locator('input[webkitdirectory]').set_input_files(str(Path(temp) / '随意文件夹'))
    row = dialog.locator('.manifest-row', has_text='随意文件夹/二级目录/a.png')
    expect(row).to_be_visible()
    expect(row.get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    dialog.get_by_role('button', name='开始上传（1）').click()
    expect(dialog.locator('.manifest-row')).to_have_count(0)
    assert len(uploads) == 1
    assert 'name="tags_json"\r\n\r\n[{"dimension_id":3,"tag_value_ids":[11]}]' in uploads[0]
    assert 'name="directory_name"' not in uploads[0]
    assert 'name="directory_id"' not in uploads[0]
    dialog.get_by_role('button', name='Close').click()
    expect(page.locator('.asset-dimension h4', has_text='客户标签')).to_be_visible()
    expect(page.locator('.asset-tag-group h5', has_text='婚纱')).to_be_visible()
    assert not errors, errors
    print(json.dumps({'passed': ['label required', 'folder flattened without name mapping',
                                 'upload tags associated', 'asset grouped by dimension'],
                      'page_errors': errors}, ensure_ascii=False))
    browser.close()
