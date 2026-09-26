"""Isolated mobile UX/auth regression. Run Vite on 127.0.0.1:3079; no real APIs are called."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:3079'
OUT = Path(__file__).resolve().parents[2] / 'tmp/fx-mobile-qa'
OUT.mkdir(parents=True, exist_ok=True)
NOW = datetime.now(timezone(timedelta(hours=8))).isoformat()
MARKET = {'checked_at': NOW, 'quote': {'rate': 6.98, 'as_of': NOW, 'usable': True},
          'trend': {'as_of': NOW[:10], 'lag_days': 1, 'usable': True, 'change_5d_pct': 0.2, 'change_20d_pct': -0.4},
          'history': [{'date': f'2026-09-{i:02}', 'rate': 6.97 + i / 1000} for i in range(1, 25)], 'warnings': []}


def setup(browser, width=390, mobile=True, permissions=None, authenticated=True):
    context = browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=mobile, has_touch=mobile,
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1' if mobile else None)
    if authenticated:
        context.add_init_script("localStorage.setItem('ark_access_token', 'isolated-test-token')")
    state = {'calls': [], 'expired': False, 'market_error': False, 'calculate_error': False, 'ai_error': False}
    user = {'id': 1, 'username': 'qa', 'display_name': 'QA', 'roles': [], 'permissions': permissions if permissions is not None else ['fx_settlement:read', 'fx_settlement:write']}

    def api(route):
        path = urlparse(route.request.url).path
        if not path.startswith('/api/'):
            route.continue_()
            return
        state['calls'].append(path)
        if path == '/api/auth/refresh':
            route.fulfill(status=401, json={'detail': 'Session expired'})
        elif path == '/api/auth/me':
            route.fulfill(json=user)
        elif path == '/api/auth/login':
            route.fulfill(json={'access_token': 'isolated-test-token', 'user': user})
        elif path == '/api/auth/logout':
            route.fulfill(json={})
        elif state['expired'] and path.startswith('/api/fx-settlement/'):
            route.fulfill(status=401, json={'detail': 'Session expired'})
        elif path == '/api/fx-settlement/market':
            if state['market_error']:
                route.fulfill(status=503, json={'detail': '行情暂不可用'})
            else:
                route.fulfill(json={'code': 200, 'data': MARKET})
        elif path in ['/api/fx-settlement/calculate', '/api/fx-settlement/advice']:
            if state['calculate_error']:
                route.fulfill(status=503, json={'detail': '测算暂不可用，请重试'})
                return
            data = route.request.post_data_json
            candidates = [{'id': key, 'label': label, 'now_usd': amount, 'later_usd': 100000 - amount,
                           'now_cny': amount * 6.98, 'stress_loss_cny': 1000, 'schedule': [{'date': data['settle_by'], 'usd': 100000-amount}],
                           'scenarios': [{'label': label, 'total_cny': total} for label, total in [('美元下跌', 685000), ('汇率不变', 698000), ('美元上涨', 712000)]]}
                          for key, label, amount in [('immediate', '立即结汇', 100000), ('balanced', '均衡分批', 60000), ('flexible', '保留机动', 30000)]]
            ai = path.endswith('/advice')
            result = {'input': data, 'generated_at': NOW, 'rate_at': NOW, 'rate': 6.98, 'rate_source': '测试参考价', 'market': MARKET,
                      'reserved_usd': 0, 'maximum_later_usd': 70000, 'selected_id': 'balanced', 'candidates': candidates,
                      'selection_source': 'ai' if ai and not state['ai_error'] else 'rules', 'warnings': ['测试压力情景，不是预测。'], 'assumptions': ['测试口径'],
                      'ai': {'summary': '优先满足用款，再分批安排。', 'reasons': ['测试理由'], 'watchpoints': ['测试观察项']} if ai and not state['ai_error'] else None,
                      'ai_error': 'AI 暂不可用，展示规则测算。' if state['ai_error'] else None}
            route.fulfill(json={'code': 200, 'data': result})
        else:
            route.fulfill(json={'code': 200, 'data': []})
    context.route('**/api/**', api)
    page = context.new_page()
    page.on('pageerror', lambda error: state.setdefault('errors', []).append(str(error)))
    return context, page, state


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('[document.documentElement.scrollWidth, innerWidth]')


def fill_form(page):
    page.locator('.mobile-nav').get_by_role('button', name='测算', exact=True).click()
    page.locator('[name=usd_balance]').fill('100000')
    page.locator('[name=max_loss_cny]').fill('2000')


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    for width in [320, 390, 430, 768]:
        context, page, state = setup(browser, width)
        page.goto(BASE + '/invoice/fx-settlement?source=phone')
        expect(page).to_have_url(BASE + '/fx-settlement?source=phone')
        expect(page.get_by_role('heading', name='结汇决策助手', level=2)).to_be_visible()
        expect(page.locator('link[rel=manifest]')).to_have_attribute('href', '/fx-app/manifest.webmanifest')
        expect(page.locator('.current-rate strong')).to_be_visible()
        no_overflow(page)
        if width == 390: page.screenshot(path=str(OUT / 'market-390.png'), full_page=True)
        fill_form(page)
        assert page.locator('[name=usd_balance]').evaluate('(el) => getComputedStyle(el).fontSize') == '16px'
        # Invalid optional field inside a closed section must be revealed and focusable.
        page.locator('.advanced summary').click()
        page.locator('[name=usd_interest_pct]').fill('21')
        page.locator('.advanced summary').click()
        page.get_by_role('button', name='先算金额', exact=True).click()
        assert page.locator('.advanced').get_attribute('open') is not None
        assert '/api/fx-settlement/calculate' not in state['calls']
        page.locator('[name=usd_interest_pct]').fill('0')
        if width == 390: page.screenshot(path=str(OUT / 'form-390.png'), full_page=True)
        page.get_by_role('button', name='先算金额', exact=True).click()
        expect(page.locator('.result-heading h3')).to_have_text('均衡分批')
        expect(page.locator('.scenario-cards article')).to_have_count(3)
        expect(page.locator('.scenario-cards')).to_be_visible()
        expect(page.locator('.table-wrap')).to_be_hidden()
        no_overflow(page)
        if width == 390: page.screenshot(path=str(OUT / 'result-390.png'), full_page=True)
        page.get_by_role('button', name='修改条件 / 重新测算').click()
        page.locator('[name=usd_balance]').fill('120000')
        page.locator('.mobile-nav').get_by_role('button', name='方案').click()
        expect(page.get_by_text('条件或报价已变化', exact=False)).to_be_visible()
        fill_form(page)
        page.get_by_role('button', name='生成 AI 策略').click()
        expect(page.get_by_text('优先满足用款，再分批安排。')).to_be_visible()
        assert not state.get('errors'), state.get('errors')
        context.close()
        print(f'PASS mobile {width}: direct route, metadata, fields, validation, results, stale, AI, overflow')

    context, page, state = setup(browser, authenticated=False)
    page.goto(BASE + '/fx-settlement')
    expect(page).to_have_url(BASE + '/login?redirect=/fx-settlement')
    page.get_by_role('textbox', name='用户名').fill('qa')
    page.get_by_role('textbox', name='密码', exact=True).fill('test-only')
    page.locator('button[type=submit]').click()
    expect(page).to_have_url(BASE + '/fx-settlement')
    page.reload()
    expect(page.locator('.mobile-nav')).to_be_visible()
    state['expired'] = True
    page.get_by_role('button', name='刷新行情').click()
    expect(page).to_have_url(BASE + '/login?redirect=%2Ffx-settlement')
    assert not state.get('errors'), state.get('errors')
    context.close()
    print('PASS anonymous login, refresh restoration, API 401 return path')

    context, page, state = setup(browser, permissions=[])
    page.goto(BASE + '/fx-settlement')
    expect(page.get_by_role('textbox', name='用户名')).to_be_visible()
    assert urlparse(page.url).path == '/login'
    assert '/api/fx-settlement/market' not in state['calls']
    context.close()
    print('PASS no permission: blocked before market request')

    context, page, state = setup(browser, permissions=['fx_settlement:read'])
    page.goto(BASE + '/fx-settlement')
    fill_form(page)
    expect(page.get_by_role('button', name='生成 AI 策略')).to_have_count(0)
    state['calculate_error'] = True
    page.get_by_role('button', name='先算金额').click()
    expect(page.get_by_role('alert')).to_contain_text('测算暂不可用')
    state['calculate_error'] = False
    page.get_by_role('button', name='先算金额').click()
    expect(page.locator('.result-heading h3')).to_have_text('均衡分批')
    context.close()
    print('PASS read-only actions and calculation retry')

    context, page, state = setup(browser)
    state['market_error'] = True
    page.goto(BASE + '/fx-settlement')
    expect(page.get_by_role('alert')).to_contain_text('行情暂不可用')
    fill_form(page)
    page.get_by_label('填写银行实际报价').check()
    page.locator('[name=bank_rate]').fill('6.98')
    state['ai_error'] = True
    page.get_by_role('button', name='生成 AI 策略').click()
    expect(page.get_by_text('AI 暂不可用，展示规则测算。')).to_be_visible()
    page.get_by_role('button', name='退出登录').click()
    expect(page.get_by_role('textbox', name='用户名')).to_be_visible()
    context.close()
    print('PASS unavailable market, manual quote, AI fallback, logout')

    context, page, state = setup(browser, 1440, False)
    page.goto(BASE + '/invoice/fx-settlement')
    expect(page.get_by_role('heading', name='结汇决策助手', level=2)).to_be_visible()
    expect(page.locator('.input-panel')).to_be_visible()
    expect(page.locator('.result-section')).to_be_visible()
    expect(page.locator('.mobile-nav')).to_be_hidden()
    expect(page.get_by_role('link', name='手机应用入口')).to_be_visible()
    no_overflow(page)
    assert not state.get('errors'), state.get('errors')
    context.close()
    print('PASS desktop keeps main layout and two columns')
    browser.close()
