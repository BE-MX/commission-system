import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'
import * as settlement from '../src/views/invoice/composables/invoiceSettlement.js'
import * as state from '../src/views/invoice/composables/invoiceEditorState.js'
import * as pricing from '../src/views/invoice/composables/accessoryPricing.js'
import * as money from '../src/utils/money.js'
import { newRequestKey } from '../src/utils/requestKey.js'
import * as routeState from '../src/views/commerce-transition/routeState.js'

const source = readFileSync(new URL('../src/views/invoice/composables/useInvoiceEditor.js', import.meta.url), 'utf8')
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const customer = id => ({ company_id: id, company_name: `Customer ${id}` })
const defaults = remark => ({ remark, customer_grade: 'A', contact_name: 'Alice', contact_phone: '123', contact_email: 'a@example.test', delivery_address: 'Address' })

async function harness(request = async () => defaults('上单备注'), createRequest, invoiceData = {}, confirm = async () => {}, options = {}) {
  const saved = [], warnings = [], confirmations = [], synced = []
  const api = Object.fromEntries(['checkInvoiceNo', 'createInvoice', 'createInvoiceFromScreenshot',
    'getCustomerContactDefaults', 'getCustomerRule', 'getInvoice', 'getInvoiceAssignees',
    'getInvoiceMerchandisers', 'getPreviousInvoiceNo', 'searchInvoiceCustomerOptions',
    'suggestInvoiceNo', 'updateInvoice'].map(name => [name, async () => ({})]))
  Object.assign(api, {
    getCustomerContactDefaults: request, getCustomerRule: async () => null,
    getInvoice: async id => options.getInvoice ? options.getInvoice(id) : ({ ...state.emptyInvoiceForm(), ...defaults('本单已保存备注'), id, customer_id: 'C1', ...invoiceData }),
    createInvoice: async payload => { saved.push(payload); return createRequest ? createRequest(payload) : { ...payload, id: 10 } },
    updateInvoice: async (id, payload) => { saved.push(payload); return { ...payload, id } },
  })
  const imports = {
    vue,
    '@/utils/money': money,
    '@/utils/requestKey': { newRequestKey },
    '@/views/commerce-transition/routeState': routeState,
    '@/utils/feedback': { msgWarning: message => warnings.push(message), msgSuccessText() {}, alertAction() {},
      confirmAction: async message => { confirmations.push(message); return confirm() },
      isFeedbackCancelled: error => ['cancel', 'close'].includes(error) },
    '@/api/invoice': api,
    '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, hasPermission: () => true }) },
    './useLinkedInvoiceSync': { useLinkedInvoiceSync: onSaved => {
      const operation = vue.ref(null)
      let activeId
      return { load(id) { activeId = id }, operation, busy: vue.ref(false), loading: vue.ref(false),
        save: async (id, payload) => ({ ...payload, id }), run: async () => {
          operation.value = { status: options.linkedStatus || 'done' }
          await onSaved(activeId)
          return operation.value
        } }
    } },
    './invoiceReceiptState': { invoiceOrderSignature: payload => JSON.stringify(payload) },
    './invoiceSyncFlow': { INVOICE_SYNC_OUTCOME: { SUCCESS: 'success' }, validateThenSync: async id => { synced.push(id); return options.outcome || 'success' } },
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
  const context = vm.createContext(options.window ? { window: options.window } : {})
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


test('saved order closes directly; changes and reverted changes use the persisted baseline', async () => {
  const h = await harness()
  try {
    await h.editor.openEdit(12)
    await vue.nextTick()
    assert.equal(h.editor.hasUnsavedChanges.value, false)
    const original = h.editor.form.remark
    h.editor.form.remark = 'unsaved'
    assert.equal(h.editor.hasUnsavedChanges.value, true)
    h.editor.form.remark = original
    assert.equal(h.editor.hasUnsavedChanges.value, false)
    await h.editor.closeEditor()
    assert.equal(h.confirmations.length, 0)
    assert.equal(h.editor.drawerVisible.value, false)
  } finally { h.stop() }
})

for (const action of ['cancel', 'close', 'confirm']) {
  test(`dirty close ${action} preserves content unless explicitly discarded`, async () => {
    const pending = deferred()
    const h = await harness(undefined, undefined, {}, async () => {
      await pending.promise
      if (action !== 'confirm') throw action
    })
    try {
      await h.editor.openEdit(12)
      h.editor.form.remark = 'changed'
      let closed = 0
      const first = h.editor.beforeEditorClose(() => closed++)
      const second = h.editor.beforeEditorClose(() => closed++)
      assert.equal(h.confirmations.length, 1)
      pending.resolve()
      await Promise.all([first, second])
      assert.equal(closed, action === 'confirm' ? 2 : 0)
      assert.equal(h.editor.form.remark, 'changed')
    } finally { h.stop() }
  })
}

test('new legacy order and receipt-only edits are protected; browser handler is cleaned up', async () => {
  const listeners = new Map()
  const window = { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) }
  const h = await harness(undefined, undefined, {}, undefined, { window })
  try {
    assert.equal(listeners.size, 0)
    await h.editor.openLegacyCreate()
    assert.ok(listeners.has('beforeunload'))
    let prevented = false
    const event = { preventDefault: () => { prevented = true } }
    listeners.get('beforeunload')(event)
    assert.equal(prevented, true)
    assert.equal(event.returnValue, '')
    h.editor.legacyVisible.value = false
    assert.equal(listeners.size, 0)
    await h.editor.openEdit(12)
    assert.equal(listeners.size, 0)
    h.editor.form.receipt_draft = { amount: 20, remark: 'new receipt' }
    assert.ok(listeners.has('beforeunload'))
    h.editor.form.receipt_draft = null
    assert.equal(listeners.size, 0)
    h.editor.form.receipt_proof_dirty = true
    assert.ok(listeners.has('beforeunload'))
  } finally { h.stop() }
  assert.equal(listeners.size, 0)
})

test('in-flight save blocks closing and keeps edits made during the request dirty', async () => {
  const pending = deferred()
  const h = await harness(undefined, async payload => { await pending.promise; return { ...payload, id: 10 } })
  try {
    await h.editor.openCreate()
    await h.editor.onCustomerChange(customer('C1'))
    h.editor.form.express_channel = 'FEDEX'
    const saving = h.editor.saveDraft()
    await vue.nextTick()
    await h.editor.closeEditor()
    assert.equal(h.editor.drawerVisible.value, true)
    assert.equal(h.confirmations.length, 0)
    assert.match(h.warnings.at(-1), /请等待完成/)
    h.editor.form.remark = 'edited during save'
    pending.resolve()
    await saving
    assert.equal(h.editor.form.remark, 'edited during save')
    assert.equal(h.editor.hasUnsavedChanges.value, true)
  } finally { h.stop() }
})

for (const outcome of ['success', 'failed', 'duplicate']) {
  test(`ordinary sync ${outcome} only announces confirmed completion`, async () => {
    const h = await harness(undefined, undefined, {}, undefined, { outcome })
    try {
      await h.editor.openCreate()
      await h.editor.onCustomerChange(customer('C1'))
      Object.assign(h.editor.form, { express_channel: 'FEDEX', invoice_no: 'TEST-123' })
      await h.editor.saveAndSync()
      assert.equal(h.editor.syncCompletionMessage.value, outcome === 'success' ? 'TEST-123订单号已保存并同步完成' : '')
      assert.equal(h.editor.drawerVisible.value, outcome !== 'success')
      assert.equal(h.editor.hasUnsavedChanges.value, false)
    } finally { h.stop() }
  })
}

for (const linkedStatus of ['done', 'manual', 'uncertain', 'running', 'failed']) {
  test(`linked sync ${linkedStatus} only announces done`, async () => {
    const h = await harness(undefined, undefined, { xiaoman_order_id: 'remote', invoice_no: 'LINKED-123', express_channel: 'FEDEX' }, undefined, { linkedStatus })
    try {
      await h.editor.openEdit(12)
      h.editor.form.remark = 'changed'
      await h.editor.saveAndSync()
      assert.equal(h.editor.syncCompletionMessage.value, linkedStatus === 'done' ? 'LINKED-123订单号已保存并同步完成' : '')
    } finally { h.stop() }
  })
}


test('empty auto-initialized receipt and separately saved converted receipt remain clean', async () => {
  const h = await harness(undefined, undefined, { receipt_draft: null })
  try {
    await h.editor.openEdit(12)
    h.editor.form.receipt_draft = { amount: 0, bank_charge: 0, collection_date: '2026-10-23', payment_type: 'Other', purpose: 'ordinary', attachment_ids: [], remark: '', status: 'draft' }
    assert.equal(h.editor.hasUnsavedChanges.value, false)
    Object.assign(h.editor.form.receipt_draft, { status: 'converted', receipt_id: 1, amount: 100, attachment_ids: [2], remark: 'persisted independently' })
    assert.equal(h.editor.hasUnsavedChanges.value, false)
    h.editor.form.receipt_remark_editing = true
    assert.equal(h.editor.hasUnsavedChanges.value, true)
    h.editor.form.receipt_remark_editing = false
    h.editor.form.remark = 'unsaved order remark'
    assert.equal(h.editor.hasUnsavedChanges.value, true)
  } finally { h.stop() }
})

test('failed save keeps browser protection and never announces completion', async () => {
  const h = await harness(undefined, async () => { throw Error('network failure') })
  try {
    await h.editor.openCreate()
    await h.editor.onCustomerChange(customer('C1'))
    h.editor.form.express_channel = 'FEDEX'
    await assert.rejects(h.editor.saveAndSync(), /network failure/)
    assert.equal(h.editor.hasUnsavedChanges.value, true)
    assert.equal(h.editor.syncCompletionMessage.value, '')
    assert.equal(h.editor.drawerVisible.value, true)
    assert.equal(h.editor.editorBusy.value, false)
  } finally { h.stop() }
})


test('linked retry announces completion when the earlier save-and-sync finally reaches done', async () => {
  const options = { linkedStatus: 'running' }
  const h = await harness(undefined, undefined, { xiaoman_order_id: 'remote', invoice_no: 'RETRY-123', express_channel: 'FEDEX' }, undefined, options)
  try {
    await h.editor.openEdit(12)
    await h.editor.saveAndSync()
    assert.equal(h.editor.syncCompletionMessage.value, '')
    options.linkedStatus = 'done'
    await h.editor.retryLinked()
    assert.equal(h.editor.syncCompletionMessage.value, 'RETRY-123订单号已保存并同步完成')
  } finally { h.stop() }
})


test('unified local create retries the original request key after response loss and never syncs old APIs', async t => {
  let attempts = 0
  const h = await harness(undefined, async payload => {
    if (++attempts === 1) throw Error('response lost')
    return { ...payload, id: 123, authority_epoch: 1, commerce_version: 1 }
  })
  t.after(h.stop)
  Object.assign(h.editor.form, defaults('local draft'), { transaction_route: 'local', local_customer_id: 3, customer_id: 'ark:3', express_channel: 'FEDEX', items: [{ local_sku_id: 9, sku_id: 9, product_display: 'Local SKU', quantity: 1, price_per_piece: 0, total_price: 0 }] })
  await assert.rejects(h.editor.saveDraft(), /response lost/)
  await h.editor.saveDraft()
  assert.equal(h.saved.length, 2)
  assert.equal(h.saved[0].request_key, h.saved[1].request_key)
  assert.equal(h.saved[1].transaction_route, 'local')
  assert.equal(h.saved[1].items[0].local_sku_id, 9)
  assert.equal(h.saved[1].receipt_draft, null)
  await h.editor.saveAndSync()
  assert.deepEqual(h.synced, [])
  assert.equal(h.saved.length, 2)
})

test('switching to local cannot silently discard an entered old receipt draft', async t => {
  const h = await harness(); t.after(h.stop)
  Object.assign(h.editor.form, defaults('local draft'), { transaction_route: 'local', local_customer_id: 3, customer_id: 'ark:3', express_channel: 'FEDEX', receipt_draft: { amount: 8, status: 'draft' }, items: [{ local_sku_id: 9, sku_id: 9, product_display: 'Local SKU', quantity: 1, price_per_piece: 0, total_price: 0 }] })
  await h.editor.saveDraft()
  assert.equal(h.saved.length, 0)
  assert.equal(h.editor.form.receipt_draft.amount, 8)
})


test('deactivating the unified editor invalidates a pending order read before it can reopen another route', async t => {
  const request = deferred(), h = await harness(undefined, undefined, {}, undefined, { getInvoice: () => request.promise }); t.after(h.stop)
  const opening = h.editor.openEdit(19)
  h.editor.cancelEntry()
  request.resolve({ ...state.emptyInvoiceForm(), id: 19, transaction_route: 'legacy' })
  await opening
  assert.equal(h.editor.drawerVisible.value, false)
  assert.equal(h.editor.form.id, null)
})
