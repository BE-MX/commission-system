"""Workspace upload flow with customer tags. Run with Vite at 127.0.0.1:3077; all media APIs mocked."""
import base64
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
dimensions = [{'id': 3, 'name': 'customer_general', 'label': '客户标签', 'is_single_select': 0,
               'is_required': 0, 'is_visible': 1, 'is_managed': 0, 'tag_scope': 'customer',
               'values': [{'id': 11, 'value': '婚纱'}]}]
batch = {'id': 1, 'task_id': 1, 'customer_name': '测试客户', 'customer_id': 'C001',
         'status': 'draft', 'lock_version': 1, 'directories': [], 'assets': []}
calls = {'validate': [], 'resolve': [], 'uploads': [], 'patches': []}
errors = []


def respond(route, data):
    route.fulfill(json={'code': 200, 'message': 'ok', 'data': data})


def api(route):
    request = route.request
    url = request.url
    path = url.split('/api/customer-media', 1)[-1]
    if request.method == 'GET' and '/content?' in url:
        route.fulfill(body=PNG, content_type='image/png')
    elif request.method == 'GET' and path.startswith('/tasks/'):
        respond(route, batch)
    elif request.method == 'GET' and path == '/tags/dimensions':
        respond(route, dimensions)
    elif request.method == 'POST' and path == '/tags/validate':
        names = json.loads(request.post_data)['tag_names']
        calls['validate'].append(names)
        respond(route, {
            'matched': [{'tag_name': '婚纱', 'dimension_id': 3, 'dimension_label': '客户标签',
                         'tag_value_id': 11, 'original_value': '婚纱'}] if '婚纱' in names else [],
            'suggested': [], 'ambiguous': [],
            'missing': [name for name in names if name != '婚纱'],
        })
    elif request.method == 'POST' and path == '/tags/resolve':
        creates = json.loads(request.post_data)['auto_create_tags']
        calls['resolve'].append(creates)
        respond(route, {'tag_mapping': {
            name: {'dimension_id': dim_id, 'tag_value_id': 12, 'created': True}
            for name, dim_id in creates.items()}})
    elif request.method == 'POST' and path == '/batches/1/assets':
        body = request.post_data_buffer.decode('utf-8', errors='replace')
        calls['uploads'].append(body)
        directory = None
        if 'name="directory_name"\r\n\r\n' in body:
            name = body.split('name="directory_name"\r\n\r\n', 1)[1].split('\r\n', 1)[0]
            directory = next((d for d in batch['directories'] if d['name'] == name), None)
            if directory is None:
                directory = {'id': 7, 'name': name, 'asset_count': 0}
                batch['directories'].append(directory)
        asset = {'id': 501 + len(batch['assets']), 'file_name': 'a.png', 'media_type': 'image',
                 'file_size': 100, 'directory_id': directory['id'] if directory else None,
                 'content_url': '/api/customer-media/assets/501/content?expires=100&token=demo'}
        batch['assets'].append(asset)
        respond(route, batch)
    elif request.method == 'PATCH' and path == '/batches/1/assets/501/tags':
        calls['patches'].append(json.loads(request.post_data))
        respond(route, batch['assets'][0])
    else:
        raise AssertionError(f'Unexpected API: {request.method} {url}')


with sync_playwright() as p, tempfile.TemporaryDirectory() as temp:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/customer-media/**', api)
    page.goto('http://127.0.0.1:3077/tests/fixtures/customer-media-workspace-qa.html')
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('heading', name='客户拍摄素材')).to_be_visible()

    folder = Path(temp) / '婚纱' / '外景'
    folder.mkdir(parents=True)
    (folder / 'a.png').write_bytes(PNG)
    page.locator('input[webkitdirectory]').set_input_files(str(Path(temp) / '婚纱'))

    # 确认弹窗：婚纱命中标签库，外景默认勾选自动新建
    dialog = page.get_by_role('dialog', name='确认文件夹标签')
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    expect(dialog.locator('.resolution-row')).to_have_count(1)
    dialog.get_by_role('button', name='确认并继续').click()
    expect(dialog).to_be_hidden()
    assert calls['validate'] == [['婚纱', '外景']], calls['validate']
    assert calls['resolve'] == [{'外景': 3}], calls['resolve']

    # 清单行：目录 + 两个文件夹标签 chip
    row = page.locator('.manifest-row', has_text='婚纱/外景/a.png')
    expect(row).to_be_visible()
    expect(row.get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    expect(row.get_by_text('客户标签：外景', exact=True)).to_be_visible()

    page.get_by_role('button', name='开始上传（1）').click()
    expect(row.get_by_role('button', name='编辑标签')).to_be_visible()
    assert len(calls['uploads']) == 1
    assert 'name="directory_name"\r\n\r\n婚纱' in calls['uploads'][0]
    assert 'name="tags_json"\r\n\r\n[{"dimension_id":3,"tag_value_ids":[11,12]}]' in calls['uploads'][0], calls['uploads'][0]

    # 已上传图片继续编辑标签：保存走 PATCH 全量覆盖
    row.get_by_role('button', name='编辑标签').click()
    picker = page.get_by_role('dialog', name='编辑标签 · a.png')
    expect(picker).to_be_visible()
    expect(picker.get_by_role('checkbox', name='外景')).to_be_checked()
    picker.get_by_role('button', name='保存').click()
    expect(picker).to_be_hidden()
    assert calls['patches'] == [{'tags': [{'dimension_id': 3, 'tag_value_ids': [11, 12]}]}], calls['patches']

    assert not errors, errors
    print(json.dumps({'passed': ['validate + confirm dialog', 'resolve auto-create', 'manifest chips',
                                 'upload with tags_json + directory', 'edit tags PATCH'],
                      'page_errors': errors}, ensure_ascii=False))
    browser.close()
