import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticItemTermination.js', import.meta.url), 'utf8')
function setup(prompt) {
  const calls = []
  const factory = new Function('reactive', 'promptAction', 'msgSuccessText', 'terminateOrderItem', source.replace(/^import .*$/gm, '').replace('export function', 'function') + '\nreturn useDomesticItemTermination')
  const state = factory(v => v, prompt, msg => calls.push(['success', msg]), async (...args) => calls.push(['terminate', ...args]))(async () => calls.push(['refresh']))
  return { ...state, calls }
}
const item = { id: 12, line_code: 'A2', product_name: '测试产品' }
test('termination targets the selected item and refreshes after success', async () => {
  const ui = setup(async () => ({ value: '  客户取消  ' }))
  await ui.handleTerminateItem(item)
  assert.deepEqual(ui.calls.map(v => v[0]), ['terminate', 'success', 'refresh'])
  assert.deepEqual(ui.calls[0], ['terminate', 12, '客户取消'])
  assert.equal(ui.terminatingItemIds.size, 0)
})
test('cancel makes no write; concurrent clicks share one prompt and write', async () => {
  const cancelled = setup(async () => { throw new Error('cancel') })
  await cancelled.handleTerminateItem(item)
  assert.deepEqual(cancelled.calls, [])
  let release
  const ui = setup(() => new Promise(resolve => { release = resolve }))
  const pending = ui.handleTerminateItem(item)
  await ui.handleTerminateItem(item)
  assert.equal(ui.terminatingItemIds.size, 1)
  release({ value: '取消' })
  await pending
  assert.equal(ui.calls.filter(v => v[0] === 'terminate').length, 1)
})
