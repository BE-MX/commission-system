import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/router/index.js', import.meta.url),
  'utf8',
)

const nginx = readFileSync(new URL('../nginx.conf', import.meta.url), 'utf8')

test('customer portal route is public top-level and registered before MainLayout', () => {
  const createRoute = source.indexOf("path: '/create/:token?'")
  const mainLayout = source.indexOf("path: '/'")

  assert.ok(createRoute >= 0)
  assert.ok(createRoute < mainLayout)
  const routeBlock = source.slice(createRoute, mainLayout)
  assert.match(routeBlock, /name:\s*['"]CustomerImagePortal['"]/)
  assert.match(routeBlock, /public:\s*true/)
  assert.match(routeBlock, /customerImage:\s*true/)
  assert.match(routeBlock, /captureCustomerImageRouteToken/)
})

test('temporary route shell has only bootstrap and actionable missing-link duties', () => {
  assert.match(source, /CustomerImageRouteShell/)
  assert.match(source, /此访问链接已失效，请向业务员重新获取链接。/)
  assert.match(source, /正在加载产品效果图工作台…/)
  assert.match(source, /Task 10 replaces this bootstrap shell/)
})

test('public portal bypasses Ark auth and mobile login redirection', () => {
  const publicGuard = source.indexOf('if (bypassCustomerImageRoute(')
  const mobileDetection = source.indexOf('const isMobileUA')
  const authImport = source.indexOf("import('@/stores/auth')")
  assert.ok(publicGuard >= 0 && publicGuard < authImport)
  assert.ok(publicGuard < mobileDetection)
})

test('customer route helpers execute token capture redirect and early public bypass', async () => {
  const helpers = await import('../src/router/customerImageRoute.js').catch(() => ({}))
  assert.equal(typeof helpers.captureCustomerImageRouteToken, 'function')
  assert.equal(typeof helpers.bypassCustomerImageRoute, 'function')

  const captured = []
  assert.deepEqual(
    helpers.captureCustomerImageRouteToken(' invite-token ', token => captured.push(token)),
    { name: 'CustomerImagePortal', replace: true },
  )
  assert.deepEqual(captured, [' invite-token '])
  assert.equal(helpers.captureCustomerImageRouteToken('', () => assert.fail()), true)

  const effects = []
  assert.equal(helpers.bypassCustomerImageRoute(
    { meta: { customerImage: true, title: '莱莎产品效果图' } },
    () => effects.push('next'),
    title => effects.push(title),
  ), true)
  assert.deepEqual(effects, ['莱莎产品效果图 - 莱莎方舟', 'next'])
  assert.equal(helpers.bypassCustomerImageRoute({ meta: {} }, () => assert.fail()), false)
  assert.match(source, /captureCustomerImageRouteToken/)
  assert.match(source, /bypassCustomerImageRoute/)
})

test('nginx serves only customer create HTML with private no-store and no-referrer headers', () => {
  const createLocation = nginx.match(/location\s+~\s+\^\\?\/create[\s\S]*?\n\s*}/)?.[0] || ''
  assert.ok(createLocation, 'missing dedicated /create HTML location')
  assert.match(createLocation, /add_header\s+Referrer-Policy\s+['"]?no-referrer['"]?\s+always;/)
  assert.match(createLocation, /add_header\s+Cache-Control\s+['"]private,\s*no-store['"]\s+always;/)
  assert.match(createLocation, /try_files\s+\/index\.html\s+=404;/)

  const fallback = nginx.match(/location\s+\/\s*{[\s\S]*?\n\s*}/)?.[0] || ''
  assert.doesNotMatch(fallback, /Cache-Control|Referrer-Policy/)
})

test('nginx access logs redact customer secrets from both request URI and Referer', () => {
  assert.match(nginx, /map\s+\$request_uri\s+\$ark_safe_request_uri\s*{/)
  assert.match(nginx, /map\s+\$http_referer\s+\$ark_safe_http_referer\s*{/)
  const format = nginx.match(/log_format\s+ark_safe[\s\S]*?;/)?.[0] || ''
  assert.match(format, /\$ark_safe_request_uri/)
  assert.match(format, /\$ark_safe_http_referer/)
  assert.doesNotMatch(format, /['"]\$request['"]/)
  assert.match(nginx, /access_log\s+\/var\/log\/nginx\/access\.log\s+ark_safe;/)
})
