import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import vm from 'node:vm'
import * as vue from 'vue'

async function harness(sync, refresh = async () => true) {
  const messages = [], context = vm.createContext({ Set })
  const modules = {
    vue,
    '@/api/stock': { syncProductInventory: sync },
    '@/utils/errors': { errorMessage: e => e.message },
    '@/utils/feedback': Object.fromEntries(['msgError', 'msgSuccessText', 'msgWarning'].map(key =>
      [key, message => messages.push({ type: key, message })])),
  }
  const code = await fs.readFile(new URL('../src/views/stock/composables/useProductInventorySync.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(code, { context })
  await module.link(name => new vm.SyntheticModule(Object.keys(modules[name]), function () {
    for (const [key, value] of Object.entries(modules[name])) this.setExport(key, value)
  }, { context }))
  await module.evaluate()
  return { ...module.namespace.useProductInventorySync({ fetchList: refresh }), messages }
}

test('double click sends one exact product and stays busy until list refresh completes', async () => {
  let finishSync, finishRefresh
  const calls = []
  const h = await harness(id => { calls.push(id); return new Promise(resolve => { finishSync = resolve }) },
    () => new Promise(resolve => { finishRefresh = resolve }))
  const task = h.syncInventory({ product_id: 11 })
  await h.syncInventory({ product_id: 11 })
  assert.deepEqual(calls, [11])
  assert.equal(h.syncingProducts.has(11), true)
  finishSync()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(h.syncingProducts.has(11), true)
  finishRefresh(true)
  await task
  assert.equal(h.syncingProducts.size, 0)
  assert.equal(h.messages[0].type, 'msgSuccessText')
})

test('different rows have independent pending state', async () => {
  const pending = new Map()
  const h = await harness(id => new Promise(resolve => pending.set(id, resolve)))
  const a = h.syncInventory({ product_id: 11 }), b = h.syncInventory({ product_id: 12 })
  assert.equal(h.syncingProducts.size, 2)
  pending.get(11)(); await a
  assert.equal(h.syncingProducts.has(11), false)
  assert.equal(h.syncingProducts.has(12), true)
  pending.get(12)(); await b
})

test('failed sync preserves rows and makes retry available without success feedback', async () => {
  let refreshes = 0
  const h = await harness(async () => { throw new Error('小满响应不完整') }, async () => { refreshes++; return true })
  await h.syncInventory({ product_id: 11 })
  assert.equal(refreshes, 0)
  assert.equal(h.syncingProducts.size, 0)
  assert.deepEqual(h.messages, [{ type: 'msgError', message: '小满响应不完整' }])
})

test('successful write followed by failed refresh is explicitly distinguished', async () => {
  const h = await harness(async () => {}, async options => {
    assert.equal(options.adjustPage, true)
    return false
  })
  await h.syncInventory({ product_id: 11 })
  assert.equal(h.messages[0].type, 'msgWarning')
  assert.match(h.messages[0].message, /库存已同步/)
  assert.equal(h.syncingProducts.size, 0)
})
