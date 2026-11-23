import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { invoiceIsLocal } from '../src/views/commerce-transition/routeState.js'
import { createLatestRequestGate } from '../src/views/invoice/composables/accessoryPricing.js'
import { normalizeHairRow } from '../src/views/invoice/composables/invoiceEditorState.js'
import { calculateLineTotal } from '../src/views/invoice/composables/invoiceSettlement.js'

const source = readFileSync(new URL('../src/views/invoice/composables/useInvoiceHairItems.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"].*?['"]\r?\n/gm, '')
  .replace('export function', 'function')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const flush = () => new Promise(resolve => setImmediate(resolve))
const matched = (id, display = '库存色板') => ({
  is_unique: true,
  item: { product_id: id, sku_id: id + 100, product_name: display, product_display: display, available_stock: 12 },
})
const price = amount => ({ standard_price: amount, customer_price: amount })

function harness() {
  const row = normalizeHairRow({ model: '库存色板', color: '38', length: '16', net_weight_grams: '150g', quantity: 2 })
  const form = { customer_id: 'C1', items: [row] }
  const requests = { options: [], matches: [], prices: [] }
  function request(bucket) {
    return params => {
      const pending = deferred()
      bucket.push({ ...pending, params })
      return pending.promise
    }
  }
  const deps = {
    invoiceIsLocal, createLatestRequestGate, normalizeHairRow, calculateLineTotal,
    msgWarning: () => {}, msgInfo: () => {},
    getInvoiceProductOptions: request(requests.options),
    matchInvoiceProduct: request(requests.matches),
    resolveInvoicePrice: request(requests.prices),
  }
  const createHairItems = new Function(...Object.keys(deps), `${source}; return useInvoiceHairItems`)(
    ...Object.values(deps),
  )
  const hair = createHairItems(form, { value: form.items }, { value: false }, {})
  return { form, row, hair, ...requests }
}

test('product and stock resolve before slow options or pricing', async () => {
  const { row, hair, options, matches, prices } = harness()
  const changed = hair.onLineFilterChange(row)
  assert.equal(matches.length, 1, 'start matching without waiting for options')
  assert.deepEqual(matches[0].params, { model: '库存色板', color: '38', size: '16', unit: '150g' })
  assert.equal(options.length, 1)
  assert.equal(row.matching, true)

  matches[0].resolve(matched(38))
  await flush()
  assert.equal(row.product_id, 38)
  assert.equal(row.sku_id, 138)
  assert.equal(row.available_stock, 12)
  assert.equal(prices.length, 1)
  assert.equal(row.matching, false)
  assert.equal(row.pricing, true, 'save still waits for pricing')

  prices[0].resolve(price(8.25))
  await changed
  assert.equal(row.matching, false)
  assert.equal(row.pricing, false)
  assert.equal(row.total_price, 16.5)
  options[0].resolve({ colors: ['38'], all_colors: ['38', '60'] })
  await flush()
  assert.deepEqual(row.options.all_colors, ['38', '60'])
})

test('opening the same spec shares pending and recently loaded options across rows', async () => {
  const { form, row, hair, options } = harness()
  const first = hair.loadLineOptions(row)
  const reopened = hair.loadLineOptions(row)
  const copied = normalizeHairRow(row)
  form.items.push(copied)
  const secondRow = hair.loadLineOptions(copied)
  assert.equal(options.length, 1)
  options[0].resolve({ sizes: ['16'] })
  await Promise.all([first, reopened, secondRow])
  await hair.loadLineOptions(row)
  assert.equal(options.length, 1)
  assert.deepEqual(row.options.sizes, ['16'])
  assert.deepEqual(copied.options.all_sizes, ['16'])
})

test('catalog options can retry after failure and cannot block a match', async () => {
  const { row, hair, options, matches, prices } = harness()
  const changed = hair.onLineFilterChange(row)
  options[0].reject(new Error('filter options unavailable'))
  await flush()
  matches[0].resolve(matched(38))
  await flush()
  prices[0].resolve(price(10))
  await changed
  assert.equal(row.product_id, 38)
  assert.equal(row.price_per_piece, 10)
  const retry = hair.loadLineOptions(row)
  assert.equal(options.length, 2)
  options[1].resolve({ units: ['150g'] })
  await retry
  assert.deepEqual(row.options.units, ['150g'])
})

test('out-of-order responses preserve the latest match and dropdown context', async () => {
  const { row, hair, options, matches, prices } = harness()
  const old = hair.onLineFilterChange(row)
  row.color = '60'
  const current = hair.onLineFilterChange(row)
  assert.equal(matches.length, 2)
  options[1].resolve({ colors: ['60'] })
  matches[1].resolve(matched(60))
  await flush()
  options[0].resolve({ colors: ['38'] })
  matches[0].resolve(matched(38))
  await old
  assert.equal(row.matching, false)
  assert.equal(row.pricing, true, 'old match cannot end the latest pricing phase')
  assert.equal(row.product_id, 60)
  assert.deepEqual(row.options.colors, ['60'])
  assert.deepEqual(prices.map(request => request.params.color), ['60'])
  prices[0].resolve(price(10))
  await current
})

test('returning to the same specs invalidates the earlier price request', async () => {
  const { row, hair, options, matches, prices } = harness()
  const old = hair.onLineFilterChange(row)
  assert.equal(matches.length, 1)
  matches[0].resolve(matched(38))
  await flush()
  row.color = ''
  const incomplete = hair.onLineFilterChange(row)
  options[1].resolve({ colors: ['38'] })
  await incomplete
  assert.equal(row.matching, false)
  assert.equal(row.pricing, false)
  assert.equal(row.product_id, null)
  row.color = '38'
  const current = hair.onLineFilterChange(row)
  matches[1].resolve(matched(38))
  await flush()
  prices[0].resolve(price(9))
  await old
  assert.equal(row.price_per_piece, null)
  assert.equal(row.pricing, true)
  prices[1].resolve(price(10))
  options[0].resolve({ colors: ['38'] })
  await current
  assert.equal(row.price_per_piece, 10)
  assert.equal(row.matching, false)
  assert.equal(row.pricing, false)
})

test('customer change keeps pricing pending until the latest customer price returns', async () => {
  const { form, row, hair, options, matches, prices } = harness()
  const changed = hair.onLineFilterChange(row)
  matches[0].resolve(matched(38))
  options[0].resolve({ colors: ['38'] })
  await flush()
  form.customer_id = 'C2'
  const repricing = hair.refreshLinePrice(row)
  prices[0].resolve(price(9))
  await changed
  assert.equal(row.pricing, true)
  assert.equal(hair.copyLine(), false)
  assert.equal(row.price_per_piece, null)
  assert.equal(prices[1].params.customer_id, 'C2')
  prices[1].resolve(price(10))
  await repricing
  assert.equal(row.pricing, false)
  assert.equal(row.price_per_piece, 10)
})
