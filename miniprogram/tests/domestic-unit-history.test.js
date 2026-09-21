const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
function page() {
  let definition
  const calls = { requests: [], urls: [] }
  const app = { globalData: { baseUrl: 'https://test', token: 'test' } }
  const wx = { request: o => calls.requests.push(o), navigateTo: o => calls.urls.push(o.url), showToast() {} }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/domestic/scan/scan.js'), 'utf8'), {
    getApp: () => app, require: () => ({ guard: () => true }), Page: p => { definition = p }, wx, setTimeout() {}
  })
  definition.data = { ...definition.data }
  definition.setData = values => Object.assign(definition.data, values)
  return { p: definition, calls }
}
for (const reason of ['ALL_DONE', 'NOT_ASSIGNED', 'NOTHING_REPORTABLE', 'ORDER_REVIEW']) {
  test('blocked unit opens its own history only after closing: ' + reason, () => {
    const { p, calls } = page()
    p._loadUnit(42, 'aabbccdd')
    calls.requests[0].success({ statusCode: 200, data: { can_submit: false, unit_id: 42, block_reason: reason } })
    assert.equal(calls.urls.length, 0)
    p.onErrorTap()
    assert.equal(calls.urls[0], '/pages/domestic/unit-history/unit-history?unitId=42&sign=aabbccdd')
    assert.equal(p.data.state, 'idle')
    p.onErrorTap()
    assert.equal(calls.urls.length, 1)
  })
}
test('quantity worker scanning a unit retains the exact unit identity', () => {
  const { p, calls } = page()
  p._loadUnit(43, 'aabbccdd')
  calls.requests[0].success({ statusCode: 200, data: { can_submit: false, scanned_unit_id: 43 } })
  p.onErrorTap()
  assert.match(calls.urls[0], /unitId=43&/)
})
test('invalid signature, missing unit, network failure, and batch card never redirect', () => {
  for (const response of [{ statusCode: 400, data: { detail: { code: 'SIGN_INVALID' } } }, { statusCode: 200, data: { can_submit: false } }, null]) {
    const { p, calls } = page()
    p._loadUnit(42, 'aabbccdd')
    if (response) calls.requests[0].success(response)
    else calls.requests[0].fail()
    p.onErrorTap()
    assert.equal(calls.urls.length, 0)
  }
  const { p, calls } = page()
  p._loadItem(1, 'aabbccdd')
  calls.requests[0].success({ statusCode: 200, data: { can_submit: false } })
  p.onErrorTap()
  assert.equal(calls.urls.length, 0)
})
test('late responses from earlier scans cannot redirect to the wrong unit', () => {
  const { p, calls } = page()
  p._loadUnit(1, 'aabbccdd')
  p._loadUnit(2, '11223344')
  calls.requests[1].success({ statusCode: 200, data: { can_submit: false, unit_id: 2 } })
  calls.requests[0].success({ statusCode: 200, data: { can_submit: false, unit_id: 1 } })
  p.onErrorTap()
  assert.match(calls.urls[0], /unitId=2&sign=11223344/)
})
test('submit rejection goes to the identified unit but network failure keeps retry flow', () => {
  for (const network of [false, true]) {
    const { p, calls } = page()
    p._loadUnit(42, 'aabbccdd')
    calls.requests[0].success({ statusCode: 200, data: { can_submit: true, unit_id: 42, report_mode: 'unit', item_id: 1, next_step: { progress_id: 5 } } })
    p.onConfirmSubmit({ detail: { qty: 1 } })
    if (network) calls.requests[1].fail()
    else calls.requests[1].success({ statusCode: 422, data: { detail: { message: '已报工完成' } } })
    p.onErrorTap()
    assert.equal(calls.urls.length, network ? 0 : 1)
  }
})

test('history page requests the signed piece and formats its records without altering state', () => {
  let p, request
  let stopped = 0
  const app = { globalData: { baseUrl: 'https://test', token: 'token' } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/domestic/unit-history/unit-history.js'), 'utf8'), {
    getApp: () => app, require: () => ({ guard: () => true }), Page: value => { p = value },
    wx: { getSystemInfoSync: () => ({}), request: value => { request = value }, stopPullDownRefresh: () => stopped++ }
  })
  p.setData = values => Object.assign(p.data, values)
  p.onLoad({ unitId: '42', sign: 'aabbccdd' })
  assert.match(request.url, /unit-history\/42\?sign=aabbccdd$/)
  assert.equal(request.header.Authorization, 'Bearer token')
  request.success({ statusCode: 200, data: { unit_id: 42, steps: [{ status: '未报工', records: [{ at: '2026-09-21T09:00:00', revoked: true, revoked_at: '2026-09-21T09:01:00' }] }] } })
  request.complete()
  assert.equal(p.data.unit.steps[0].records[0].timeText, '2026-09-21 09:00:00')
  assert.equal(p.data.unit.steps[0].status, '未报工')
  assert.equal(p.data.loading, false)
  request = null
  p.onLoad({ unitId: 'bad', sign: 'bad' })
  p.onPullDownRefresh()
  assert.equal(request, null)
  assert.equal(stopped, 2)
})

test('late rejection of a prior submission cannot replace the current piece prompt', () => {
  const { p, calls } = page()
  p._loadUnit(1, 'aabbccdd')
  calls.requests[0].success({ statusCode: 200, data: { can_submit: true, unit_id: 1, report_mode: 'unit', item_id: 1, next_step: { progress_id: 5 } } })
  p.onConfirmSubmit({ detail: { qty: 1 } })
  p._loadUnit(2, '11223344')
  calls.requests[2].success({ statusCode: 200, data: { can_submit: false, unit_id: 2, block_message: 'piece two blocked' } })
  calls.requests[1].success({ statusCode: 422, data: { detail: { message: 'piece one completed' } } })
  assert.equal(p.data.errorMessage, 'piece two blocked')
  assert.equal(p.data.submitting, false)
  p.onErrorTap()
  assert.match(calls.urls[0], /unitId=2&sign=11223344/)
})
