import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/router/index.js', import.meta.url),
  'utf8',
)

test('customer portal route is public top-level and registered before MainLayout', () => {
  const createRoute = source.indexOf("path: '/create/:token?'")
  const mainLayout = source.indexOf("path: '/'")

  assert.ok(createRoute >= 0)
  assert.ok(createRoute < mainLayout)
  const routeBlock = source.slice(createRoute, mainLayout)
  assert.match(routeBlock, /name:\s*['"]CustomerImagePortal['"]/)
  assert.match(routeBlock, /public:\s*true/)
  assert.match(routeBlock, /customerImage:\s*true/)
  assert.match(routeBlock, /captureInviteToken/)
})

test('temporary route shell has only bootstrap and actionable missing-link duties', () => {
  assert.match(source, /CustomerImageRouteShell/)
  assert.match(source, /此访问链接已失效，请向业务员重新获取链接。/)
  assert.match(source, /正在加载产品效果图工作台…/)
  assert.match(source, /Task 10 replaces this bootstrap shell/)
})

test('public portal bypasses Ark auth and mobile login redirection', () => {
  const publicGuard = source.indexOf('if (to.meta.public) return next()')
  const authImport = source.indexOf("import('@/stores/auth')")
  assert.ok(publicGuard >= 0 && publicGuard < authImport)
  assert.match(source, /to\.meta\.customerImage/)
})
