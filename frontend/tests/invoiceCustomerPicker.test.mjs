import test from 'node:test'
import assert from 'node:assert/strict'
import { h, nextTick, reactive } from 'vue'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'
import * as search from '../src/views/invoice/composables/useInvoiceCustomerSearch.js'

const company = id => ({ company_id: id, company_name: 'Hajra Omanovic', country_name: '美国', kind: 'customer', option_key: `customer:${id}` })
const contact = id => ({ ...company(id), kind: 'contact', name: 'Hajra Omanovic', contact_id: id, option_key: `contact:${id}` })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function fixture(t, verify) {
  const component = loadComponent('../../src/views/invoice/components/InvoiceCustomerPicker.vue', {
    '@/api/invoice': { verifyInvoiceCustomer: verify },
    '../composables/useInvoiceCustomerSearch': search,
  })
  const chosen = []
  const props = reactive({ modelValue: null, options: [company('9001'), contact('9001'), company('9002'), contact('9002')],
    privateOnly: true, salesUserId: 16, active: true, search() {}, loadMore() {},
    'onUpdate:modelValue': row => { props.modelValue = row }, onChange: row => chosen.push(row) })
  const select = { inheritAttrs: false, setup: (_, { attrs, slots }) => () => h('picker-input', {
    onChoose: attrs.onChange, disabled: attrs.disabled,
  }, [...(slots.default?.() || []), ...(slots.footer?.() || [])]) }
  const option = { inheritAttrs: false, setup: (_, { attrs, slots }) => () => h('picker-option', attrs, slots.default?.()) }
  const mounted = mountComponent(t, component, props, undefined, { ElSelect: select, ElOptionGroup: slotShell, ElOption: option, ElButton: slotShell })
  return { ...mounted, props, chosen, choose: row => mounted.find(node => node.type === 'picker-input')[0].props.onChoose(row) }
}

test('mounted picker distinguishes two companies from two contacts and verifies the exact chosen company', async t => {
  const calls = []
  const ui = fixture(t, async params => { calls.push(params); return { company_id: params.customer_id, status: 'active', company_name: 'Hajra Omanovic' } })
  assert.match(ui.text(), /2 位客户.*2 位联系人/)
  assert.equal(ui.find(node => node.props?.class === 'customer-group-heading').length, 2)
  await ui.choose(contact('9001'))
  assert.deepEqual(calls, [{ customer_id: '9001', private_only: true, sales_user_id: 16 }])
  assert.equal(ui.chosen[0].kind, 'contact')
  assert.equal(ui.chosen[0].company_id, '9001')
})

test('mounted missing group disappears with its contacts and count while preserving the prior customer', async t => {
  const ui = fixture(t, async params => ({ company_id: params.customer_id, status: 'missing' }))
  ui.props.modelValue = company('9001')
  await nextTick()
  await ui.choose(contact('9002'))
  await nextTick()
  assert.equal(ui.props.modelValue.company_id, '9001')
  assert.equal(ui.chosen.length, 0)
  assert.doesNotMatch(ui.text(), /9002|小满已失效/)
  assert.match(ui.text(), /1 位客户.*1 位联系人/)
  assert.equal(ui.find(node => node.type === 'picker-option').length, 2)
  ui.props.options = [company('9001'), contact('9001'), company('9002'), contact('9002')]
  await nextTick()
  assert.doesNotMatch(ui.text(), /9002/)
  assert.equal(ui.find(node => node.type === 'picker-option').length, 2)
})

test('all confirmed missing groups produce an empty list with zero visible customers', async t => {
  const ui = fixture(t, async params => ({ company_id: params.customer_id, status: 'missing' }))
  await ui.choose(company('9001'))
  await ui.choose(company('9002'))
  await nextTick()
  assert.equal(ui.find(node => node.type === 'picker-option').length, 0)
  assert.match(ui.text(), /0 位客户/)
  assert.doesNotMatch(ui.text(), /位联系人/)
})

test('a transient verification failure keeps both groups visible and retryable', async t => {
  let failing = true
  const ui = fixture(t, async params => {
    if (failing) throw new Error('Synthetic network outage')
    return { company_id: params.customer_id, status: 'active', company_name: 'Hajra Omanovic' }
  })
  await ui.choose(company('9002'))
  await nextTick()
  assert.match(ui.text(), /9002/)
  assert.equal(ui.find(node => node.type === 'picker-option').length, 4)
  failing = false
  await ui.choose(company('9002'))
  assert.equal(ui.props.modelValue.company_id, '9002')
})

test('closing a retained drawer cancels late verification before it can fill a closed order', async t => {
  const request = deferred()
  const ui = fixture(t, () => request.promise)
  const pending = ui.choose(contact('9001'))
  await nextTick()
  ui.props.active = false
  await nextTick()
  request.resolve({ company_id: '9001', status: 'active', company_name: 'Hajra Omanovic' })
  assert.equal(await pending, false)
  assert.equal(ui.props.modelValue, null)
  assert.deepEqual(ui.chosen, [])
  ui.props.active = true
  await nextTick()
  assert.doesNotMatch(ui.text(), /正在核对/)
})
