import test from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'
import * as search from '../src/views/invoice/composables/useInvoiceCustomerSearch.js'

const customer = (id, name = 'Hajra Omanovic') => ({ company_id: id, company_name: name, kind: 'customer', option_key: `customer:${id}` })
const contact = (id, key) => ({ ...customer(id), kind: 'contact', contact_id: key, option_key: `contact:${key}`, name: 'Hajra Omanovic' })

test('two customer records with matching contacts form two distinct groups, including split pages', () => {
  assert.equal(typeof search.groupCustomerOptions, 'function')
  const groups = search.groupCustomerOptions([contact('1', 'a'), customer('2'), customer('1'), contact('2', 'b'), contact('1', 'a')])
  assert.equal(groups.length, 2)
  assert.deepEqual(groups[0].options.map(row => row.kind), ['customer', 'contact'])
  assert.deepEqual(groups[1].options.map(row => row.kind), ['customer', 'contact'])
  assert.notEqual(groups[0].company_id, groups[1].company_id)
  const onlyContact = search.groupCustomerOptions([contact('3', 'c')])
  assert.deepEqual(onlyContact[0].options.map(row => row.kind), ['contact'])
})

test('confirmed missing customer blocks both customer and contact without replacing the current selection', async () => {
  assert.equal(typeof search.useVerifiedCustomerSelection, 'function')
  const current = ref(customer('current')), selected = []
  let calls = 0
  const picker = search.useVerifiedCustomerSelection({ current: () => current.value,
    verify: async () => { calls++; return { company_id: 'old', status: 'missing' } },
    onSelect: row => selected.push(row) })
  assert.equal(await picker.choose(customer('old')), false)
  assert.equal(picker.isUnavailable('old'), true)
  assert.equal(await picker.choose(contact('old', 'a')), false)
  assert.equal(calls, 1)
  assert.deepEqual(selected, [])
  assert.equal(current.value.company_id, 'current')
  assert.match(picker.error.value, /不存在/)
})

test('a verification outage remains retryable and never marks a customer missing', async () => {
  assert.equal(typeof search.useVerifiedCustomerSelection, 'function')
  let fails = true
  const selected = []
  const picker = search.useVerifiedCustomerSelection({ current: () => null,
    verify: async () => { if (fails) throw new Error('offline'); return { company_id: '1', status: 'active', company_name: 'Current name' } },
    onSelect: row => selected.push(row) })
  assert.equal(await picker.choose(customer('1')), false)
  assert.equal(picker.isUnavailable('1'), false)
  fails = false
  const row = contact('1', 'c')
  assert.equal(await picker.choose(row), true)
  assert.equal(selected[0].company_name, 'Current name')
  assert.equal(selected[0].contact_id, 'c')
  assert.equal(picker.error.value, '')
})

test('late customer verification cannot overwrite a newer selection or a reset editor', async () => {
  assert.equal(typeof search.useVerifiedCustomerSelection, 'function')
  let finish
  const selected = []
  const picker = search.useVerifiedCustomerSelection({ current: () => null,
    verify: row => row.company_id === '1' ? new Promise(resolve => { finish = resolve })
      : Promise.resolve({ company_id: '2', status: 'active', company_name: 'Second' }),
    onSelect: row => selected.push(row) })
  const first = picker.choose(customer('1'))
  await picker.choose(customer('2'))
  finish({ company_id: '1', status: 'active', company_name: 'First' })
  assert.equal(await first, false)
  assert.deepEqual(selected.map(row => row.company_id), ['2'])
  const stale = picker.choose(customer('1'))
  picker.reset()
  finish({ company_id: '1', status: 'missing' })
  await stale
  assert.equal(picker.isUnavailable('1'), false)
  assert.equal(picker.error.value, '')
})

test('a mismatched or incomplete provider identity never becomes a selected customer', async () => {
  assert.equal(typeof search.useVerifiedCustomerSelection, 'function')
  for (const result of [{ company_id: '2', status: 'active', company_name: 'Wrong' }, { company_id: '1', status: 'active' }, { company_id: '1', status: 'out_of_scope' }]) {
    const picker = search.useVerifiedCustomerSelection({ current: () => null, verify: async () => result, onSelect: () => assert.fail('must not select') })
    assert.equal(await picker.choose(customer('1')), false)
    assert.equal(picker.isUnavailable('1'), false)
  }
})
