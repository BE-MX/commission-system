const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
function harness() {
  const requests = [], routes = []
  const app = { globalData: { token: 'token', allowedEntries: [], userInfo: { name: '王红' }, baseUrl: 'http://test' }, logout() { this.globalData.token = null } }
  let page, navigation
  const context = vm.createContext({ getApp: () => app, module: { exports: {} },
    wx: { request: r => requests.push(r), getSystemInfoSync: () => ({ statusBarHeight: 24 }),
      setStorageSync() {}, reLaunch: r => routes.push(r.url), switchTab: r => routes.push(r.url), navigateTo: r => routes.push(r.url) },
    Page: p => { page = p },
    require: file => file.includes('navigation') ? navigation : { beijingNow: () => new Date(2026, 8, 15, 9) }
  })
  const read = file => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context)
  read('utils/navigation.js')
  navigation = context.module.exports
  read('pages/entry/entry.js')
  page.setData = data => Object.assign(page.data, data)
  const reply = (allowed, index = requests.length - 1) => requests[index].success({ statusCode: 200, data: { valid: true, allowed_entries: allowed, user: { name: '王红' } } })
  return { app, page, navigation, requests, routes, reply }
}
test('unknown and missing permissions stay hidden; original order retained', () => {
  const { navigation } = harness()
  assert.equal(navigation.visibleEntries(undefined).length, 0)
  assert.equal(navigation.visibleEntries(['unknown']).length, 0)
  assert.equal(navigation.visibleEntries(['shipping', 'export']).map(x => x.id).join(','), 'export,shipping')
})
test('home loads live permissions, routes allowed buttons, refresh removes revoked entry', () => {
  const h = harness()
  h.page.onLoad(); h.page.onShow()
  assert.equal(h.page.data.entries.length, 0)
  h.reply(['export', 'lookup'])
  h.page.onEntryTap({ currentTarget: { dataset: { id: 'export' } } })
  assert.equal(h.routes.pop(), '/pages/scan/scan')
  h.page.onShow(); h.reply(['lookup'])
  assert.equal(h.page.data.entries.map(x => x.id).join(','), 'lookup')
  h.navigation.open('export')
  assert.equal(h.routes.pop(), '/pages/entry/entry')
})
test('network errors fail closed and retry recovers; no grants is a valid empty state', () => {
  const h = harness()
  h.page.onShow(); h.requests[0].fail()
  assert.ok(h.page.data.error)
  assert.equal(h.page.data.entries.length, 0)
  h.page.loadEntries(); h.reply([])
  assert.equal(h.page.data.error, '')
  assert.equal(h.page.data.loading, false)
  assert.equal(h.page.data.entries.length, 0)
})
test('stale responses after hide or account switch cannot restore permissions', () => {
  const h = harness()
  h.page.onShow(); h.page.onHide(); h.reply(['export'])
  assert.equal(h.app.globalData.allowedEntries.length, 0)
  h.page.onShow(); h.app.globalData.token = 'different-account'; h.reply(['shipping'])
  assert.equal(h.app.globalData.allowedEntries.length, 0)
})
test('expired token logs out, missing capability payload does not open all entries', () => {
  const h = harness()
  h.page.onShow(); h.requests[0].success({ statusCode: 200, data: { valid: true } })
  assert.ok(h.page.data.error)
  h.page.loadEntries(); h.requests[1].success({ statusCode: 401 })
  assert.equal(h.app.globalData.token, null)
})

function scanHarness(file) {
  let page
  const calls = { toasts: [], routes: [] }
  const app = { globalData: { token: 't', allowedEntries: [] } }
  const ctx = vm.createContext({ getApp: () => app, Page: p => { page = p },
    require: () => ({ canAccess: () => false }),
    wx: { showToast: data => calls.toasts.push(data.title), switchTab: data => calls.routes.push(data.url),
      scanCode: data => data.success({ result: 'ARK-P:1:abcd' }) } })
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx)
  page.setData = data => Object.assign(page.data, data)
  return { page, app, calls }
}
test('foreign reporting rejects domestic QR without navigation or pending data', () => {
  const h = scanHarness('pages/scan/scan.js')
  for (const prefix of ['ARK-D', 'ARK-DU']) h.page._handleScanResult({ result: prefix + ':1:abcd' })
  assert.equal(h.calls.toasts.length, 2)
  assert.equal(h.calls.routes.length, 0)
  assert.equal(h.app.globalData.pendingDomesticScan, undefined)
})
test('domestic reporting rejects foreign QR without delayed navigation', () => {
  const h = scanHarness('pages/domestic/scan/scan.js')
  h.page.onScanTap()
  assert.equal(h.calls.toasts[0], '未开通外贸报工权限')
  assert.equal(h.calls.routes.length, 0)
})
