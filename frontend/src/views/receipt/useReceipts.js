import { formatMoney } from '../../utils/money.js'
import { confirmAction, promptAction, msgSuccess, msgError } from '@/utils/feedback'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useListPage } from '@/composables/useListPage'
import { currentBeijingDate } from '@/utils/datetime'
import * as api from '@/api/receipt'

export const statusLabel = value => ({ pending: '待同步', waiting_target: '等待集成验证', syncing: '同步中', synced: '已同步', failed: '同步失败', uncertain: '待核对' })[value] || value
export const statusTone = value => ({ synced: 'success', failed: 'danger', uncertain: 'warning', pending: 'info', syncing: 'warning' })[value] || 'info'
export const money = value => formatMoney(value)
export const financeLabel = value => value === 1 ? '已生效' : value === 0 ? '未生效' : '未取得'

export function useReceipts() {
  const route = useRoute()
  const queryOrderId = value => typeof value === 'string' && /^[1-9][0-9]{0,63}$/.test(value) ? value : ''
  const queryKeyword = value => typeof value === 'string' ? value.slice(0, 100) : ''
  const deliveryEnabled = ref(null), presaleDeliveryEnabled = ref(null)
  const page = useListPage(async ({ dateRange, ...params }, { signal, isCurrent }) => {
    if (params.order_id) params.order_id = params.order_id.trim()
    if (!params.order_id) delete params.order_id
    const result = await api.listReceipts({ ...params, date_from: dateRange?.[0], date_to: dateRange?.[1] }, { signal, suppressToast: true })
    if (isCurrent()) {
      deliveryEnabled.value = result.delivery_enabled
      presaleDeliveryEnabled.value = result.presale_delivery_enabled
    }
    return result
  },
    { searchForm: { keyword: queryKeyword(route.query.keyword), order_id: queryOrderId(route.query.order_id), sync_status: '', source: '', status: '', dateRange: [] } })
  watch(() => [route.query.order_id, route.query.keyword], ([id, keyword]) => {
    page.searchForm.order_id = queryOrderId(id); page.searchForm.keyword = queryKeyword(keyword)
    page.handleSearch()
  })
  const dates = computed({ get: () => page.searchForm.dateRange, set: value => { page.searchForm.dateRange = value || [] } })
  const editorVisible = ref(false), detailVisible = ref(false), detail = ref(null), saving = ref(false), uploading = ref(false)
  const orders = ref([]), ordersLoading = ref(false), balance = ref(null), balanceLoading = ref(false), error = ref('')
  const candidates = ref([]), form = reactive({}), editing = ref(null)
  let searchSequence = 0, balanceSequence = 0, detailSequence = 0, initialForm = '', idempotencyKey = ''
  const selectedOrder = computed(() => orders.value.find(o => o.id === form.invoice_id))
  const remainingAfter = computed(() => Number(balance.value?.remaining_amount || 0) - Number(form.amount || 0))
  const editable = computed(() => detail.value?.status === 'active' && !detail.value.batch_id && !detail.value.xiaoman_receipt_id && detail.value.purpose !== 'presale_deposit' && ['pending', 'failed'].includes(detail.value.sync_status))

  async function searchOrders(keyword = '') {
    const sequence = ++searchSequence
    ordersLoading.value = true
    try { const data = await api.getReceiptOrders({ keyword }); if (sequence === searchSequence) orders.value = data.items }
    finally { if (sequence === searchSequence) ordersLoading.value = false }
  }
  async function selectOrder(id) {
    const sequence = ++balanceSequence
    balance.value = null; form.amount = null; error.value = ''; balanceLoading.value = true
    // Screenshots for an unsubmitted different order must be chosen again.
    form.attachment_ids = []
    try {
      const result = await api.getReceiptBalance(id)
      if (sequence !== balanceSequence || form.invoice_id !== id) return
      balance.value = result
      form.amount = Number(result.remaining_amount) > 0 ? Number(result.remaining_amount) : null
      if (!form.amount) error.value = '订单已无可登记余额'
    } catch { if (sequence === balanceSequence) error.value = '订单余额未核验，请刷新余额后再登记' }
    finally { if (sequence === balanceSequence) balanceLoading.value = false }
  }
  async function openCreate(invoiceId = null) {
    if (saving.value || uploading.value) return
    editing.value = null; balance.value = null; error.value = ''; balanceSequence += 1
    Object.assign(form, { invoice_id: invoiceId, amount: null, collection_date: currentBeijingDate(),
      payment_type: '', bank_charge: 0, attachment_ids: [], remark: '' })
    idempotencyKey = crypto.randomUUID(); initialForm = JSON.stringify(form); editorVisible.value = true
    await searchOrders()
    if (invoiceId) await selectOrder(invoiceId)
  }
  async function showDetail(row) {
    const sequence = ++detailSequence
    detailVisible.value = true; candidates.value = []; detail.value = null
    const result = await api.getReceipt(row.id)
    if (sequence === detailSequence) detail.value = result
  }
  async function refreshBalance() {
    const sequence = ++balanceSequence, id = form.invoice_id
    balanceLoading.value = true; balance.value = null
    try {
      const result = await api.getReceiptBalance(id)
      if (sequence === balanceSequence && form.invoice_id === id) { balance.value = result; error.value = '' }
    } catch { if (sequence === balanceSequence) error.value = '余额核验失败，凭证已保留，请重试' }
    finally { if (sequence === balanceSequence) balanceLoading.value = false }
  }
  function editCurrent() {
    if (saving.value || uploading.value) return
    editing.value = detail.value.id
    const row = detail.value
    Object.assign(form, { invoice_id: row.invoice_id, amount: Number(row.amount), collection_date: row.collection_date,
      payment_type: row.payment_type, bank_charge: Number(row.bank_charge), attachment_ids: row.attachments.map(a => a.id), remark: row.remark || '' })
    initialForm = JSON.stringify(form); error.value = ''; editorVisible.value = true
  }
  async function closeEditor(done) {
    if (saving.value || uploading.value) { msgError('请等待当前保存或上传完成'); return }
    if (JSON.stringify(form) !== initialForm) {
      try { await confirmAction('尚未提交的信息将被丢弃，确定关闭？', '关闭回款单', { type: 'warning' }) }
      catch { return }
    }
    balanceSequence += 1; editorVisible.value = false
    if (typeof done === 'function') done()
  }
  async function submit() {
    if (saving.value || uploading.value) return
    error.value = ''
    if (!form.invoice_id || !form.amount || !form.collection_date || !form.payment_type || !form.attachment_ids.length) {
      error.value = '请选择订单，填写金额、日期、回款方式，并上传回款截图'; return
    }
    if (!editing.value && (!balance.value || Number(form.amount) > Number(balance.value.remaining_amount))) {
      error.value = '本次金额超过可登记余额，或余额尚未核验'; return
    }
    saving.value = true
    try {
      const fields = { amount: String(form.amount), collection_date: form.collection_date, payment_type: form.payment_type,
        bank_charge: String(form.bank_charge || 0), remark: form.remark, attachment_ids: [...form.attachment_ids] }
      const created = !editing.value
      const row = editing.value ? await api.updateReceipt(editing.value, { ...fields, version: detail.value.version })
        : await api.createReceipt({ ...fields, invoice_id: form.invoice_id, request_key: idempotencyKey, balance_version: balance.value.version, settlement_id: balance.value.settlement_id || null })
      editorVisible.value = false; detail.value = row; detailVisible.value = true; candidates.value = []
      const canDeliver = selectedOrder.value?.order_type === 'presale' ? presaleDeliveryEnabled.value : deliveryEnabled.value
      msgSuccess(editing.value ? '回款已修正，请重试同步' : canDeliver === false ? '回款已创建，同步启用后自动处理' : '回款已创建，等待同步小满')
      // Receipt lists are sorted by id descending; creation moves to page one.
      await (created ? page.refreshCreate() : page.refreshUpdate())
    } catch (e) {
      error.value = e.response?.data?.detail || e.message || '保存失败，资料已保留'
      // Keep request key after unknown HTTP outcome. Never turn a retry into a new receipt.
    } finally { saving.value = false }
  }
  async function retry(row) { if (saving.value) return; saving.value = true; try { detail.value = await api.retryReceipt(row.id); await page.refreshUpdate(); msgSuccess('已加入同步队列') } finally { saving.value = false } }
  async function reason(title) {
    try { return (await promptAction('请填写核对依据或原因（至少 2 个字符）', title, { inputPattern: /\S.{1,}/, inputErrorMessage: '请填写原因' })).value }
    catch { return null }
  }
  async function voidCurrent() { const why = await reason('作废本地回款'); if (!why) return; detail.value = await api.voidReceipt(detail.value.id, why); await page.refreshUpdate() }
  async function reconcile() {
    if (saving.value) return; saving.value = true
    try { const res = await api.reconcileReceipt(detail.value.id); detail.value = res.receipt; candidates.value = res.candidates; await page.refreshUpdate(); msgSuccess(res.candidates.length ? '已找到候选，请管理员核对' : '小满查询已完成') }
    finally { saving.value = false }
  }
  async function resolve(resolution) {
    let remoteId = null
    if (resolution === 'bind_receipt') {
      try { remoteId = (await promptAction('填写小满回款 ID（不是订单 ID）', '绑定小满回款', { inputPattern: /^\d+$/, inputErrorMessage: '请输入数字回款 ID' })).value }
      catch { return }
    }
    const why = await reason(resolution === 'bind_receipt' ? '绑定依据' : '确认小满未创建')
    if (!why) return
    detail.value = await api.resolveReceipt(detail.value.id, { resolution, xiaoman_receipt_id: remoteId, reason: why })
    candidates.value = []; await page.refreshUpdate()
  }
  function reset() { return page.handleReset() }
  return { ...page, listErrorMessage: page.errorMessage, dates, deliveryEnabled, presaleDeliveryEnabled, editorVisible, detailVisible, detail, saving, uploading, orders, ordersLoading, balance,
    balanceLoading, error, candidates, form, editing, selectedOrder, remainingAfter, editable, searchOrders,
    selectOrder, refreshBalance, openCreate, showDetail, editCurrent, closeEditor, submit, retry, voidCurrent, reconcile, resolve, reset }
}
