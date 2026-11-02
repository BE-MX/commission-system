import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'

const source = readFileSync(new URL('../src/views/design/customer-media/composables/useCustomerMediaClear.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup({ confirm = async () => {}, clear, blocked = false, status = 'draft', assets = [{ id: 1 }, { id: 2 }] } = {}) {
  let batch = { id: 15, status, assets }
  const calls = [], notices = []
  let refreshCount = 0, resetCount = 0
  const useClear = new Function('ref', 'clearMediaAssets', 'confirmAction', 'isFeedbackCancelled', 'msgError', 'msgSuccessText',
    `${source}; return useCustomerMediaClear`)(ref,
    async (...args) => { calls.push(args); return clear ? clear(...args) : { data: { ...batch, assets: [] } } },
    async (...args) => { notices.push(args); return confirm(...args) },
    error => ['cancel', 'close'].includes(error),
    () => {}, message => notices.push(message),
  )
  const state = useClear({ getBatch: () => batch, onBatch: data => { batch = data }, isBlocked: () => blocked,
    refreshBatch: async () => { refreshCount++ }, onCleared: () => { resetCount++ } })
  return { ...state, calls, notices, get batch() { return batch },
    get refreshCount() { return refreshCount }, get resetCount() { return resetCount } }
}

test('clear confirms and sends all batch IDs, then replaces the batch and resets filters', async () => {
  const state = setup()
  await state.clearAssets()
  assert.match(state.notices[0][0], /全部 2 个.*含筛选隐藏项/)
  assert.match(state.notices[0][0], /客户标签和待上传清单会保留/)
  assert.equal(state.notices[0][2].confirmButtonText, '确认清空')
  assert.deepEqual(state.calls, [[15, [1, 2]]])
  assert.deepEqual(state.batch.assets, [])
  assert.equal(state.resetCount, 1)
  assert.equal(state.clearing.value, false)
})

for (const action of ['cancel', 'close']) test(`confirmation ${action} does not delete or change the list`, async () => {
  const state = setup({ confirm: async () => { throw action } })
  await state.clearAssets()
  assert.deepEqual(state.calls, [])
  assert.equal(state.batch.assets.length, 2)
  assert.equal(state.refreshCount, 0)
  assert.equal(state.resetCount, 0)
  assert.equal(state.clearing.value, false)
})

test('clear blocks duplicate clicks throughout confirmation and request', async () => {
  let resolveConfirm, resolveClear
  const state = setup({ confirm: () => new Promise(resolve => { resolveConfirm = resolve }),
    clear: () => new Promise(resolve => { resolveClear = resolve }) })
  const pending = state.clearAssets()
  assert.equal(state.clearing.value, true)
  await state.clearAssets()
  assert.equal(state.notices.length, 1)
  resolveConfirm()
  await new Promise(resolve => setImmediate(resolve))
  await state.clearAssets()
  assert.equal(state.calls.length, 1)
  resolveClear({ data: { id: 15, assets: [] } })
  await pending
  assert.equal(state.clearing.value, false)
})

test('failed or uncertain deletion reads current state and does not claim success', async () => {
  const state = setup({ clear: async () => { throw new Error('network timeout') } })
  await state.clearAssets()
  assert.equal(state.refreshCount, 1)
  assert.equal(state.resetCount, 0)
  assert.equal(state.notices.length, 1)
  assert.equal(state.batch.assets.length, 2)
  assert.equal(state.clearing.value, false)
})

test('noneditable, empty and busy batches cannot open a clear confirmation', async () => {
  for (const options of [{ status: 'published' }, { status: 'pending_review' }, { assets: [] }, { blocked: true }]) {
    const state = setup(options)
    await state.clearAssets()
    assert.deepEqual(state.notices, [])
    assert.deepEqual(state.calls, [])
  }
})
