"""Image bytes and real XHR regression; API responses are isolated, no remote writes."""
import argparse
import base64
import io
import json
import time
from pathlib import Path

from PIL import Image, PngImagePlugin
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:3027')
parser.add_argument('--output', default='tmp/knowledge-image-upload')
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)

# A 2.2 MB PNG with transparent pixels and removable text metadata.
image = Image.new('RGBA', (800, 450), (24, 100, 180, 255))
image.putpixel((0, 0), (0, 0, 0, 0))
metadata = PngImagePlugin.PngInfo()
metadata.add_text('Comment', 'x' * 2_200_000)
png_buffer = io.BytesIO()
image.save(png_buffer, 'PNG', pnginfo=metadata)
png_bytes = png_buffer.getvalue()
jpeg_buffer = io.BytesIO()
Image.effect_noise((3200, 1800), 48).convert('RGB').save(jpeg_buffer, 'JPEG', quality=98)
jpeg_bytes = jpeg_buffer.getvalue()
base = args.base_url + '/tests/fixtures/editor-images/index.html'

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page()
    page.goto(base)
    page.wait_for_load_state('networkidle')
    metrics = []
    for name, mime, data in [('transparent.png', 'image/png', png_bytes), ('photo.jpg', 'image/jpeg', jpeg_bytes)]:
        result = page.evaluate('''async ({name, mime, bytes}) => {
          const {prepareKnowledgeImage} = await import('/src/utils/prepareKnowledgeImage.js');
          const file = new File([Uint8Array.from(atob(bytes), c => c.charCodeAt(0))], name, {type:mime});
          const prepared = await prepareKnowledgeImage(file);
          const bitmap = await createImageBitmap(prepared);
          const canvas = document.createElement('canvas');
          canvas.width = bitmap.width; canvas.height = bitmap.height;
          const ctx = canvas.getContext('2d'); ctx.drawImage(bitmap, 0, 0);
          const alpha = ctx.getImageData(0, 0, 1, 1).data[3];
          bitmap.close();
          return {name, original:file.size, uploaded:prepared.size, type:prepared.type,
            width:canvas.width, height:canvas.height, alpha};
        }''', {'name': name, 'mime': mime, 'bytes': base64.b64encode(data).decode()})
        assert result['uploaded'] < result['original'], result
        assert result['type'] == mime and max(result['width'], result['height']) <= 2400, result
        if mime == 'image/png':
            assert result['alpha'] == 0 and result['width'] == 800 and result['height'] == 450, result
        metrics.append(result)

    # A real browser XHR that takes longer than the former 30-second timeout.
    requests = []
    def respond(route):
        request = route.request
        if request.method == 'POST':
            requests.append({'method': request.method, 'body_bytes': len(request.post_data_buffer)})
            time.sleep(33)
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'code': 200, 'data': {'id': 9}}))
        elif request.method == 'GET':
            route.fulfill(status=200, content_type='image/png', body=png_bytes)
        else:
            route.abort()
    page.route('**/api/knowledge/**', respond)
    page.evaluate('imageTest.realTransport = true')
    started = time.monotonic()
    page.locator('input[type=file]').set_input_files({'name': 'transparent.png', 'mimeType': 'image/png', 'buffer': png_bytes})
    expect(page.locator('.knowledge-image img')).to_have_count(1, timeout=45000)
    page.wait_for_function("document.querySelector('.knowledge-image img').naturalWidth === 800")
    elapsed = time.monotonic() - started
    assert elapsed > 30 and len(requests) == 1, (elapsed, requests)
    assert requests[0]['body_bytes'] < len(png_bytes) / 10, requests
    page.get_by_role('button', name='保存草稿', exact=True).click()
    page.wait_for_function('imageTest.saves.length === 1')
    nodes = [n for n in page.evaluate('imageTest.saves[0].content.content') if n['type'] == 'knowledgeImage']
    assert nodes[0]['attrs'] == {'assetId': 9, 'alt': '', 'caption': ''}, nodes
    page.screenshot(path=str(out / 'slow-upload-success.png'), full_page=True)
    browser.close()

result = {'images': metrics, 'slow_xhr_seconds': round(elapsed, 2), 'requests': requests, 'canonical_save': True}
(out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
