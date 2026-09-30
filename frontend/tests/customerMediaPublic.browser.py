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
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 201, 'value': 'Front'},
              {'dimension_id': 3, 'dimension_label': 'Color names', 'tag_value_id': 301, 'value': 'Ash'},
              {'dimension_id': 4, 'dimension_label': 'Textures type', 'tag_value_id': 401, 'value': 'Straight'}]},
    {'id': 12, 'file_name': 'detail.png', 'file_size': 2097152, 'media_type': 'image', 'content_url': '/mock/detail.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'},
              {'dimension_id': 3, 'dimension_label': 'Color names', 'tag_value_id': 301, 'value': 'Ash'},
              {'dimension_id': 4, 'dimension_label': 'Textures type', 'tag_value_id': 402, 'value': 'Wavy'}]},
    {'id': 13, 'file_name': 'side.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/side.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'},
              {'dimension_id': 3, 'dimension_label': 'Color names', 'tag_value_id': 301, 'value': 'Ash'},
              {'dimension_id': 4, 'dimension_label': 'Textures type', 'tag_value_id': 401, 'value': 'Straight'}]},
    {'id': 14, 'file_name': 'untagged.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/untagged.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'}]},
    {'id': 15, 'file_name': 'color-only.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/color-only.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'},
              {'dimension_id': 3, 'dimension_label': 'Color names', 'tag_value_id': 301, 'value': 'Ash'}]},
    {'id': 16, 'file_name': 'texture-only.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/texture-only.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 101, 'value': 'Wig'},
              {'dimension_id': 2, 'dimension_label': 'Purpose', 'tag_value_id': 202, 'value': 'Detail'},
              {'dimension_id': 4, 'dimension_label': 'Textures type', 'tag_value_id': 402, 'value': 'Wavy'}]},
    {'id': 17, 'file_name': 'cap.png', 'file_size': 1048576, 'media_type': 'image', 'content_url': '/mock/cap.png',
     'tags': [{'dimension_id': 1, 'dimension_label': 'Product type', 'tag_value_id': 102, 'value': 'Cap'}]},
]
tag_groups = [
    {'dimension_id': 1, 'name': 'customer_product_type', 'label': 'Product type', 'values': [{'id': 101, 'value': 'Wig', 'count': 6}, {'id': 102, 'value': 'Cap', 'count': 1}]},
    {'dimension_id': 2, 'name': 'purpose', 'label': 'Purpose', 'values': [{'id': 201, 'value': 'Front', 'count': 1}, {'id': 202, 'value': 'Detail', 'count': 5}]},
    {'dimension_id': 3, 'name': 'color_names', 'label': 'Color names', 'values': [{'id': 301, 'value': 'Ash', 'count': 4}]},
    {'dimension_id': 4, 'name': 'textures_type', 'label': 'Textures type', 'values': [{'id': 401, 'value': 'Straight', 'count': 2}, {'id': 402, 'value': 'Wavy', 'count': 2}]},
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


def assert_row_heading_hierarchy(page):
    first_row = page.locator('.portal-tag-group').first
    expect(first_row.locator('.row-label')).to_have_text(['Straight', 'Ash'])
    product_size = page.locator('.portal-dimension h3').first.evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)')
    for label in first_row.locator('.row-label').all():
        style = label.evaluate('(el) => ({size: parseFloat(getComputedStyle(el).fontSize), weight: Number(getComputedStyle(el).fontWeight)})')
        assert style == {'size': product_size - 2, 'weight': 800}, style
    count_size = first_row.locator('.row-count').evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)')
    assert count_size < product_size - 2


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/customer-media/portal/**', api)
    page.route('**/mock/*.png', lambda route: route.fulfill(body=PNG, content_type='image/png'))
    page.goto('http://127.0.0.1:3077/customer-media/')
    page.get_by_role('button', name='Enter Library').click()
    expect(page.locator('.portal-dimension h3')).to_have_text(['Wig 6 / 6 files', 'Cap 1 / 1 files'])
    expect(page.locator('.group-filter-row')).to_have_count(3)
    expect(page.locator('.portal-tag-group')).to_have_count(6)
    expect(page.locator('.portal-tag-group h4')).to_have_count(4)
    assert_row_heading_hierarchy(page)
    expect(page.locator('.portal-tag-group').first.locator('.asset-card')).to_have_count(2)
    expect(page.locator('.portal-tag-group').first.locator('.asset-footer strong')).to_have_text(['front.png', 'side.png'])
    expect(page.locator('.portal-tag-group').nth(2).locator('h4')).to_have_count(0)
    expect(page.locator('.asset-card')).to_have_count(7)
    assert '未设置' not in ' '.join(page.locator('.portal-tag-group h4').all_text_contents())
    page.locator('#product-filters [data-product="102"]').click()
    expect(page.locator('.portal-dimension h3')).to_have_text(['Cap 1 / 1 files'])
    expect(page.locator('.asset-footer strong')).to_have_text(['cap.png'])
    page.locator('#product-filters [data-product="101"]').click()
    expect(page.locator('.asset-card')).to_have_count(7)
    page.locator('#product-filters [data-product="all"]').click()
    expect(page.locator('.asset-card')).to_have_count(7)
    page.locator('#product-filters [data-product="101"]').click()
    page.locator('[data-group-tag="201"]').click()
    expect(page.locator('.asset-card')).to_have_count(1)
    expect(page.locator('.asset-footer strong')).to_have_text(['front.png'])
    expect(page.locator('.portal-tag-group')).to_have_count(1)
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
    }""", {'batch': base, 'assets': [{**assets[0], 'content_url': '/mock/front.png?expires=123&token=abc'}, *assets[1:]],
            'dimensions': [{'id': group['dimension_id'], 'name': group['name'], 'label': group['label']}
                           for group in tag_groups]})
    preview = preview_page.frame_locator('iframe')
    expect(preview.locator('.asset-card')).to_have_count(7)
    expect(preview.locator('.portal-tag-group')).to_have_count(6)
    expect(preview.locator('.portal-tag-group h4')).to_have_count(4)
    expect(preview.locator('#portal-customer')).to_have_text('Test Client')
    signed_download = preview.locator('.asset-footer a').first.get_attribute('href')
    assert signed_download.count('?') == 1 and 'token=abc' in signed_download and 'download=true' in signed_download
    preview.locator('#product-filters [data-product="102"]').click()
    expect(preview.locator('.asset-footer strong')).to_have_text(['cap.png'])
    assert preview_calls == [], preview_calls
    assert not errors, errors

    internal_page = browser.new_page(viewport={'width': 1400, 'height': 900})
    internal_page.on('pageerror', lambda error: errors.append(str(error)))
    internal_page.add_init_script('window.customerMediaQaData = ' + json.dumps({
        'customer': {'customer_id': 'C001', 'customer_name': 'Test Client', 'status': 'ready',
                     'asset_count': 7, 'image_count': 7, 'video_count': 0, 'published_batch_count': 1},
        'batches': [{**base, 'assets': assets}],
        'tagDimensions': [{'id': group['dimension_id'], 'name': group['name'], 'label': group['label']}
                          for group in tag_groups],
    }))
    internal_page.route('**/mock/*.png', lambda route: route.fulfill(body=PNG, content_type='image/png'))
    internal_page.goto('http://127.0.0.1:3077/tests/fixtures/customer-media-client-library-qa.html')
    expect(internal_page.locator('.portal-tag-group')).to_have_count(6)
    expect(internal_page.locator('.portal-tag-group h4')).to_have_count(4)
    assert_row_heading_hierarchy(internal_page)
    expect(internal_page.locator('.portal-tag-group').first.locator('.asset-card')).to_have_count(2)
    expect(internal_page.locator('.portal-tag-group').first.locator('.asset-footer strong')).to_have_text(['front.png', 'side.png'])
    expect(internal_page.locator('.portal-tag-group').nth(2).locator('h4')).to_have_count(0)
    expect(internal_page.locator('.asset-card')).to_have_count(7)
    internal_page.get_by_role('group', name='按Product type筛选').get_by_role('button', name='Cap').click()
    expect(internal_page.locator('.asset-footer strong')).to_have_text(['cap.png'])
    internal_page.get_by_role('group', name='按Product type筛选').get_by_role('button', name='All').click()
    expect(internal_page.locator('.asset-card')).to_have_count(7)
    internal_page.get_by_role('group', name='按Product type筛选').get_by_role('button', name='Wig').click()
    internal_page.get_by_role('button', name='Front', exact=True).click()
    expect(internal_page.locator('.portal-tag-group')).to_have_count(1)
    expect(internal_page.locator('.asset-footer strong')).to_have_text(['front.png'])
    assert not errors, errors
    assets[0]['tags'].append({'dimension_id': 1, 'dimension_label': 'Product type',
                              'tag_value_id': 102, 'value': 'Cap'})
    page.reload()
    page.get_by_role('button', name='Enter Library').click()
    page.locator('#product-filters [data-product="101"]').click()
    expect(page.locator('.portal-dimension h3')).to_have_text(['Wig 6 / 6 files'])
    expect(page.locator('.asset-card')).to_have_count(6)

    print(json.dumps({'passed': ['product grouping', 'top product type filters in signed-in, internal and draft views', 'color and texture rows in both client views',
                                 'group tag filtering', '200px thumbnail and filename',
                                 'same-origin draft preview without portal API'], 'page_errors': errors}))
    browser.close()
