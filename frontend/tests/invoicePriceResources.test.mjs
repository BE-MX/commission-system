import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { viewController } from './helpers/viewController.mjs'
import * as presentation from '../src/views/invoice/invoicePricePresentation.js'
import * as accessoryState from '../src/views/invoice/composables/accessoryPriceConfigState.js'
import * as errors from '../src/utils/errors.js'
import { isAmount } from '../src/utils/validators.js'
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function prices(t, names, api) {
  return viewController(t, '../../src/views/invoice/InvoicePriceConfig.vue', names, {
    './invoicePricePresentation': presentation, '@/api/invoice': api,
    './composables/useInvoiceEditor': { customerLabel: row => row.company_name },
  })
}

for (const [key, method, loader] of [['stdResource', 'listStdPrices', 'loadStdPrices'], ['colorResource', 'listColorTypes', 'loadColorTypes'], ['ruleResource', 'listCustomerRules', 'loadRules'], ['customResource', 'listCustomProducts', 'loadCustom']]) {
  test(`price ${key} first error, late-response protection and stale retry execute the real controller`, async t => {
    const queue = [], { vm } = prices(t, key + ',' + loader, { [method]: (...args) => { const request = deferred(); queue.push(request); assert.equal(args.at(-1).suppressToast, true); assert.ok(args.at(-1).signal); return request.promise } })
    const first = vm[loader](); queue[0].reject(Error('offline')); assert.equal(await first, false)
    assert.equal(vm[key].hasLoaded.value, false); assert.equal(vm[key].errorMessage.value, 'offline')
    const old = vm[loader](), latest = vm[loader](); queue[2].resolve({ items: [{ id: 'new' }] }); await latest
    queue[1].resolve({ items: [{ id: 'old' }] }); await old; assert.equal(vm[key].data.value[0].id, 'new')
    const failed = vm[loader](); queue[3].reject(Error('refresh offline')); await failed
    assert.equal(vm[key].isStale.value, true); assert.equal(vm[key].data.value[0].id, 'new')
  })
}

test('standard price series options retain every series while the visible filter is explicitly submitted', async t => {
  const { vm } = prices(t, 'stdFilter,stdPrices,stdSeriesOptions,loadStdPrices,searchStd,resetStd', {
    listStdPrices: async params => { assert.deepEqual(params, {}); return { items: [{ id: 1, series_grade: 'A', price: 1.2345 }, { id: 2, series_grade: 'B' }] } },
  })
  await vm.loadStdPrices(); vm.stdFilter.value = 'A'; assert.equal(vm.stdPrices.value.length, 2)
  await vm.searchStd(); assert.equal(vm.stdPrices.value.length, 1); assert.deepEqual(vm.stdSeriesOptions.value, ['A', 'B'])
  vm.stdFilter.value = 'B'; await vm.loadStdPrices(); assert.equal(vm.stdPrices.value[0].id, 1); assert.equal(vm.stdPrices.value[0].price, 1.2345)
  await vm.resetStd(); assert.equal(vm.stdPrices.value.length, 2)
})

test('rule and custom mutations refresh their submitted keyword; unchanged monetary payload survives failed refresh', async t => {
  const calls = [], writes = []; let failed = false
  const { vm, messages } = prices(t, 'ruleKeyword,searchRules,loadRules,ruleResource,ruleDialog,saveRule,customKeyword,searchCustom,loadCustom,runReconcile', {
    listCustomerRules: async params => { calls.push({ kind: 'rule', params }); if (failed) throw Error('price read offline'); return { items: [{ id: 1 }] } },
    upsertCustomerRule: async payload => { writes.push({ ...payload }); failed = true },
    listCustomProducts: async params => { calls.push({ kind: 'custom', params }); return { items: [] } },
    reconcileCustomProducts: async () => ({ checked: 1, linked: 1 }),
  })
  vm.ruleKeyword.value = 'applied'; await vm.searchRules(); vm.ruleKeyword.value = 'draft'
  vm.ruleDialog.form = { customer_id: 'customer-1', adjust_value: 1.23456, enabled: false }; await vm.saveRule(); await Promise.resolve()
  assert.equal(calls.findLast(call => call.kind === 'rule').params.keyword, 'applied')
  assert.equal(writes[0].adjust_value, 1.23456); assert.equal(writes[0].enabled, false); assert.ok(messages.includes('保存'))
  assert.equal(vm.ruleResource.errorMessage.value, 'price read offline')
  vm.customKeyword.value = 'applied-custom'; await vm.searchCustom(); vm.customKeyword.value = 'draft-custom'; await vm.runReconcile()
  assert.equal(calls.at(-1).params.keyword, 'applied-custom')
})

test('rule customer candidate query ignores former queries and closing invalidates pending results', async t => {
  const queue = [], { vm } = prices(t, 'ruleCustomerResource,ruleCustomerOptions,ruleDialog,searchRuleCustomers', { searchInvoiceCustomers: () => { const request = deferred(); queue.push(request); return request.promise } })
  vm.ruleDialog.visible = true
  const old = vm.searchRuleCustomers('A'), latest = vm.searchRuleCustomers('B')
  queue[1].resolve({ items: [{ id: 'B' }] }); await latest; queue[0].resolve({ items: [{ id: 'A' }] }); await old
  assert.equal(vm.ruleCustomerOptions.value[0].id, 'B')
  const closed = vm.searchRuleCustomers('C'); vm.ruleDialog.visible = false; await nextTick(); queue[2].resolve({ items: [{ id: 'C' }] }); await closed
  assert.deepEqual(vm.ruleCustomerOptions.value, [])
})

test('accessory list reports first and stale failures while preserving submitted keyword and exact SKU write precision', async t => {
  const calls = [], writes = []; let failed = true
  const { vm, messages } = viewController(t, '../../src/views/invoice/components/AccessoryPriceConfig.vue', 'keyword,rows,listErrorMessage,hasLoaded,searchRows,loadRows,dialog,saveRow', {
    '../composables/accessoryPriceConfigState': accessoryState, '@/utils/errors': errors, '@/utils/validators': { isAmount },
    '@/api/invoice': {
      listAccessoryPrices: async (params, config) => { calls.push(params); assert.equal(config.suppressToast, true); assert.ok(config.signal); if (failed) throw Error('accessory offline'); return { items: [{ id: 1, standard_price: '1.23' }] } },
      saveAccessoryPrice: async payload => { writes.push(payload); failed = true },
    },
  })
  assert.equal(await vm.loadRows(), false); assert.equal(vm.hasLoaded.value, false); assert.equal(vm.listErrorMessage.value, 'accessory offline')
  failed = false; vm.keyword.value = 'applied'; await vm.searchRows(); vm.keyword.value = 'draft'
  vm.dialog.candidate = { sku_id: 'sku' }; vm.dialog.form = { product_id: 'product', sku_id: 'sku', price: 1.239, currency: 'USD' }
  await vm.saveRow()
  assert.equal(calls.at(-1).keyword, 'applied'); assert.equal(writes[0].price, '1.24'); assert.equal(writes[0].sku_id, 'sku')
  assert.ok(messages.includes('保存')); assert.equal(vm.rows.value[0].id, 1); assert.equal(vm.listErrorMessage.value, 'accessory offline')
})
