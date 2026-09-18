import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/invoice/composables/useLinkedInvoiceSync.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup(api = {}, saved = () => {}) {
  const mocks = { ref: value => ({ value }), ElMessage: { warning() {} }, ElMessageBox: {},
    saveInvoiceLinked: async () => ({ invoice: { id: 1 }, operation: { id: 'op', invoice_id: 1 } }),
    getInvoiceLinked: async () => null, runInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'manual' }),
    closeInvoiceLinked: async () => ({ id: 'op', invoice_id: 1, status: 'manual' }), resolveInvoiceLinked() {}, ...api }
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
