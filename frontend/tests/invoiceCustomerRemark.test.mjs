import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import * as settlement from '../src/views/invoice/composables/invoiceSettlement.js'
import * as state from '../src/views/invoice/composables/invoiceEditorState.js'
import * as pricing from '../src/views/invoice/composables/accessoryPricing.js'
import * as money from '../src/utils/money.js'

const source = readFileSync(new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url), 'utf8')
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const customer = id => ({ company_id: id, company_name: `Customer ${id}` })
const defaults = remark => ({ remark, customer_grade: 'A', contact_name: 'Alice', contact_phone: '123', contact_email: 'a@example.test', delivery_address: 'Address' })

async function harness(request = async () => defaults('上单备注'), createRequest, invoiceData = {}, confirm = async () => {}) {
  const saved = [], warnings = [], confirmations = [], synced = []
  const api = Object.fromEntries(['checkInvoiceNo', 'createInvoice', 'createInvoiceFromScreenshot',
    'getCustomerContactDefaults', 'getCustomerRule', 'getInvoice', 'getInvoiceAssignees',
    'getInvoiceMerchandisers', 'getPreviousInvoiceNo', 'searchInvoiceCustomerOptions',
    'suggestInvoiceNo', 'updateInvoice'].map(name => [name, async () => ({})]))
  Object.assign(api, {
    getCustomerContactDefaults: request, getCustomerRule: async () => null,
    getInvoice: async id => ({ ...state.emptyInvoiceForm(), ...defaults('本单已保存备注'), id, customer_id: 'C1', ...invoiceData }),
    createInvoice: async payload => { saved.push(payload); return createRequest ? createRequest(payload) : { ...payload, id: 10 } },
    updateInvoice: async (id, payload) => { saved.push(payload); return { ...payload, id } },
  })
  const imports = {
    vue,
    '@/utils/money': money,
    '@/utils/feedback': { msgWarning: message => warnings.push(message), msgSuccessText() {}, alertAction() {},
      confirmAction: async message => { confirmations.push(message); return confirm() },
      isFeedbackCancelled: error => ['cancel', 'close'].includes(error) },
    '@/api/invoice': api,
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, hasPermission: () => true }) },
    './useLinkedInvoiceSync': { useLinkedInvoiceSync: () => ({ load() {}, operation: vue.ref(null), busy: vue.ref(false), loading: vue.ref(false) }) },
    './invoiceReceiptState': { invoiceOrderSignature: payload => JSON.stringify(payload) },
    './invoiceSyncFlow': { INVOICE_SYNC_OUTCOME: { SUCCESS: 'success' }, validateThenSync: async id => { synced.push(id); return 'success' } },
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
  return { editor, saved, warnings, confirmations, synced, stop: () => scope.stop() }
}
async function run(fn, request) {
  const h = await harness(request)
  try { await fn(h) } finally { h.stop() }
}

test('complete customer details collapse, can reopen, and remain expanded while filling a cleared field', () => run(async h => {
  assert.equal(h.editor.contactDetailsExpanded.value, true)
  await h.editor.onCustomerChange(customer('C1'))
  assert.equal(h.editor.contactDetailsComplete.value, true)
  assert.equal(h.editor.contactDetailsExpanded.value, false)
  h.editor.contactDetailsExpanded.value = true
  h.editor.form.contact_email = ''
  assert.equal(h.editor.contactDetailsComplete.value, false)
  h.editor.form.contact_email = 'new@example.test'
  assert.equal(h.editor.contactDetailsExpanded.value, true)
  await h.editor.onCustomerChange(null)
  assert.equal(h.editor.contactDetailsExpanded.value, true)
}))

for (const field of ['contact_name', 'contact_phone', 'contact_email', 'delivery_address']) {
  for (const blank of ['', '  ', null]) {
    test(`customer with ${field}=${JSON.stringify(blank)} stays expanded`, () => run(async h => {
      await h.editor.onCustomerChange(customer('C1'))
      assert.equal(h.editor.contactDetailsComplete.value, false)
      assert.equal(h.editor.contactDetailsExpanded.value, true)
    }, async () => ({ ...defaults(''), [field]: blank })))
  }
}

test('same-company explicit contact completeness overrides the previous snapshot', () => run(async h => {
  await h.editor.onCustomerChange(customer('C1'))
  await h.editor.onCustomerChange({ ...customer('C1'), kind: 'contact', name: 'Bob', tel: '', email: 'b@example.test' })
  assert.equal(h.editor.contactDetailsExpanded.value, true)
  await h.editor.onCustomerChange({ ...customer('C1'), kind: 'contact', name: 'Bob', tel: '456', email: 'b@example.test' })
  assert.equal(h.editor.contactDetailsExpanded.value, false)
}))

test('late complete customer response cannot collapse the current incomplete customer', async () => {
  const first = deferred()
  await run(async h => {
    const pending = h.editor.onCustomerChange(customer('C1'))
    await h.editor.onCustomerChange(customer('C2'))
    first.resolve(defaults('old'))
    await pending
    assert.equal(h.editor.form.customer_id, 'C2')
    assert.equal(h.editor.contactDetailsExpanded.value, true)
  }, id => id === 'C1' ? first.promise : Promise.resolve({ ...defaults(''), contact_phone: '' }))
})

for (const invoiceData of [{}, { contact_phone: '' }]) {
  test(`edit uses stored contact completeness ${JSON.stringify(invoiceData)}`, async () => {
    const h = await harness(async () => defaults(''), undefined, invoiceData)
    try {
      await h.editor.openEdit(7)
      assert.equal(h.editor.contactDetailsExpanded.value, Boolean('contact_phone' in invoiceData))
    } finally { h.stop() }
  })
}

test('collapsed contact values and shipping fee survive save and edit readback', () => run(async h => {
  await h.editor.onCustomerChange(customer('C1'))
  Object.assign(h.editor.form, { express_channel: 'FEDEX', shipping_fee: 123.45 })
  assert.equal(h.editor.contactDetailsExpanded.value, false)
  assert.equal(h.editor.formTotal.value, 123.45)
  await h.editor.saveDraft()
  assert.equal(h.saved[0].shipping_fee, 123.45)
  for (const field of ['contact_name', 'contact_phone', 'contact_email', 'delivery_address']) {
    assert.equal(h.saved[0][field], defaults('')[field])
  }
  assert.equal(h.editor.form.shipping_fee, 123.45)
  assert.equal(h.editor.contactDetailsExpanded.value, false)
}))

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

test('active presale blocks save and save-and-sync before sending any document write', () => run(async h => {
  await h.editor.onCustomerChange(customer('C1'))
  Object.assign(h.editor.form, defaults(''), { id: 981, order_type: 'presale', express_channel: 'FEDEX',
    presale_edit_blocked_reason: '请使用登记预售收款，提交后无需保存主单' })
  await h.editor.saveDraft()
  await h.editor.saveAndSync()
  assert.equal(h.saved.length, 0)
  assert.deepEqual(h.warnings, Array(2).fill(h.editor.form.presale_edit_blocked_reason))
  assert.equal(h.editor.saveAndSyncSubmitting.value, false)
}))

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

test('order write locks receipt editing until the response settles and prevents duplicate writes', async () => {
  const pending = deferred()
  const h = await harness(undefined, () => pending.promise)
  try {
    Object.assign(h.editor.form, defaults('order'), { express_channel: 'FEDEX' })
    const saving = h.editor.saveDraft()
    assert.equal(h.editor.receiptLocked.value, true)
    await h.editor.saveDraft()
    await Promise.resolve()
    assert.equal(h.saved.length, 1)
    pending.resolve({ ...h.saved[0], id: 10 })
    await saving
    assert.equal(h.editor.receiptLocked.value, false)
  } finally { h.stop() }
})

test('remark editing prevents ordinary order persistence until saved or cancelled', () => run(async h => {
  Object.assign(h.editor.form, defaults('order'), { express_channel: 'FEDEX', receipt_remark_editing: true })
  assert.equal(await h.editor.saveDraft(), null)
  assert.equal(h.saved.length, 0)
  assert.equal(h.editor.receiptLocked.value, false)
  assert.ok(h.warnings.includes('请先保存或取消回款备注编辑'))
}))

for (const orderType of ['presale', 'stock', 'production']) {
  test(`${orderType} accessory-only save omits the default blank hair row`, () => run(async h => {
    const accessory = pricing.normalizeAccessoryRow({ product_id: 'A1', sku_id: 7,
      product_name: 'Clip', quantity: 3600, price_per_piece: 2, discount_amount: 5 })
    Object.assign(h.editor.form, defaults('accessory only'), { order_type: orderType, express_channel: 'FEDEX',
      items: [state.emptyHairRow(orderType === 'production'), accessory] })
    assert.ok(await h.editor.saveDraft())
    assert.equal(h.saved.length, 1)
    assert.equal(h.saved[0].items.length, 1)
    assert.equal(h.saved[0].items[0].product_kind, 'accessory')
    assert.equal(h.saved[0].items[0].quantity, 3600)
    assert.equal(h.saved[0].items[0].discount_amount, -5)
    assert.equal(h.editor.quantityErrorRow.value, null)
  }))
}

test('mixed hair/accessory save ignores added blank placeholders while preserving all entered rows', () => run(async h => {
  Object.assign(h.editor.form, defaults('mixed'), { order_type: 'presale', express_channel: 'FEDEX', items: [
    state.emptyHairRow(), { ...state.emptyHairRow(), product_name: 'Hair', quantity: 2, price_per_piece: 50 },
    pricing.normalizeAccessoryRow({ product_name: 'Clip', quantity: 3600, price_per_piece: 2 }), state.emptyHairRow(),
  ] })
  await h.editor.saveDraft()
  assert.deepEqual(h.saved[0].items.map(row => row.quantity), [2, 3600])
}))

test('accessory-only save and sync proceeds past the blank hair placeholder', () => run(async h => {
  Object.assign(h.editor.form, defaults('accessory'), { order_type: 'presale', express_channel: 'FEDEX',
    items: [state.emptyHairRow(), pricing.normalizeAccessoryRow({ product_name: 'Clip', quantity: 3600, price_per_piece: 2 })] })
  await h.editor.saveAndSync()
  assert.equal(h.saved.length, 1)
  assert.equal(h.saved[0].items.length, 1)
  assert.equal(h.saved[0].items[0].quantity, 3600)
}))

for (const quantity of [null, undefined, NaN, Infinity, 0, -1, 1.5]) {
  test(`presale save rejects invalid quantity ${String(quantity)} without creating an invoice`, () => run(async h => {
    Object.assign(h.editor.form, defaults('order'), { order_type: 'presale', express_channel: 'FEDEX',
      items: [{ ...state.emptyHairRow(), model: 'Started model', quantity },
        { ...state.emptyHairRow(), product_display: 'Filled product', quantity: 3, price_per_piece: 50 }] })
    assert.equal(await h.editor.saveDraft(), null)
    assert.equal(h.saved.length, 0)
    assert.equal(h.editor.quantityErrorRow.value, h.editor.form.items[0])
    assert.match(h.warnings.at(-1), /Started model.*数量.*正整数/)
    assert.equal(h.editor.form.items.length, 2)
    assert.equal(h.editor.form.items[1].quantity, 3)
  }))
}

test('save and sync locates an incomplete old row hidden by filled imported rows; correction saves original quantities', () => run(async h => {
  Object.assign(h.editor.form, defaults('order'), { order_type: 'presale', express_channel: 'FEDEX',
    items: [{ ...state.emptyHairRow(), model: 'Started model' },
      ...Array.from({ length: 21 }, () => ({ ...state.emptyHairRow(), quantity: 2, price_per_piece: 50 }))] })
  await h.editor.saveAndSync()
  assert.equal(h.saved.length, 0)
  assert.equal(h.editor.quantityErrorRow.value, h.editor.form.items[0])
  h.editor.form.items[0].quantity = 4
  await vue.nextTick()
  assert.equal(h.editor.quantityErrorRow.value, null)
  await h.editor.saveDraft()
  assert.equal(h.saved.length, 1)
  assert.equal(h.saved[0].items[0].quantity, 4)
  assert.equal(h.saved[0].items.length, 22)
  assert.ok(h.saved[0].items.slice(1).every(row => row.quantity === 2))
}))


for (const action of ['cancel', 'close', 'confirm']) {
  for (const amount of [0, null, '0.00']) {
    test(`zero receipt ${amount}: ${action} gates every save and sync`, async () => {
      const pending = deferred()
      const h = await harness(undefined, undefined, {}, async () => {
        await pending.promise
        if (action !== 'confirm') throw action
      })
      try {
        await h.editor.onCustomerChange(customer('C1'))
        Object.assign(h.editor.form, { express_channel: 'FEDEX', receipt_draft: { amount, status: 'draft' } })
        const submit = h.editor.saveAndSync()
        assert.deepEqual(h.confirmations, ['当前回款金额为0，是否确认提交？'])
        assert.equal(h.saved.length, 0)
        assert.equal(h.synced.length, 0)
        await h.editor.saveAndSync()
        assert.equal(h.confirmations.length, 1)
        pending.resolve()
        await submit
        assert.equal(h.saved.length, action === 'confirm' ? 1 : 0)
        assert.equal(h.synced.length, action === 'confirm' ? 1 : 0)
        assert.equal(h.editor.saveAndSyncSubmitting.value, false)
      } finally { h.stop() }
    })
  }
}

test('positive receipt and draft-only save do not prompt for zero payment', async () => {
  const h = await harness()
  try {
    await h.editor.onCustomerChange(customer('C1'))
    Object.assign(h.editor.form, { express_channel: 'FEDEX', shipping_fee: 1, receipt_draft: { amount: 1, status: 'draft' } })
    await h.editor.saveAndSync()
    h.editor.form.receipt_draft.amount = 0
    await h.editor.saveDraft()
    assert.equal(h.confirmations.length, 0)
    assert.equal(h.saved.length, 2)
    assert.equal(h.synced.length, 1)
  } finally { h.stop() }
})

for (const action of ['saveDraft', 'saveAndSync']) {
  for (const id of [null, 1226]) {
    test(`${action} blocks excess receipt before ${id ? 'update' : 'create'} request`, () => run(async h => {
      await h.editor.onCustomerChange(customer('C1'))
      Object.assign(h.editor.form, { id, order_type: 'stock', express_channel: 'FEDEX', shipping_fee: 5082.14,
        receipt_draft: { amount: 5377.30, status: 'draft' } })
      await h.editor[action]()
      assert.equal(h.saved.length, 0)
      assert.equal(h.synced.length, 0)
      assert.match(h.warnings.at(-1), /回款金额.*5,377.30.*订单总额.*5,082.14.*USD/)
      assert.equal(h.editor.form.receipt_draft.amount, 5377.30)
      h.editor.form.receipt_draft.amount = 5082.14
      await h.editor[action]()
      assert.equal(h.saved.length, 1)
      assert.equal(h.synced.length, action === 'saveAndSync' ? 1 : 0)
    }))
  }
}

for (const receipt of [{ amount: 100.01 }, { amount: 100.01, status: 'draft' }]) {
  test(`legacy draft status ${receipt.status} still validates lowered total`, () => run(async h => {
    await h.editor.onCustomerChange(customer('C1'))
    Object.assign(h.editor.form, { express_channel: 'FEDEX', shipping_fee: 100, receipt_draft: receipt })
    assert.equal(await h.editor.saveDraft(), null)
    assert.equal(h.saved.length, 0)
    assert.match(h.warnings.at(-1), /回款金额/)
  }))
}

for (const scenario of [
  { order_type: 'presale', receipt_draft: { amount: 200, status: 'draft' } },
  { order_type: 'stock', receipt_draft: { amount: 200, status: 'converted' } },
  { order_type: 'stock', receipt_draft: { amount: '100.00', status: 'draft' } },
  { order_type: 'stock', receipt_draft: null },
]) {
  test(`save preserves receipt boundary ${JSON.stringify(scenario)}`, () => run(async h => {
    await h.editor.onCustomerChange(customer('C1'))
    Object.assign(h.editor.form, { express_channel: 'FEDEX', shipping_fee: 100, ...scenario })
    assert.ok(await h.editor.saveDraft())
    assert.equal(h.saved.length, 1)
  }))
}
