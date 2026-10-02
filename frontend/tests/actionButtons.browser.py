"""Run against the isolated table-actions Vite fixture; never uses business APIs.

python frontend/tests/actionButtons.browser.py --url http://localhost:3000/tests/fixtures/table-actions/
Requires Python Playwright and installed Chrome. Optional --screenshots directory.
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://localhost:3000/tests/fixtures/table-actions/')
parser.add_argument('--screenshots', type=Path)
args = parser.parse_args()
STYLE = '''el => {const s=getComputedStyle(el);return {
 color:s.color,bg:s.backgroundColor,height:s.height,radius:s.borderRadius,shadow:s.boxShadow,
 fontSize:s.fontSize,lineHeight:s.lineHeight,transform:s.transform,opacity:s.opacity,
 outline:s.outlineStyle,transition:s.transitionDuration};}'''

def contrast(a, b):
    def lum(rgb):
        v = [int(x.strip()) / 255 for x in rgb.removeprefix('rgb(').removesuffix(')').split(',')]
        return sum((x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4) * w
                   for x, w in zip(v, [.2126, .7152, .0722]))
    a, b = sorted([lum(a), lum(b)], reverse=True)
    return (a + .05) / (b + .05)

observations = 0
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1080}, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.route('**/api/**', lambda route: route.abort())
    page.goto(args.url, wait_until='networkidle')
    for tone in ['default', 'primary', 'success', 'danger', 'warning']:
        for kind in ['base', 'disabled', 'loading', 'disabled-loading']:
            pairs = {}
            for prefix in ['gb', 'ep']:
                el = page.locator(f'#{prefix}-{tone}-{kind}')
                el.scroll_into_view_if_needed()
                page.mouse.move(0, 0)
                el.evaluate('(el)=>el.blur()')
                pairs[prefix] = {'base': el.evaluate(STYLE)}
                el.hover(force=True)
                page.wait_for_timeout(40)
                pairs[prefix]['hover'] = el.evaluate(STYLE)
                if kind == 'base':
                    page.mouse.down()
                    page.wait_for_timeout(40)
                    assert el.evaluate('el=>el.matches(":active")')
                    pairs[prefix]['active'] = el.evaluate(STYLE)
                    page.mouse.up()
                    page.mouse.move(0, 0)
                    page.wait_for_timeout(40)
                    clicked = el.evaluate(STYLE)
                    assert clicked['color'] == pairs[prefix]['base']['color'] and clicked['bg'] == 'rgba(0, 0, 0, 0)', clicked
                    page.keyboard.press('Tab')
                    el.focus()
                    page.wait_for_timeout(40)
                    pairs[prefix]['focus'] = el.evaluate(STYLE)
                    assert pairs[prefix]['focus']['outline'] == 'solid'
                if 'loading' in kind:
                    assert el.locator('.is-loading').count() == 1
                    visible_icons = el.locator('.el-icon').evaluate_all('els=>els.filter(e=>getComputedStyle(e).display!=="none" && e.getBoundingClientRect().width>0).length')
                    assert visible_icons == 1, (prefix, visible_icons)
                el.evaluate('(el)=>el.blur()')
            for state in pairs['gb']:
                a, b = pairs['gb'][state], pairs['ep'][state]
                for key in ['color', 'bg', 'height', 'radius', 'shadow', 'fontSize', 'lineHeight', 'transform', 'opacity']:
                    assert a[key] == b[key], (tone, kind, state, key, a[key], b[key])
                assert a['height'] == '24px' and a['radius'] == '0px' and a['shadow'] == 'none'
                assert a['fontSize'] == '13px' and a['transform'] == 'none'
                observations += 2
    for el in page.locator('[id^="solid-"]').all():
        for state in ['base', 'hover', 'active']:
            el.scroll_into_view_if_needed()
            if state == 'base':
                page.mouse.move(0, 0)
                el.evaluate('(el)=>el.blur()')
            else:
                el.hover()
                if state == 'active':
                    page.mouse.down()
            page.wait_for_timeout(40)
            style = el.evaluate(STYLE)
            assert contrast(style['color'], style['bg']) >= 4.5, (el.get_attribute('id'), state, style)
            if state == 'active':
                page.mouse.up()
            observations += 1
    # All action cells expose their buttons, including narrow and long-label cases.
    def layout():
        failures = page.locator('td.table-action-column > .cell').evaluate_all('''cells=>cells.flatMap(cell=>{
          const c=cell.getBoundingClientRect();return [...cell.querySelectorAll('button')].filter(b=>{
            const r=b.getBoundingClientRect();return r.width&&r.height&&(r.left<c.left-1||r.right>c.right+1||r.top<c.top-1||r.bottom>c.bottom+1);
          }).map(b=>b.textContent.trim());})''')
        assert not failures, failures
    layout()
    page.get_by_role('button', name='编辑', exact=True).first.click()
    assert page.locator('output').inner_text() == '编辑'
    page.get_by_label('显示编辑权限按钮').uncheck()
    assert page.get_by_role('button', name='编辑', exact=True).count() == 1  # Invoice fixture remains.
    page.get_by_label('320px 窄容器').check()
    layout()
    page.get_by_role('button', name='导出', exact=True).last.click()
    page.get_by_role('menuitem', name='Excel', exact=True).click()
    assert page.locator('output').inner_text() == 'Excel'
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.screenshots / 'action-buttons-desktop.png'))
    mobile = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, reduced_motion='reduce')
    mobile.goto(args.url, wait_until='networkidle')
    for prefix in ['gb', 'ep']:
        assert mobile.locator(f'#{prefix}-primary-base').evaluate('el=>getComputedStyle(el).minHeight') == '44px'
    assert mobile.locator('.el-table__cell.el-table-fixed-column--left, .el-table__cell.el-table-fixed-column--right').evaluate_all('els=>els.every(el=>getComputedStyle(el).position==="static")')
    mobile_cells = mobile.locator('td.table-action-column > .cell').evaluate_all('''cells=>cells.every(cell=>{
      const c=cell.getBoundingClientRect();return [...cell.querySelectorAll('button')].every(b=>{
        const r=b.getBoundingClientRect();return !r.width||(r.left>=c.left-1&&r.right<=c.right+1&&r.top>=c.top-1&&r.bottom<=c.bottom+1);
      });})''')
    assert mobile_cells, 'touch operation cells must expose all controls'
    if args.screenshots:
        mobile.screenshot(path=str(args.screenshots / 'action-buttons-mobile.png'))
    assert not errors, errors
    browser.close()
print(f'PASS: {observations} state/contrast observations; icons, focus, layout, permissions, dropdown and touch targets')
