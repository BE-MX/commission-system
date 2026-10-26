import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticItemTermination.js', import.meta.url), 'utf8')
function setup(write = async () => {}) {
  const calls = []
  const factory = new Function('reactive', 'msgSuccessText', 'msgWarning', 'terminateOrderItem', 'newRequestId', source.replace(/^import .*$/gm, '').replace('export function', 'function') + '\nreturn useDomesticItemTermination')
  const state = factory(v => v, msg => calls.push(['success', msg]), msg => calls.push(['warning', msg]), async (...args) => { calls.push(['terminate', ...args]); await write() }, () => 'stable-request')(async () => calls.push(['refresh']))
  return { ...state, calls }
}
const item = { id: 12, line_code: 'A2', product_name: '测试产品', order_qty: 5, shipped_qty: 2 }

test('opens quantity selection capped at unshipped quantity and cancel writes nothing', () => {
  const ui = setup()
  ui.handleTerminateItem(item)
  assert.equal(ui.terminationDialog.maxQty, 3)
  assert.equal(ui.terminationDialog.qty, 3)
  ui.terminationDialog.visible = false
  assert.deepEqual(ui.calls, [])
})

test('selected quantity, trimmed reason and stable request are sent before refresh', async () => {
  const ui = setup()
  ui.handleTerminateItem(item)
  Object.assign(ui.terminationDialog, { qty: 1, reason: '  客户取消  ' })
  await ui.confirmTerminateItem()
  assert.deepEqual(ui.calls.map(v => v[0]), ['terminate', 'success', 'refresh'])
  assert.deepEqual(ui.calls[0], ['terminate', 12, '客户取消', 1, 'stable-request'])
  assert.equal(ui.terminationDialog.visible, false)
  assert.equal(ui.terminatingItemIds.size, 0)
})

test('validation blocks invalid quantity and empty reason', async () => {
  const ui = setup()
  ui.handleTerminateItem(item)
  for (const qty of [0, 4, 1.2, undefined]) {
    Object.assign(ui.terminationDialog, { qty, reason: '取消' })
    await ui.confirmTerminateItem()
  }
  Object.assign(ui.terminationDialog, { qty: 1, reason: ' ' })
  await ui.confirmTerminateItem()
  assert.equal(ui.calls.filter(v => v[0] === 'terminate').length, 0)
})

test('double submit writes once and uncertain retry retains request id', async () => {
  let release
  let failing = true
  const ui = setup(() => failing ? new Promise((resolve, reject) => { release = reject }) : Promise.resolve())
  ui.handleTerminateItem(item)
  ui.terminationDialog.reason = '取消'
  const pending = ui.confirmTerminateItem()
  await ui.confirmTerminateItem()
  assert.equal(ui.calls.length, 1)
  release(new Error('network'))
  await assert.rejects(pending)
  assert.equal(ui.terminationDialog.visible, true)
  ui.terminationDialog.visible = false
  ui.handleTerminateItem(item)
  assert.equal(ui.terminationDialog.requestId, 'stable-request')
  failing = false
  await ui.confirmTerminateItem()
  assert.equal(ui.calls[0][4], ui.calls[1][4])
})
