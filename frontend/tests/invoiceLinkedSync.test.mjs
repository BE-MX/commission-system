import { feedbackFixture } from './helpers/feedbackFixture.mjs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { newRequestKey } from '../src/utils/requestKey.js'
const source = readFileSync(new URL('../src/views/invoice/composables/useLinkedInvoiceSync.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup(api = {}, saved = () => {}) {
  const mocks = { newRequestKey, ref: value => ({ value }), ElMessage: { warning() {} }, ElMessageBox: {},
    saveInvoiceLinked: async () => ({ invoice: { id: 1 }, operation: { id: 'op', invoice_id: 1 } }),
    getInvoiceLinked: async () => null, runInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'manual' }),
    closeInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'manual' }), resolveInvoiceLinked() {}, ...api }
  Object.assign(mocks, feedbackFixture(mocks))
  return new Function(...Object.keys(mocks), source + '\nreturn useLinkedInvoiceSync')( ...Object.values(mocks))(saved)
}
test('409 clears rejected key so corrected payload can save', async () => {
  const keys = []
  const vm = setup({ saveInvoiceLinked: async (id, body) => {
    keys.push(body.request_key)
    if (keys.length === 1) throw { response: { status: 409 } }
    return { invoice: { id }, operation: { id: 'op', invoice_id: id } }
  } })
  await assert.rejects(vm.save(1, { amount: 1 }, 'v1'))
  assert.equal((await vm.save(1, { amount: 2 }, 'v2')).id, 1)
  assert.notEqual(keys[0], keys[1])
})
test('lost save response reuses original key before accepting another edit', async () => {
  const requests = []
  const vm = setup({ saveInvoiceLinked: async (id, body) => {
    requests.push(body)
    if (requests.length === 1) throw new Error('timeout')
    return { invoice: { id }, operation: { id: 'op', invoice_id: id } }
  } })
  await assert.rejects(vm.save(1, { amount: 1 }, 'v1'))
  assert.equal(await vm.save(1, { amount: 2 }, 'v2'), null)
  assert.equal(requests[0].request_key, requests[1].request_key)
  assert.equal(requests[1].invoice.amount, 1)
})
test('run and close await editor refresh with invoice identity', async () => {
  const refreshed = []
  const vm = setup({}, async id => refreshed.push(id))
  await vm.save(1, {}, 'version')
  await vm.run(); await vm.close()
  assert.deepEqual(refreshed, [1, 1])
})
test('lost run response reads durable result without another POST', async () => {
  let posts = 0, gets = 0
  const vm = setup({ runInvoiceLinked: async () => { posts++; throw Error('timeout') },
    getInvoiceLinked: async () => { gets++; return { id: 'op', invoice_id: 1, status: 'running' } } })
  await vm.save(1, {}, 'version'); await vm.run()
  assert.equal(posts, 1); assert.equal(gets, 1); assert.equal(vm.operation.value.status, 'running')
})

test('lost response recovered as done shows success without a misleading warning', async () => {
  const warnings = [], successes = []
  let posts = 0, refreshed = 0
  const vm = setup({ ElMessage: { warning: message => warnings.push(message), success: message => successes.push(message) },
    runInvoiceLinked: async (id, identity, recheck, options) => {
      assert.equal(options.suppressToast, true); posts++; throw Error('lost response')
    }, getInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'done' }),
  }, async () => { refreshed++ })
  await vm.save(1, {}, 'version')
  assert.equal((await vm.run()).status, 'done')
  assert.equal(posts, 1); assert.equal(refreshed, 1)
  assert.deepEqual(warnings, [])
  assert.match(successes[0], /同步完成/)
})

test('queued run explains automatic continuation without a failure warning', async () => {
  const warnings = [], infos = []
  const vm = setup({ ElMessage: { warning: value => warnings.push(value), info: value => infos.push(value) },
    runInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'pending' }) })
  await vm.save(1, {}, 'version'); await vm.run()
  assert.deepEqual(warnings, [])
  assert.match(infos[0], /修改已保存.*继续同步/)
})

test('a different latest task cannot complete the original lost response', async () => {
  const refreshed = []
  const vm = setup({ runInvoiceLinked: async () => { throw Error('timeout') },
    getInvoiceLinked: async () => ({ id: 'different', invoice_id: 1, status: 'done' }) }, id => refreshed.push(id))
  await vm.save(1, {}, 'version')
  assert.equal(await vm.run(), null)
  assert.equal(vm.operation.value.id, 'op')
  assert.deepEqual(refreshed, [])
})
