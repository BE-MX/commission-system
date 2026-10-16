"""Unified media upload with customer labels. Run with Vite at 127.0.0.1:3077."""
import base64
import json
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
dimensions = [{'id': 3, 'name': 'customer_general', 'label': '客户标签', 'is_single_select': 0,
               'is_visible': 1, 'is_managed': 0, 'tag_scope': 'customer',
               'values': [{'id': 11, 'value': '婚纱'}]}]
customer_tags = [{'dimension_id': 3, 'dimension_label': '客户标签', 'tag_value_id': 11, 'value': '婚纱'},
                 {'dimension_id': 3, 'dimension_label': '客户标签', 'tag_value_id': 12, 'value': '旧标签'}]
batch = {'id': 1, 'task_id': 1, 'customer_name': '测试客户', 'customer_id': 'C001',
         'status': 'draft', 'lock_version': 1, 'directories': [], 'assets': []}
uploads, errors, created = [], [], []


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
    elif request.method == 'POST' and path.startswith('/customers/C001/tag-values?'):
        payload = request.post_data_json
        assert payload['dimension_id'] == 3
        created.append(payload['value'])
        value_id = 20 + len(created)
        customer_tags.append({'dimension_id': 3, 'dimension_label': '客户标签',
                              'tag_value_id': value_id, 'value': payload['value']})
        respond(route, {'id': value_id, 'value': payload['value'], 'dimension_id': 3})
    elif request.method == 'POST' and path == '/batches/1/assets':
        body = request.post_data_buffer.decode('utf-8', errors='replace')
        uploads.append(body)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.post_data_buffer)
        parts = {part.get_param('name', header='content-disposition'): part for part in message.iter_parts()}
        tags = json.loads(parts['tags_json'].get_content())
        tag_ids = {value for dim in tags for value in dim['tag_value_ids']}
        batch['assets'].append({'id': 500 + len(uploads), 'file_name': 'a.png', 'media_type': 'image',
                                'file_size': 100, 'directory_id': None,
                                'tags': [tag for tag in customer_tags if tag['tag_value_id'] in tag_ids],
                                'content_url': '/api/customer-media/assets/501/content?expires=100&token=demo'})
        respond(route, batch)
    else:
        raise AssertionError(f'Unexpected API: {request.method} {request.url}')


def drop_folders(page, roots):
    """Synthetic FileSystemEntry tree, exercising the actual drop capture handler."""
    page.locator('.upload-drop').evaluate('''(element, {roots, png}) => {
      const entry = spec => {
        if (!spec.children) return {isFile: true, file: resolve => resolve(
          new File([Uint8Array.from(atob(png), c => c.charCodeAt(0))], spec.name, {type: 'image/png'}))}
        return {name: spec.name, isDirectory: true, createReader: () => {
          let read = false
          return {readEntries: resolve => setTimeout(() => {
            const children = read ? [] : spec.children.map(entry)
            read = true
            resolve(children)
          }, 0)}
        }}
      }
      const entries = roots.map(entry)
      const event = new Event('drop', {bubbles: true, cancelable: true})
      Object.defineProperty(event, 'dataTransfer', {value: {
        items: entries.map(item => ({webkitGetAsEntry: () => item})), files: []}})
      element.dispatchEvent(event)
    }''', {'roots': roots, 'png': base64.b64encode(PNG).decode()})


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
    expect(dialog.get_by_role('button', name='选择文件夹')).to_be_enabled()
    # No manual selection is needed; subfolder names do not become labels.
    drop_folders(page, [{'name': ' 婚 纱 ', 'children': [
        {'name': '忽略子目录', 'children': [{'name': 'drop.png'}]}]}])
    expect(dialog.locator('.manifest-row')).to_have_count(1)
    expect(dialog.locator('.manifest-row').get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name='婚纱', exact=True)).to_have_attribute('aria-pressed', 'true')
    assert not created
    dialog.get_by_role('button', name='清空清单').click()
    dialog.get_by_role('button', name='旧标签', exact=True).click()

    folder = Path(temp) / '婚 纱' / '二级目录'
    folder.mkdir(parents=True)
    (folder / 'a.png').write_bytes(PNG)
    dialog.locator('input[webkitdirectory]').set_input_files(str(Path(temp) / '婚 纱'))
    row = dialog.locator('.manifest-row', has_text='婚 纱/二级目录/a.png')
    expect(row).to_be_visible()
    expect(row.get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name='旧标签', exact=True)).to_have_attribute('aria-pressed', 'false')
    expect(dialog.get_by_role('button', name='婚纱', exact=True)).to_have_attribute('aria-pressed', 'true')
    dialog.get_by_role('button', name='开始上传（1）').click()
    expect(dialog.locator('.manifest-row')).to_have_count(0)
    assert len(uploads) == 1
    assert 'name="tags_json"\r\n\r\n[{"dimension_id":3,"tag_value_ids":[11]}]' in uploads[0]
    assert 'name="directory_name"' not in uploads[0]
    assert 'name="directory_id"' not in uploads[0]
    # Cancelling or dismissing a new-label confirmation changes nothing.
    for action in ['取消', 'Close this dialog']:
        drop_folders(page, [{'name': ' 取 消 ', 'children': [{'name': 'cancel.png'}]}])
        prompt = page.get_by_role('dialog', name='发现新标签').last
        expect(prompt.get_by_text('发现新标签，是否自动创建并选中？', exact=False)).to_be_visible()
        expect(dialog.get_by_role('button', name='选择文件夹')).to_be_disabled()
        prompt.get_by_role('button', name=action, exact=True).click()
        expect(prompt).to_be_hidden()
        expect(dialog.locator('.manifest-row')).to_have_count(0)
        expect(dialog.get_by_role('button', name='选择文件夹')).to_be_enabled()
        expect(dialog.get_by_role('button', name='婚纱', exact=True)).to_have_attribute('aria-pressed', 'true')
        assert not created
    # Different roots get separate labels; nested folders never prompt.
    drop_folders(page, [
        {'name': '外 景', 'children': [{'name': '婚纱', 'children': [{'name': 'new.png'}]}]},
        {'name': '婚纱', 'children': [{'name': 'existing.png'}]},
    ])
    prompt = page.get_by_role('dialog', name='发现新标签').last
    expect(prompt.get_by_text('标签名称：外景', exact=False)).to_be_visible()
    prompt.get_by_role('button', name='创建并选中').click()
    expect(dialog.locator('.manifest-row')).to_have_count(2)
    assert created == ['外景']
    expect(dialog.locator('.manifest-row', has_text='外 景/婚纱/new.png')
           .get_by_text('客户标签：外景', exact=True)).to_be_visible()
    expect(dialog.locator('.manifest-row', has_text='婚纱/existing.png')
           .get_by_text('客户标签：婚纱', exact=True)).to_be_visible()
    dialog.get_by_role('button', name='开始上传（2）').click()
    expect(dialog.locator('.manifest-row')).to_have_count(0)
    assert len(uploads) == 3
    assert 'name="tags_json"\r\n\r\n[{"dimension_id":3,"tag_value_ids":[21]}]' in uploads[1]
    assert 'name="tags_json"\r\n\r\n[{"dimension_id":3,"tag_value_ids":[11]}]' in uploads[2]
    dialog.get_by_role('button', name='Close').click()
    expect(page.locator('.asset-dimension h4', has_text='未设置产品类型')).to_be_visible()
    expect(page.locator('.asset-tag-group h5')).to_have_count(0)
    page.get_by_role('button', name='客户效果预览').click()
    preview = page.frame_locator('iframe.customer-effect-frame')
    expect(preview.locator('#app')).to_be_visible()
    expect(preview.locator('#login')).to_be_hidden()
    expect(preview.locator('.asset-card')).to_have_count(3)
    dimensions.append({'id': 4, 'name': 'customer_product_type', 'label': 'Product type',
                       'values': [{'id': 41, 'value': 'Wig'}, {'id': 42, 'value': 'Cap'}]})
    batch['assets'] = [
        {'id': 601, 'file_name': 'wig.png', 'media_type': 'image', 'file_size': 100, 'directory_id': None,
         'content_url': '/api/customer-media/assets/601/content?expires=100&token=demo',
         'tags': [{'dimension_id': 4, 'dimension_label': 'Product type', 'tag_value_id': 41, 'value': 'Wig'}]},
        {'id': 602, 'file_name': 'cap.png', 'media_type': 'image', 'file_size': 100, 'directory_id': None,
         'content_url': '/api/customer-media/assets/602/content?expires=100&token=demo',
         'tags': [{'dimension_id': 4, 'dimension_label': 'Product type', 'tag_value_id': 42, 'value': 'Cap'}]},
    ]
    page.reload()
    product_filter = page.get_by_role('group', name='按Product type筛选')
    expect(product_filter.get_by_role('button', name='Wig')).to_be_visible()
    expect(page.locator('.asset-dimension')).to_have_count(2)
    product_filter.get_by_role('button', name='Cap').click()
    expect(page.locator('.asset-dimension')).to_have_count(1)
    expect(page.locator('.asset-info strong')).to_have_text(['cap.png'])
    product_filter.get_by_role('button', name='全部').click()
    expect(page.locator('.asset-dimension')).to_have_count(2)
    assert not errors, errors
    print(json.dumps({'passed': ['folder drop without prior selection', 'top folder whitespace normalization',
                                 'previous labels replaced', 'new-label cancel and close',
                                 'confirmed customer tag creation', 'separate root folder labels',
                                 'upload tag payloads associated', 'missing row headings hidden',
                                 'draft preview without portal login', 'batch product type filter'],
                      'page_errors': errors}, ensure_ascii=False))
    browser.close()
