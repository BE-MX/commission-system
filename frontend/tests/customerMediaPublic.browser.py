"""External client library grouping and tag filter, with a mocked signed-in session."""
import base64
import json
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright, expect

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
base = {'id': 1, 'title': 'Spring shoot', 'published_at': '2026-09-01T10:00:00', 'shoot_type': 'product'}
assets = [
    {'id': 11, 'file_name': 'front.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/front.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 201, 'value': 'Front'}]},
    {'id': 12, 'file_name': 'detail.png', 'file_size': 2097152, 'media_type': 'image', 'content_url': '/mock/detail.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'}]},
]
tag_groups = [
    {'dimension_id': 1, 'name': 'customer_product_type', 'label': 'Product type', 'values': [{'id': 101, 'value': 'Wig', 'count': 2}]},
    {'dimension_id': 2, 'name': 'purpose', 'label': 'Purpose', 'values': [{'id': 201, 'value': 'Front', 'count': 1}, {'id': 202, 'value': 'Detail', 'count': 1}]},
]
errors = []


def api(route):
    parsed = urlsplit(route.request.url)
    if parsed.path == '/api/customer-media/portal/me':
        data = {'customer_id': 'C001', 'customer_name': 'Test Client', 'email': 'client@example.com'}
    elif parsed.path == '/api/customer-media/portal/tags':
        data = tag_groups
    elif parsed.path == '/api/customer-media/portal/library':
        ids = {int(value) for value in parse_qs(parsed.query).get('tag_value_ids', [''])[0].split(',') if value}
        filtered = [asset for asset in assets if not ids or ids.issubset({tag['tag_value_id'] for tag in asset['tags']})]
        data = [{**base, 'assets': filtered}] if filtered else []
    else:
        raise AssertionError(f'Unexpected API: {route.request.url}')
    route.fulfill(json={'code': 200, 'message': 'ok', 'data': data})


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/customer-media/portal/**', api)
    page.route('**/mock/*.png', lambda route: route.fulfill(body=PNG, content_type='image/png'))
    page.goto('http://127.0.0.1:3077/customer-media/')
    page.get_by_role('button', name='Enter Library').click()
    expect(page.locator('.portal-dimension h3')).to_have_text(['Wig 2 / 2 files'])
    expect(page.locator('.group-filter-row')).to_have_count(1)
    expect(page.locator('.asset-card')).to_have_count(2)
    page.locator('[data-group-tag="201"]').click()
    expect(page.locator('.asset-card')).to_have_count(1)
    expect(page.locator('.asset-footer strong')).to_have_text(['front.png'])
    assert page.locator('.asset-preview').first.evaluate('(el) => el.getBoundingClientRect().height') == 200
    page.locator('#select-all').check()
    expect(page.locator('#selected-count')).to_have_text('1 selected across this page')
    assert not errors, errors
    preview_page = browser.new_page(viewport={'width': 1400, 'height': 900})
    preview_page.on('pageerror', lambda error: errors.append(str(error)))
    preview_calls = []
    preview_page.route('**/api/customer-media/portal/**', lambda route: (preview_calls.append(route.request.url), route.abort()))
    preview_page.route('**/mock/*.png', lambda route: route.fulfill(body=PNG, content_type='image/png'))
    preview_page.goto('http://127.0.0.1:3077/')
    preview_page.evaluate("""payload => {
      const iframe = document.createElement('iframe');
      iframe.src = '/customer-media/?preview=1';
      iframe.onload = () => iframe.contentWindow.postMessage({
        type: 'customer-media-preview',
        customer: { customer_id: 'C001', customer_name: 'Test Client' },
        batch: { ...payload.batch, seq: 1, assets: payload.assets },
        dimensions: payload.dimensions,
      }, location.origin);
      document.body.append(iframe);
    }""", {'batch': base, 'assets': [{**assets[0], 'content_url': '/mock/front.png?expires=123&token=abc'}, assets[1]],
            'dimensions': [{'id': group['dimension_id'], 'name': group['name'], 'label': group['label']}
                           for group in tag_groups]})
    preview = preview_page.frame_locator('iframe')
    expect(preview.locator('.asset-card')).to_have_count(2)
    expect(preview.locator('#portal-customer')).to_have_text('Test Client')
    signed_download = preview.locator('.asset-footer a').first.get_attribute('href')
    assert signed_download.count('?') == 1 and 'token=abc' in signed_download and 'download=true' in signed_download
    assert preview_calls == [], preview_calls
    assert not errors, errors
    print(json.dumps({'passed': ['product grouping', 'group tag filtering', '200px thumbnail and filename',
                                 'same-origin draft preview without portal API'], 'page_errors': errors}))
    browser.close()
