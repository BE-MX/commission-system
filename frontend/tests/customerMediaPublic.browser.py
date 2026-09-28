"""External client library grouping and tag filter, with a mocked signed-in session."""
import base64
import json
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright, expect

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')
base = {'id': 1, 'title': 'Spring shoot', 'published_at': '2026-09-01T10:00:00', 'shoot_type': 'product'}
assets = [
    {'id': 11, 'file_name': 'front.png', 'media_type': 'image', 'content_url': '/mock/front.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Purpose', 'tag_value_id': 101, 'value': 'Front'},
              {'dimension_id': 2, 'dimension_label': 'Season', 'tag_value_id': 201, 'value': 'Spring'}]},
    {'id': 12, 'file_name': 'detail.png', 'media_type': 'image', 'content_url': '/mock/detail.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Purpose', 'tag_value_id': 102, 'value': 'Detail'},
              {'dimension_id': 2, 'dimension_label': 'Season', 'tag_value_id': 201, 'value': 'Spring'}]},
]
tag_groups = [
    {'dimension_id': 1, 'label': 'Purpose', 'values': [{'id': 101, 'value': 'Front', 'count': 1}, {'id': 102, 'value': 'Detail', 'count': 1}]},
    {'dimension_id': 2, 'label': 'Season', 'values': [{'id': 201, 'value': 'Spring', 'count': 2}]},
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
    expect(page.locator('.portal-dimension h3')).to_have_text(['Purpose', 'Season'])
    expect(page.locator('.portal-tag-group h4')).to_have_count(3)
    expect(page.locator('.asset-card')).to_have_count(4)
    page.locator('[data-tag="101"]').click()
    expect(page.locator('.asset-card')).to_have_count(2)
    expect(page.locator('.portal-tag-group h4')).to_have_text(['Front 1 files', 'Spring 1 files'])
    assert not errors, errors
    print(json.dumps({'passed': ['dimension grouping', 'tag filtering', 'one asset reused across groups'], 'page_errors': errors}))
    browser.close()
