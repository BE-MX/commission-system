"""Browser acceptance against mocked APIs; run with the local Vite server.

python scripts/test_ai_gateway_ui.py --browser-executable <chromium-path>
All /api requests are intercepted; no credentials or paid provider are used.
"""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:3018')
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in ('127.0.0.1', 'localhost'), 'local UI only'
    output = Path(__file__).resolve().parents[1] / 'tmp/ai-gateway-qa'
    output.mkdir(parents=True, exist_ok=True)
    item = dict(id=1, name='文案站点', owner_user_id=1, owner_name='演示业务员', is_enabled=True,
        site_url='https://example.invalid', description='客户文案', preset_ids=[1], preset_names=['sales_copy'],
        daily_limit=100, rpm_limit=10, concurrency_limit=2, max_output_tokens=2048, today_calls=5,
        tokens_prompt=100, tokens_completion=300, unknown_usage=1, failures=1, occupied=1, needs_review=1,
        last_used_at='2026-09-12T00:10:00')
    apps = [item]
    request_id = 'd27ff095-abf5-4428-b396-fb968db7ae92'
    record = dict(request_id=request_id, preset_name='sales_copy', created_at='2026-09-12T00:10:00',
        status='unknown', tokens_prompt=None, tokens_completion=None, error_code='upstream_timeout',
        resolution_reason=None, can_resolve=True)
    writes = []

    def handler(route):
        path = urlparse(route.request.url).path
        if not path.startswith('/api/'):
            return route.continue_()
        method = route.request.method
        if path == '/api/auth/me':
            return route.fulfill(json=dict(id=1, username='demo', real_name='演示管理员', permissions=['ai:admin'], roles=['super_admin']))
        if path.endswith('/admin/options'):
            data = dict(owners=[dict(id=1, name='演示业务员')], presets=[dict(id=1, name='sales_copy', model='mock-text')])
        elif path.endswith('/rotate-key'):
            writes.append(('rotate', {}))
            data = dict(id=1, api_key='ark_site_UI_TEST_ONLY', key_hint='ark…ONLY')
        elif path.endswith('/resolve'):
            body = route.request.post_data_json
            writes.append(('resolve', body))
            record.update(status='timeout', can_resolve=False, resolution_reason=body['reason'])
            item.update(occupied=0, needs_review=0)
            data = dict(request_id=request_id, status='timeout')
        elif '/ai-gateway/admin/apps' in path and method == 'PATCH':
            body = route.request.post_data_json
            writes.append(('patch', body))
            item.update(body)
            data = item
        elif path.endswith('/admin/apps') and method == 'POST':
            body = route.request.post_data_json
            writes.append(('create', body))
            apps.append({**item, **body, 'id': 2})
            data = {**apps[-1], 'api_key': 'ark_site_UI_NEW_TEST_ONLY'}
        elif path.endswith('/requests'):
            data = dict(items=[record], total=1)
        elif '/ai-gateway/admin/apps' in path:
            data = dict(items=apps, total=len(apps))
        elif path in ('/api/ai/providers', '/api/ai/presets'):
            data = []
        else:
            data = dict(items=[], total=0)
        route.fulfill(json=dict(code=200, message='ok', data=data))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=args.browser_executable)
        try:
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            page.emulate_media(reduced_motion='reduce')
            page.add_init_script("localStorage.setItem('ark_access_token', 'ui-test-only')")
            page.route('**/api/**', handler)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(args.base_url + '/system/ai')
            page.wait_for_load_state('networkidle')
            page.get_by_role('tab', name='站点应用').click()
            expect(page.get_by_role('tab', name='站点应用')).to_have_attribute('aria-selected', 'true')
            expect(page.get_by_text('文案站点', exact=True)).to_be_visible()
            page.screenshot(path=str(output/'desktop.png'), full_page=True)
            # Reset immediately after loading, before ever opening the editor.
            page.get_by_role('button', name='重置密钥', exact=True).click()
            page.get_by_role('button', name='确定重置密钥', exact=True).click()
            key_dialog = page.get_by_role('dialog', name='保存站点密钥')
            expect(key_dialog.locator('pre')).to_contain_text('ARK_AI_PRESET=sales_copy')
            page.get_by_role('button', name='已保存，关闭').click()
            expect(key_dialog).not_to_be_visible()
            expect(page.get_by_text('ark_site_UI_TEST_ONLY', exact=False)).to_have_count(0)
            # Edit limits, preserving grants and only sending editable fields.
            page.get_by_role('button', name='编辑', exact=True).click()
            editor = page.get_by_role('dialog', name='编辑站点应用')
            editor.get_by_label('应用名称', exact=True).fill('文案站点已编辑')
            editor.get_by_role('button', name='保存', exact=True).click()
            expect(editor).not_to_be_visible()
            assert writes[-1][1]['name'] == '文案站点已编辑'
            assert writes[-1][1]['preset_ids'] == [1]
            # Disable/enable path uses explicit mutation, no destructive delete.
            page.get_by_role('button', name='停用', exact=True).click()
            page.get_by_role('button', name='确定停用', exact=True).click()
            expect(page.get_by_role('button', name='启用', exact=True)).to_be_visible()
            page.get_by_role('button', name='启用', exact=True).click()
            # Unknown records require both an audit reason and explicit checkbox.
            page.get_by_role('button', name='调用记录', exact=True).click()
            expect(page.get_by_text(request_id, exact=True)).to_be_visible()
            page.get_by_role('button', name='解除占用', exact=True).click()
            resolve_dialog = page.get_by_role('dialog', name='核查后解除并发占用')
            expect(resolve_dialog.get_by_role('button', name='解除占用', exact=True)).to_be_disabled()
            resolve_dialog.get_by_role('textbox', name='核查结论').fill('本地已结束，供应商确认请求完成')
            resolve_dialog.get_by_text('已确认本地执行结束，并完成上游结果核查', exact=True).click()
            expect(resolve_dialog.get_by_role('checkbox')).to_be_checked()
            resolve_dialog.get_by_role('button', name='解除占用', exact=True).click()
            expect(resolve_dialog).not_to_be_visible()
            expect(page.get_by_role('dialog', name='文案站点已编辑 · 调用记录').get_by_text('已核查超时', exact=True)).to_be_visible()
            page.get_by_role('dialog', name='文案站点已编辑 · 调用记录').locator('.el-drawer__close-btn').click()
            # Creation returns a one-time key; do not save that dialog screenshot.
            page.get_by_role('button', name='创建站点应用', exact=True).click()
            creator = page.get_by_role('dialog', name='创建站点应用')
            creator.get_by_label('应用名称', exact=True).fill('新建示例站点')
            creator.locator('.el-select').nth(0).click()
            page.get_by_role('option', name='演示业务员', exact=True).click()
            creator.locator('.el-select').nth(1).click()
            page.get_by_role('option', name='sales_copy · mock-text', exact=True).click()
            creator.get_by_text('用途说明', exact=True).click()
            creator.get_by_role('button', name='保存', exact=True).click()
            expect(key_dialog).to_be_visible()
            page.get_by_role('button', name='已保存，关闭').click()
            expect(key_dialog).not_to_be_visible()
            expect(page.locator('.key-config')).not_to_contain_text('ark_site_')
            expect(page.get_by_text('新建示例站点', exact=True)).to_be_visible()
            assert any(action == 'create' for action, _ in writes)
            assert not errors, errors
            page.set_viewport_size(dict(width=390, height=844))
            expect(page.locator('.gateway-apps .el-table__fixed-right')).to_have_count(0)
            expect(page.locator('.el-message')).to_have_count(0, timeout=10000)
            page.screenshot(path=str(output/'mobile.png'), full_page=True)
            assert page.locator('body').evaluate('(el) => el.scrollWidth <= window.innerWidth + 1')
            print('PASS: list, direct rotation, one-time key, edit, disable/enable, audited resolve, create and narrow viewport')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
