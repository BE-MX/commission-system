import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import { useInvoiceCustomerSearch, customerOptionLabel } from '../src/views/invoice/composables/useInvoiceCustomerSearch.js'

const page = (items, total = items.length) => ({ items, total, has_more: items.length < total })
const customer = id => ({ company_id: String(id), company_name: `Customer ${id}`, option_key: `customer:${id}`, kind: 'customer' })
const setup = request => useInvoiceCustomerSearch({ request, scope: () => ({ private_only: true, sales_user_id: 16 }), selected: ref(null), onBound() {} })

test('browse 126 customers across pages without truncation', async () => {
  const all = Array.from({ length: 126 }, (_, i) => customer(i))
  const picker = setup(async ({ offset, limit, private_only, sales_user_id }) => {
    assert.equal(private_only, true)
    assert.equal(sales_user_id, 16)
    return { items: all.slice(offset, offset + limit), total: 126, has_more: offset + limit < 126 }
  })
  await picker.search('')
  await picker.loadMore()
  await picker.loadMore()
  assert.equal(picker.options.value.length, 126)
  assert.equal(picker.total.value, 126)
  assert.equal(picker.hasMore.value, false)
})

test('new query discards an in-flight load-more response', async () => {
  let resolveOld
  const picker = setup(async ({ keyword, offset }) => {
    if (offset) return new Promise(resolve => { resolveOld = resolve })
    return keyword ? page([customer(200)]) : page([customer(1)], 126)
  })
  await picker.search('')
  const pending = picker.loadMore()
  await picker.search('Alice')
  resolveOld(page([customer(2)]))
  await pending
  assert.deepEqual(picker.options.value.map(row => row.company_id), ['200'])
  assert.equal(picker.loading.value, false)
})

test('reset prevents a previous invoice search from filling the next invoice', async () => {
  let finish
  const picker = setup(() => new Promise(resolve => { finish = resolve }))
  const pending = picker.search('old')
  picker.reset()
  finish(page([customer(1)]))
  await pending
  assert.deepEqual(picker.options.value, [])
})

test('editing preserves the selected customer label without changing pagination offset', async () => {
  const selected = ref(customer(999))
  const offsets = []
  const picker = useInvoiceCustomerSearch({
    request: async ({ offset }) => { offsets.push(offset); return page([customer(offset + 1)], 10) },
    scope: () => ({}), selected, onBound() {},
  })
  await picker.search('')
  await picker.loadMore()
  assert.deepEqual(offsets, [0, 1])
  assert.equal(picker.options.value[0].company_id, '999')
  assert.equal(customerOptionLabel({ ...customer(1), kind: 'contact', name: 'Alice' }), 'Alice — Customer 1 · 联系人')
})
