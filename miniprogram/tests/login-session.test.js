const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')

function harness(storage = {}) {
  let app, page
  const calls = { login: 0, requests: [], routes: [] }
  const wx = {
    getStorageSync: key => storage[key],
    setStorageSync: (key, value) => { storage[key] = value },
    removeStorageSync: key => { delete storage[key] },
    getLaunchOptionsSync: () => ({ path: 'pages/entry/entry' }),
    redirectTo: args => calls.routes.push(args.url),
    reLaunch: args => calls.routes.push(args.url),
    login: args => { calls.login++; args.success({ code: 'test-code' }) },
    request: args => calls.requests.push(args),
    showToast: () => {}
  }
  const context = vm.createContext({ wx, App: obj => { app = obj },
    Page: obj => { page = obj }, getApp: () => app })
  function read(file) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), context)
  }
  read('app.js')
  function loadLogin() {
    read('pages/login/login.js')
    page.setData = obj => Object.assign(page.data, obj)
    page.onLoad()
    return page
  }
  return { app, calls, loadLogin, storage }
}

test('explicit logout stays logged out on login page and after restart', () => {
  const h = harness({ ark_token: 'old', ark_user: { id: 1 } })
  h.app.onLaunch()
  h.app.logout({ manual: true })
  h.loadLogin()
  assert.equal(h.calls.login, 0)
  assert.equal(h.storage.ark_token, undefined)
  const restarted = harness(h.storage)
  restarted.app.onLaunch()
  restarted.loadLogin()
  assert.equal(restarted.calls.login, 0)
})

test('explicit sign-in after logout restores normal login and keeps existing binding', () => {
  const h = harness()
  h.app.logout({ manual: true })
  const page = h.loadLogin()
  page.onWechatLogin()
  assert.equal(h.calls.login, 1)
  h.calls.requests[0].success({ statusCode: 200, data: {
    bound: true, token: 'new', user: { id: 1, wx_id: 'openid-test' }
  } })
  assert.equal(h.storage.ark_token, 'new')
  assert.equal(h.storage.ark_manual_logout, undefined)
  assert.equal(h.calls.routes.at(-1), '/pages/entry/entry')
})

test('first launch still recognizes WeChat and failures can be retried', () => {
  const h = harness()
  const page = h.loadLogin()
  assert.equal(h.calls.login, 1)
  h.calls.requests[0].fail()
  assert.equal(page.data.isLoggingIn, false)
  page.onWechatLogin()
  assert.equal(h.calls.login, 2)
})

test('failed WeChat login cannot bind an empty identity', () => {
  const h = harness()
  const page = h.loadLogin()
  h.calls.requests[0].fail()
  page.setData({ identifier: 'worker01' })
  page.onBind()
  assert.equal(h.calls.requests.length, 1)
})

test('unbound WeChat identity can bind once and persist auth', () => {
  const h = harness()
  const page = h.loadLogin()
  h.calls.requests[0].success({ statusCode: 200, data: { bound: false, open_id: 'openid-test' } })
  page.setData({ identifier: 'worker01' })
  page.onBind()
  page.onBind()
  assert.equal(h.calls.requests.length, 2)
  assert.equal(h.calls.requests[1].data.open_id, 'openid-test')
  h.calls.requests[1].success({ statusCode: 200, data: { token: 'bound-token', user: { id: 1 } } })
  assert.equal(h.storage.ark_token, 'bound-token')
})
