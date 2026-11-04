import { formatMoney } from '../src/utils/money.js'
import { feedbackFixture } from './helpers/feedbackFixture.mjs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { computed, reactive, ref } from 'vue'
import { watchListResourceScope } from '../src/composables/useListResourceScope.js'
import { isAmount } from '../src/utils/validators.js'
import { useListPage } from '../src/composables/useListPage.js'

const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticCustomers.js', import.meta.url), 'utf8')
const template = readFileSync(new URL('../src/views/domestic/DomesticCustomers.vue', import.meta.url), 'utf8')

function createState({ permissions = [], roles = [] } = {}) {
  const requests = []
  const warnings = []
  const creates = []
  const updates = []
  const recharges = []
  let requestSequence = 0
  const context = {
    reactive, ref, watchListResourceScope, isAmount, onMounted: () => {},
    ElMessage: { warning: message => warnings.push(message) },
    createCustomer: async payload => creates.push(payload),
    updateCustomer: async (id, payload) => updates.push({ id, payload }),
    newRequestId: () => `recharge-${++requestSequence}`,
    rechargeCustomer: async (id, payload) => { recharges.push({ id, payload }); return { data: {} } },
    msgSuccess: () => {},
    membershipPreview: () => '', membershipChangeLabel: () => '',
    useAuthStore: () => ({
      user: { id: 7 },
      hasPermission: code => roles.includes('super_admin') || permissions.includes(code),
    }),
    useListPage: (fetcher, options) => useListPage(fetcher, { ...options, immediate: false }),
    listCustomers: async params => {
      requests.push(params)
      return { data: { items: [{ id: params.owner_scope }], total: 1 } }
    },
  }
  const executable = source.replace(/^import\s[\s\S]*?from\s+['"][^'"]+['"]\s*$/gm, '').replace(/^export /gm, '')
  Object.assign(context, feedbackFixture(context), { formatMoney })
  vm.runInNewContext(`${executable}\nthis.state = useDomesticCustomers()`, context)
  return { state: context.state, requests, warnings, creates, updates, recharges }
}

function rechargeUpload(state) {
  const script = readFileSync(new URL('../src/components/AppUpload.vue', import.meta.url), 'utf8')
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\r?\n/gm, '')
  const errors = []
  const props = { transfer: true, accept: 'image/jpeg,image/png,image/webp,application/pdf',
    maxSizeMb: 20, limit: 1, get modelValue() { return state.rechargeDialog.voucherList },
    uploadFn: state.selectRechargeVoucher }
  const deps = { computed, reactive, ref, defineProps: () => props,
    defineEmits: () => (_, files) => state.onRechargeVoucherChange(files), msgError: message => errors.push(message) }
  const zone = new Function(...Object.keys(deps), `${script}\nreturn { onPaste, beforeUpload, doUpload, remove }`)(...Object.values(deps))
  return { ...zone, errors }
}

test('pasted recharge evidence stays local until submit and preserves the original file and request key', async () => {
  const { state, recharges } = createState()
  state.openRecharge({ id: 7 })
  state.rechargeDialog.amount = 1200
  const key = state.rechargeDialog.requestId
  const zone = rechargeUpload(state)
  const file = new File(['clipboard pixels'], 'clipboard.png', { type: 'image/png' })
  let prevented = false
  await zone.onPaste({ clipboardData: { items: [{ kind: 'file', getAsFile: () => file }] }, preventDefault() { prevented = true } })
  assert.equal(prevented, true)
  assert.equal(recharges.length, 0)
  assert.equal(state.rechargeDialog.voucherFile, file)
  assert.equal(state.rechargeDialog.voucherList[0].name, 'clipboard.png')
  await state.confirmRecharge()
  assert.equal(recharges.length, 1)
  assert.equal(recharges[0].id, 7)
  assert.equal(recharges[0].payload.file, file)
  assert.equal(recharges[0].payload.amount, 1200)
  assert.equal(recharges[0].payload.request_id, key)
})

test('removing a pasted voucher blocks stale-file submission and allows selecting a PDF', async () => {
  const { state, recharges, warnings } = createState()
  state.openRecharge({ id: 7 })
  state.rechargeDialog.amount = 1200
  const zone = rechargeUpload(state)
  const image = new File(['image'], 'one.png', { type: 'image/png' })
  assert.equal(zone.beforeUpload(image), true)
  await zone.doUpload({ file: image })
  assert.equal(zone.beforeUpload(new File(['second'], 'two.png', { type: 'image/png' })), false)
  zone.remove(0)
  assert.equal(state.rechargeDialog.voucherFile, null)
  await state.confirmRecharge()
  assert.equal(recharges.length, 0)
  assert.ok(warnings.some(message => message.includes('转账截图')))
  const pdf = new File(['%PDF-1.4'], 'bank.pdf', { type: 'application/pdf' })
  assert.equal(zone.beforeUpload(pdf), true)
  await zone.doUpload({ file: pdf })
  await state.confirmRecharge()
  assert.equal(recharges[0].payload.file, pdf)
})

test('recharge voucher validation rejects invalid and oversize files and reopening resets evidence', async () => {
  const { state } = createState()
  state.openRecharge({ id: 7 })
  const key = state.rechargeDialog.requestId
  const zone = rechargeUpload(state)
  assert.equal(zone.beforeUpload({ type: 'text/plain', size: 5 }), false)
  assert.ok(zone.errors.at(-1).includes('PDF'))
  assert.equal(zone.beforeUpload({ type: 'image/png', size: 20 * 1024 * 1024 + 1 }), false)
  assert.ok(zone.errors.at(-1).includes('20MB'))
  await zone.onPaste({ clipboardData: { items: [{ kind: 'string' }] }, preventDefault() { assert.fail('text paste intercepted') } })
  state.onRechargeVoucherChange([await state.selectRechargeVoucher(new File(['old'], 'old.png', { type: 'image/png' }))])
  state.openRecharge({ id: 8 })
  assert.equal(state.rechargeDialog.voucherFile, null)
  assert.equal(state.rechargeDialog.voucherList.length, 0)
  assert.notEqual(state.rechargeDialog.requestId, key)
})

const validCustomer = {
  custom_code: 'KH-001', shop_name: '马姐假发', contact: '马姐', phone: '13800138000',
  region: ['山东省', '青岛市'], owner_user_id: 7, customer_source: 'referral',
  customer_level: 'A', lifecycle_status: 'active', store_type: 'store',
  first_contact_date: '2026-01-01', first_order_date: '2026-02-01', last_order_date: '2026-03-01',
}

test('new customer form marks every required field', () => {
  for (const label of [
    '客户编码', '联系人', '手机号', '省份 / 城市', '归属销售', '客户来源',
    '客户等级', '客户状态', '门店类型', '首次联系', '首次下单', '最近下单',
  ]) {
    assert.match(template, new RegExp(`<el-form-item label="${label}" :required="!dialog.id">`))
  }
  assert.match(template, /<el-form-item label="客户店名" required>/)
})

test('new customer blocks every required field and accepts a complete profile', async () => {
  for (const field of Object.keys(validCustomer)) {
    const { state, warnings, creates } = createState()
    const missing = field === 'region' ? ['山东省'] : typeof validCustomer[field] === 'string' ? '   ' : null
    Object.assign(state.dialog, validCustomer, { [field]: missing })
    await state.save()
    assert.equal(creates.length, 0, `${field} should block creation`)
    assert.equal(warnings.length, 1, `${field} should show a warning`)
  }

  const { state, creates } = createState()
  Object.assign(state.dialog, validCustomer)
  await state.save()
  assert.equal(creates.length, 1)
  assert.equal(creates[0].city, '青岛市')
})

test('editing an existing customer keeps optional profile fields optional', async () => {
  const { state, updates, warnings } = createState()
  state.openDialog({ id: 9, shop_name: '老客户' })
  await state.save()
  assert.equal(warnings.length, 0)
  assert.equal(updates.length, 1)
  assert.equal(updates[0].id, 9)
})

test('ownership and the independent customer permission control row eligibility', () => {
  const { state } = createState({ permissions: ['domestic:admin', 'domestic:read_all'] })
  assert.equal(state.canOperateCustomer({ owner_user_id: 7 }), true)
  assert.equal(state.canOperateCustomer({ owner_user_id: 8 }), false)
  assert.equal(state.canOperateCustomer({ owner_user_id: null }), false)
  for (const access of [{ permissions: ['domestic_customer:admin'] }, { roles: ['super_admin'] }]) {
    const { state: admin } = createState(access)
    assert.equal(admin.canOperateCustomer({ owner_user_id: 8 }), true)
    assert.equal(admin.canOperateCustomer({ owner_user_id: null }), true)
  }
})

test('customer tab changes reset pagination and retain search and region filters', async () => {
  const { state, requests } = createState()
  await state.fetchList()
  assert.equal(requests[0].owner_scope, 'private')
  state.page.value = 4
  Object.assign(state.searchForm, { owner_scope: 'public', keyword: '门店', province: '山东省', city: '青岛市' })
  await state.handleSearch()
  assert.equal(state.page.value, 1)
  assert.equal(requests[1].owner_scope, 'public')
  assert.equal(requests[1].page, 1)
  assert.equal(requests[1].keyword, '门店')
  assert.equal(requests[1].province, '山东省')
  assert.equal(requests[1].city, '青岛市')
  assert.equal(state.list.value[0].id, 'public')
})


test('grade and owner filters compose, reset pagination and clear from requests', async () => {
  const { state, requests } = createState()
  state.page.value = 5
  Object.assign(state.searchForm, { customer_level: 'A', owner_user_id: 7 })
  await state.handleSearch()
  assert.equal(requests.at(-1).page, 1)
  assert.equal(requests.at(-1).customer_level, 'A')
  assert.equal(requests.at(-1).owner_user_id, 7)
  state.searchForm.customer_level = ''
  state.searchForm.owner_user_id = ''
  await state.handleSearch()
  assert.equal(Object.hasOwn(requests.at(-1), 'customer_level'), false)
  assert.equal(Object.hasOwn(requests.at(-1), 'owner_user_id'), false)
})
