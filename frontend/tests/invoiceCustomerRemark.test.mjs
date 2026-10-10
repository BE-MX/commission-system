import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import * as settlement from '../src/views/invoice/composables/invoiceSettlement.js'
import * as state from '../src/views/invoice/composables/invoiceEditorState.js'
import * as pricing from '../src/views/invoice/composables/accessoryPricing.js'

const source = readFileSync(new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url), 'utf8')
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const customer = id => ({ company_id: id, company_name: `Customer ${id}` })
const defaults = remark => ({ remark, customer_grade: 'A', contact_name: 'Alice', contact_phone: '123', contact_email: 'a@example.test', delivery_address: 'Address' })

async function harness(request = async () => defaults('上单备注')) {
  const saved = [], warnings = []
  const api = Object.fromEntries(['checkInvoiceNo', 'createInvoice', 'createInvoiceFromScreenshot',
    'getCustomerContactDefaults', 'getCustomerRule', 'getInvoice', 'getInvoiceAssignees',
    'getInvoiceMerchandisers', 'getPreviousInvoiceNo', 'searchInvoiceCustomerOptions',
    'suggestInvoiceNo', 'updateInvoice'].map(name => [name, async () => ({})]))
  Object.assign(api, {
    getCustomerContactDefaults: request, getCustomerRule: async () => null,
    getInvoice: async id => ({ ...state.emptyInvoiceForm(), ...defaults('本单已保存备注'), id, customer_id: 'C1' }),
    createInvoice: async payload => { saved.push(payload); return { ...payload, id: 10 } },
  })
  const imports = {
    vue,
    '@/utils/feedback': { msgWarning: message => warnings.push(message), msgSuccessText() {}, alertAction() {} },
    '@/api/invoice': api,
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, hasPermission: () => true }) },
    './useLinkedInvoiceSync': { useLinkedInvoiceSync: () => ({ load() {}, operation: vue.ref(null), busy: vue.ref(false), loading: vue.ref(false) }) },
    './invoiceReceiptState': { invoiceOrderSignature: payload => JSON.stringify(payload) },
    './invoiceSyncFlow': { INVOICE_SYNC_OUTCOME: {}, validateThenSync() {} },
    './invoiceSettlement': settlement,
    './accessoryPricing': pricing,
    './invoiceEditorState': state,
    './useInvoiceCustomerSearch': {
      customerOptionKey: option => `customer:${option.company_id}`,
      useInvoiceCustomerSearch: () => ({ options: vue.ref([]), loading: vue.ref(false), total: vue.ref(0), hasMore: vue.ref(false), search() {}, reset() {} }),
    },
    './useInvoiceAccessories': { useInvoiceAccessories: form => ({
      hairItems: vue.computed(() => form.items), hairAmount: vue.ref(0), hairDiscount: vue.ref(0),
      accessoryAmount: vue.ref(0), accessoryDiscountTotal: vue.ref(0),
      invalidateCustomerContext() {}, refreshAccessoryPrices: async () => {},
    }) },
    './useInvoiceHairItems': { useInvoiceHairItems: () => ({ refreshLinePrice: async () => {}, addBlankLine() {} }) },
  }
  const context = vm.createContext({})
  const module = new vm.SourceTextModule(source, { context })
  await module.link(name => {
    const exports = imports[name]
    assert.ok(exports, `missing mock: ${name}`)
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  const scope = vue.effectScope()
  const editor = scope.run(() => module.namespace.useInvoiceEditor())
  return { editor, saved, warnings, stop: () => scope.stop() }
}
async function run(fn, request) {
  const h = await harness(request)
  try { await fn(h) } finally { h.stop() }
}

test('select customer fills previous remark and saves the manually edited text', () => run(async h => {
  await h.editor.onCustomerChange(customer('C1'))
  assert.equal(h.editor.form.remark, '上单备注')
  h.editor.form.remark = '修改内容\n新要求'
  h.editor.form.express_channel = 'FEDEX'
  await h.editor.saveDraft()
  assert.equal(h.saved.length, 1)
  assert.equal(h.saved[0].remark, '修改内容\n新要求')
  assert.equal(h.editor.form.remark, '修改内容\n新要求')
}))

test('no-history customer starts empty and can save', () => run(async h => {
  h.editor.form.remark = '前一个客户备注'
  await h.editor.onCustomerChange(customer('NEW'))
  assert.equal(h.editor.form.remark, '')
  Object.assign(h.editor.form, defaults(''), { express_channel: 'FEDEX' })
  await h.editor.saveDraft()
  assert.equal(h.saved.length, 1)
  assert.equal(h.saved[0].remark, '')
}, async () => ({ remark: '', customer_grade: null })))

for (const manual of ['手动填写', '']) {
  test(`manual remark ${JSON.stringify(manual)} survives a late response`, () => {
    const d = deferred()
    return run(async h => {
      const pending = h.editor.onCustomerChange(customer('C1'))
      h.editor.form.remark = '输入后再修改'
      h.editor.form.remark = manual
      d.resolve(defaults('迟到的上单备注'))
      await pending
      assert.equal(h.editor.form.remark, manual)
    }, () => d.promise)
  })
}

test('switching customers clears old remark immediately and ignores stale response', () => {
  const a = deferred(), b = deferred()
  return run(async h => {
    h.editor.form.remark = '旧内容'
    const first = h.editor.onCustomerChange(customer('C1'))
    assert.equal(h.editor.form.remark, '')
    const second = h.editor.onCustomerChange(customer('C2'))
    b.resolve(defaults('客户二'))
    await second
    a.resolve(defaults('客户一'))
    await first
    assert.equal(h.editor.form.remark, '客户二')
  }, id => id === 'C1' ? a.promise : b.promise)
})

test('same-company contact change preserves manual remark and clearing customer empties it', () => run(async h => {
  await h.editor.onCustomerChange(customer('C1'))
  h.editor.form.remark = '本单手动备注'
  await h.editor.onCustomerChange({ ...customer('C1'), kind: 'contact', name: 'Bob' })
  assert.equal(h.editor.form.remark, '本单手动备注')
  await h.editor.onCustomerChange(null)
  assert.equal(h.editor.form.remark, '')
}))

test('resetting to an existing order ignores pending defaults and preserves stored remark', () => {
  const d = deferred()
  return run(async h => {
    const pending = h.editor.onCustomerChange(customer('C1'))
    await h.editor.openEdit(7)
    d.resolve(defaults('迟到上单备注'))
    await pending
    assert.equal(h.editor.form.remark, '本单已保存备注')
    await h.editor.onCustomerChange(customer('C2'))
    assert.equal(h.editor.form.remark, '本单已保存备注')
  }, () => d.promise)
})

test('failed optional defaults clears old remark and user can still fill and save', () => run(async h => {
  h.editor.form.remark = '旧客户备注'
  await h.editor.onCustomerChange(customer('C1'))
  assert.equal(h.editor.form.remark, '')
  Object.assign(h.editor.form, defaults('手动备注'), { express_channel: 'FEDEX' })
  h.editor.markCustomerGradeTouched()
  await h.editor.saveDraft()
  assert.equal(h.saved[0].remark, '手动备注')
}, async () => { throw Error('offline') }))

test('save waits for customer defaults while preserving the user remark', () => {
  const d = deferred()
  return run(async h => {
    const changing = h.editor.onCustomerChange(customer('C1'))
    h.editor.form.remark = '立即填写并保存'
    h.editor.form.express_channel = 'FEDEX'
    const saving = h.editor.saveDraft()
    assert.equal(h.saved.length, 0)
    d.resolve(defaults('历史备注'))
    await Promise.all([changing, saving])
    assert.equal(h.saved.length, 1)
    assert.equal(h.saved[0].remark, '立即填写并保存')
  }, () => d.promise)
})

for (const entry of ['openCreate', 'openLegacyCreate']) {
  test(`${entry} starts empty and fills the selected customer's remark`, () => run(async h => {
    h.editor.form.remark = '上个抽屉残留'
    await h.editor[entry]()
    assert.equal(h.editor.form.remark, '')
    await h.editor.onCustomerChange(customer('C1'))
    assert.equal(h.editor.form.remark, '上单备注')
  }))
}

test('salesperson switch clears new-order remark and invalidates pending defaults', () => {
  const d = deferred()
  return run(async h => {
    const pending = h.editor.onCustomerChange(customer('C1'))
    h.editor.form.remark = '客户一手填'
    await h.editor.onSalesUserChange()
    assert.equal(h.editor.form.remark, '')
    d.resolve(defaults('旧客户历史备注'))
    await pending
    assert.equal(h.editor.form.remark, '')
  }, () => d.promise)
})

test('screenshot customer defaults also fill the latest remark', () => run(async h => {
  await h.editor.applyScreenshotPreview({ ready: true, invoice_patch: {
    ...state.emptyInvoiceForm(), customer_id: 'C1', customer_name: 'Customer C1',
  } })
  assert.equal(h.editor.form.remark, '上单备注')
}))
