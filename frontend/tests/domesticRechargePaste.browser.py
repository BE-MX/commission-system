"""Isolated local browser acceptance; run Vite on 127.0.0.1:3037 first."""
import base64
import json
import traceback
from io import BytesIO
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'tmp' / 'domestic-recharge-paste'
OUT.mkdir(parents=True, exist_ok=True)
URL = 'http://127.0.0.1:3037/tests/fixtures/domestic-recharge-paste/index.html'
data = BytesIO()
Image.new('RGB', (24, 24), '#b96522').save(data, format='PNG')
png = base64.b64encode(data.getvalue()).decode()
results = []

def check(name, fn):
    try:
        fn()
        results.append({'name': name, 'status': 'pass'})
        print('PASS', name, flush=True)
    except Exception as e:
        results.append({'name': name, 'status': 'fail', 'error': str(e)})
        print('FAIL', name, e, flush=True)
        traceback.print_exc()

def real_paste(page, zone):
    page.evaluate('''async data => { const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0)); await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([bytes],{type:'image/png'})})]); }''', png)
    zone.focus()
    page.keyboard.press('Control+V')

def synthetic(zone, kind, size=8):
    zone.evaluate('''(el, f) => { const dt=new DataTransfer(); dt.items.add(new File([new Uint8Array(f.size)],f.name,{type:f.type})); el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})) }''', {'name': 'invalid-file', 'type': kind, 'size': size})

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 900}, permissions=['clipboard-read','clipboard-write'])
    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:3037/') and not route.request.url.startswith('http://127.0.0.1:3037/api/') else route.abort())
    page.goto(URL, wait_until='networkidle')
    page.wait_for_function('window.rechargeTest?.page')
    page.evaluate('window.rechargeTest.page.openRecharge(window.rechargeTest.customer)')
    dialog = page.get_by_role('dialog', name='客户充值（提交后需审核）')
    dialog.wait_for()
    zone = dialog.locator('.app-upload.transfer-zone')
    zone.wait_for()

    def clipboard_and_submit():
        dialog.locator('.el-input-number input').fill('123.45')
        real_paste(page, zone)
        zone.locator('.file-name').wait_for()
        name = zone.locator('.file-name').inner_text()
        assert name and name.endswith('.png'), name
        assert page.evaluate('window.rechargeTest.posts.length') == 0
        captured = page.evaluate('''async () => { const d=window.rechargeTest.page.rechargeDialog; const f=d.voucherFile; return {request_id:d.requestId, name:f.name, type:f.type, bytes:Array.from(new Uint8Array(await f.arrayBuffer()))} }''')
        assert captured['bytes'][:8] == [137,80,78,71,13,10,26,10]
        page.screenshot(path=str(OUT / 'clipboard.png'))
        dialog.get_by_role('button', name='提交审核').click()
        page.wait_for_function('window.rechargeTest.posts.length === 1')
        post = page.evaluate('window.rechargeTest.posts[0]')
        assert post['url'] == '/customers/42/recharges' and post['amount'] == '123.45'
        assert post['request_id'] == captured['request_id'] and post['request_id']
        assert post['file'] == {k:captured[k] for k in ('name','type','bytes')}
        OUT.joinpath('captured-request.json').write_text(json.dumps(post,ensure_ascii=False,indent=2),encoding='utf-8')
    check('真实剪贴板及 multipart 提交', clipboard_and_submit)

    def deletion_and_pdf():
        page.evaluate('window.rechargeTest.page.openRecharge(window.rechargeTest.customer)')
        dialog.wait_for()
        dialog.locator('.el-input-number input').fill('250')
        real_paste(page, zone)
        zone.locator('.file-name').wait_for()
        zone.locator('.remove').click()
        assert zone.locator('.file-name').count() == 0
        assert page.evaluate('window.rechargeTest.page.rechargeDialog.voucherFile') is None
        dialog.get_by_role('button', name='提交审核').click()
        page.get_by_text('请上传银行流水或转账截图').wait_for()
        assert page.evaluate('window.rechargeTest.posts.length') == 1
        zone.locator('input[type=file]').set_input_files({'name':'transfer.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\n% local fixture\n'})
        zone.get_by_text('transfer.pdf').wait_for()
        assert page.evaluate('window.rechargeTest.page.rechargeDialog.voucherFile.name') == 'transfer.pdf'
        dialog.get_by_role('button', name='取消').click()
        dialog.wait_for(state='hidden')
        page.evaluate('window.rechargeTest.page.openRecharge(window.rechargeTest.customer)')
        dialog.wait_for()
        assert zone.locator('.file-name').count() == 0
        assert page.evaluate('window.rechargeTest.page.rechargeDialog.voucherFile') is None
    check('删除阻止旧凭证提交、重选 PDF、重新打开清空', deletion_and_pdf)

    def reject():
        synthetic(zone, 'image/gif')
        page.get_by_text('请上传 PNG / JPG / WebP 图片或 PDF').wait_for(timeout=3000)
        synthetic(zone, 'image/png', 20*1024*1024+1)
        page.get_by_text('文件超过 20MB 限制').wait_for(timeout=3000)
        assert page.evaluate('window.rechargeTest.page.rechargeDialog.voucherFile') is None
        assert page.evaluate('window.rechargeTest.posts.length') == 1
    check('类型和 20MB 限制', reject)

    def narrow():
        page.set_viewport_size({'width':390,'height':844})
        box = zone.bounding_box()
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / 'mobile.png'))
        assert box['x'] >= 0 and box['x'] + box['width'] <= 391, box
    check('窄屏上传区可见', narrow)

    page.close()
    page = browser.new_page(viewport={'width':1280,'height':900}, permissions=['clipboard-read','clipboard-write'])
    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:3037/') and not route.request.url.startswith('http://127.0.0.1:3037/api/') else route.abort())
    page.goto(URL + '?mode=requests', wait_until='networkidle')
    page.wait_for_function('window.rechargeTest?.page')
    def resubmit():
        page.evaluate('window.rechargeTest.page.openEdit(window.rechargeTest.requestRow)')
        dlg = page.get_by_role('dialog', name='修改已撤回申请')
        dlg.wait_for()
        area = dlg.locator('.app-upload.transfer-zone')
        real_paste(page, area)
        area.locator('.file-name').wait_for()
        assert page.evaluate('window.rechargeTest.page.editDialog.file.type') == 'image/png'
        assert page.evaluate('window.rechargeTest.posts.length') == 0
        page.screenshot(path=str(OUT / 'resubmit.png'))
    check('撤回充值重提入口 Ctrl+V', resubmit)
    page.close()
    browser.close()

OUT.joinpath('results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(1 if any(r['status']=='fail' for r in results) else 0)
