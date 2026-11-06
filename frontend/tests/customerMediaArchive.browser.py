"""Run from the repository root: python frontend/tests/customerMediaArchive.browser.py.

Exercises the real customer portal in Chrome with a loopback-only fixture server.
The ZIP bytes are a fixture; backend archive paths are tested separately.
"""
import base64
import io
import json
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'frontend' / 'public'
EVIDENCE = ROOT / 'tmp' / 'media-zip-browser'
EVIDENCE.mkdir(parents=True, exist_ok=True)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aNu8AAAAASUVORK5CYII=')


def tag(dimension, label, value_id, value):
    return {'dimension_id': dimension, 'dimension_label': label, 'tag_value_id': value_id, 'value': value}


def asset(asset_id, name, tags):
    return {'id': asset_id, 'file_name': name, 'file_size': 1024, 'media_type': 'image',
            'content_url': f'/mock/{name}?expires=123&token=fixture', 'tags': tags}


assets = [
    asset(11, 'front.png', [tag(1, 'Product type', 101, 'Wig'), tag(3, 'Color names', 301, 'Ash'),
                            tag(3, 'Color names', 302, 'Blonde'), tag(4, 'Textures type', 401, 'Straight'),
                            tag(4, 'Textures type', 402, 'Wavy')]),
    asset(12, 'side.png', [tag(1, 'Product type', 101, 'Wig'), tag(3, 'Color names', 301, 'Ash'),
                           tag(4, 'Textures type', 401, 'Straight')]),
    asset(13, 'front-detail.png', [tag(1, 'Product type', 102, 'Cap'), tag(3, 'Color names', 302, 'Blonde')]),
]
groups = [
    {'dimension_id': 1, 'name': 'customer_product_type', 'label': 'Product type', 'values': []},
    {'dimension_id': 3, 'name': 'color_names', 'label': 'Color names', 'values': []},
    {'dimension_id': 4, 'name': 'textures_type', 'label': 'Textures type', 'values': []},
]
batches = [{'id': 1, 'title': 'Fixture batch', 'published_at': '2026-11-01T10:00:00', 'assets': assets}]

buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('fixture/front.png', b'fixture front')
    archive.writestr('fixture/side.png', b'fixture side')
ZIP_BYTES = buffer.getvalue()
state = {'requests': [], 'mode': 'ok'}
request_entered = threading.Event()
release_request = threading.Event()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/mock/'):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
            return
        data = {'/api/customer-media/portal/me': {'customer_id': 'fixture', 'customer_name': 'Fixture Client'},
                '/api/customer-media/portal/tags': groups,
                '/api/customer-media/portal/library': batches}
        if path in data:
            return self.send_json({'code': 200, 'data': data[path]})
        if path.startswith('/api/'):
            return self.send_json({'detail': 'Unexpected fixture endpoint'}, 404)
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/api/customer-media/portal/downloads/zip':
            return self.send_json({'detail': 'Unexpected fixture endpoint'}, 404)
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        state['requests'].append({'method': self.command, 'body': body})
        request_entered.set()
        if state['mode'] == 'blocked':
            if not release_request.wait(15):
                return self.send_json({'detail': 'Fixture timed out'}, 500)
        if state['mode'] == 'fail':
            return self.send_json({'detail': 'Fixture ZIP failure. Please retry.'}, 500)
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(len(ZIP_BYTES)))
        self.end_headers()
        self.wfile.write(ZIP_BYTES)


def open_library(page, url):
    page.goto(url)
    page.get_by_role('button', name='Enter Library').click()
    expect(page.locator('#app')).to_be_visible()
    expect(page.locator('.asset-card')).to_have_count(6)


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/customer-media/'
    errors = []
    downloads = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            context = browser.new_context(viewport={'width': 1400, 'height': 900}, accept_downloads=True)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('download', lambda download: downloads.append(download.suggested_filename))
            # This guard ensures the real browser cannot reach production or external hosts.
            page.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).hostname == '127.0.0.1' else route.abort())
            open_library(page, url)
            expect(page.locator('[data-card="11"]')).to_have_count(4)
            headings = page.locator('.portal-tag-group h4').all_text_contents()
            for texture in ('Straight', 'Wavy'):
                for color in ('Ash', 'Blonde'):
                    assert any(texture in heading and color in heading for heading in headings), headings
            original = page.locator('[data-card="11"] .asset-footer a').first.get_attribute('href')
            assert original.endswith('/mock/front.png?expires=123&token=fixture&download=true'), original
            page.screenshot(path=str(EVIDENCE / 'multi-tag-groups.png'), full_page=True)

            # One duplicate card selection plus another asset becomes one archive request.
            page.locator('[data-select="11"]').first.check()
            page.locator('[data-select="12"]').first.check()
            expect(page.locator('#selected-count')).to_have_text('2 selected across this page')
            state['mode'] = 'blocked'
            request_entered.clear()
            release_request.clear()
            page.locator('#download-selected').click()
            assert request_entered.wait(5), 'ZIP request was not sent'
            expect(page.locator('#download-selected')).to_be_disabled()
            expect(page.locator('#download-selected')).to_have_text('Preparing ZIP…')
            # Rerendering while the request is pending must keep the guard in force.
            page.locator('#search').fill('front')
            expect(page.locator('#download-selected')).to_be_disabled()
            assert len(state['requests']) == 1, state['requests']
            page.screenshot(path=str(EVIDENCE / 'preparing.png'), full_page=True)
            with page.expect_download() as received:
                release_request.set()
            download = received.value
            assert download.suggested_filename == 'LeShine-materials.zip', download.suggested_filename
            target = EVIDENCE / 'fixture-download.zip'
            download.save_as(str(target))
            with zipfile.ZipFile(target) as archive:
                assert set(archive.namelist()) == {'fixture/front.png', 'fixture/side.png'}
                assert archive.read('fixture/front.png') == b'fixture front'
            assert state['requests'] == [{'method': 'POST', 'body': {'asset_ids': [11, 12]}}], state['requests']
            assert downloads == ['LeShine-materials.zip'], downloads
            expect(page.locator('#download-selected')).to_be_enabled()
            expect(page.locator('#toast')).to_contain_text('ZIP download started')
            page.screenshot(path=str(EVIDENCE / 'download-success.png'), full_page=True)

            # Fresh session: search filtering + select all submits only unique visible IDs.
            state['mode'] = 'fail'
            page.reload()
            page.get_by_role('button', name='Enter Library').click()
            page.locator('#search').fill('front')
            page.locator('#select-all').check()
            expect(page.locator('#selected-count')).to_have_text('2 selected across this page')
            page.locator('#download-selected').click()
            expect(page.locator('#toast')).to_have_text('Fixture ZIP failure. Please retry.')
            expect(page.locator('#download-selected')).to_be_enabled()
            assert state['requests'][-1] == {'method': 'POST', 'body': {'asset_ids': [11, 13]}}, state['requests']
            page.screenshot(path=str(EVIDENCE / 'failure-retry.png'), full_page=True)
            state['mode'] = 'ok'
            with page.expect_download() as received:
                page.locator('#download-selected').click()
            assert received.value.suggested_filename == 'LeShine-materials.zip'
            assert state['requests'][-1] == {'method': 'POST', 'body': {'asset_ids': [11, 13]}}
            assert len(state['requests']) == 3, state['requests']
            assert downloads == ['LeShine-materials.zip', 'LeShine-materials.zip'], downloads
            assert not errors, errors
            print(json.dumps({'passed': ['multi-tag Cartesian grouping', 'deduplicated selection POST',
                'single downloadable ZIP and extraction', 'pending guard after rerender', 'filtered select all',
                'failure message and retry', 'single original signed link'], 'requests': state['requests'],
                'page_errors': errors, 'screenshots': str(EVIDENCE)}, ensure_ascii=False))
            context.close()
            browser.close()
    finally:
        release_request.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
