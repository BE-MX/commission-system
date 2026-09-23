import { computed, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { useListPage } from '@/composables/useListPage'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess, msgError } from '@/utils/feedback'
import * as api from '@/api/receipt'

export const statusLabel = value => ({ pending: '待同步', waiting_target: '等待集成验证', syncing: '同步中', synced: '已同步', failed: '同步失败', uncertain: '待核对' })[value] || value
export const statusTone = value => ({ synced: 'success', failed: 'danger', uncertain: 'warning', pending: 'info', syncing: 'warning' })[value] || 'info'
export const money = value => Number(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const financeLabel = value => value === 1 ? '已生效' : value === 0 ? '未生效' : '未取得'

export function useReceipts() {
  const dates = ref([]), deliveryEnabled = ref(null)
  const page = useListPage(async params => {
    const result = await api.listReceipts({ ...params, date_from: dates.value?.[0], date_to: dates.value?.[1] })
    deliveryEnabled.value = result.delivery_enabled
    return result
  },
    { searchForm: { keyword: '', sync_status: '', source: '', status: '' } })
  const editorVisible = ref(false), detailVisible = ref(false), detail = ref(null), saving = ref(false), uploading = ref(false)
  const orders = ref([]), ordersLoading = ref(false), balance = ref(null), balanceLoading = ref(false), error = ref('')
  const candidates = ref([]), form = reactive({}), editing = ref(null)
  let searchSequence = 0, balanceSequence = 0, detailSequence = 0, initialForm = '', idempotencyKey = ''
  const selectedOrder = computed(() => orders.value.find(o => o.id === form.invoice_id))
  const remainingAfter = computed(() => Number(balance.value?.remaining_amount || 0) - Number(form.amount || 0))
  const editable = computed(() => detail.value?.status === 'active' && !detail.value.batch_id && detail.value.purpose !== 'presale_deposit' && ['pending', 'failed'].includes(detail.value.sync_status))

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
      try { await ElMessageBox.confirm('尚未提交的信息将被丢弃，确定关闭？', '关闭回款单', { type: 'warning' }) }
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
      const row = editing.value ? await api.updateReceipt(editing.value, { ...fields, version: detail.value.version })
        : await api.createReceipt({ ...fields, invoice_id: form.invoice_id, request_key: idempotencyKey, balance_version: balance.value.version, settlement_id: balance.value.settlement_id || null })
      editorVisible.value = false; detail.value = row; detailVisible.value = true; candidates.value = []
      msgSuccess(editing.value ? '回款已修正，请重试同步' : deliveryEnabled.value === false ? '回款已创建，同步启用后自动处理' : '回款已创建，等待同步小满')
      await page.fetchList()
    } catch (e) {
      error.value = e.response?.data?.detail || e.message || '保存失败，资料已保留'
      // Keep request key after unknown HTTP outcome. Never turn a retry into a new receipt.
    } finally { saving.value = false }
  }
  async function retry(row) { if (saving.value) return; saving.value = true; try { detail.value = await api.retryReceipt(row.id); await page.fetchList(); msgSuccess('已加入同步队列') } finally { saving.value = false } }
  async function reason(title) {
    try { return (await ElMessageBox.prompt('请填写核对依据或原因（至少 2 个字符）', title, { inputPattern: /\S.{1,}/, inputErrorMessage: '请填写原因' })).value }
    catch { return null }
  }
  async function voidCurrent() { const why = await reason('作废本地回款'); if (!why) return; detail.value = await api.voidReceipt(detail.value.id, why); await page.fetchList() }
  async function reconcile() {
    if (saving.value) return; saving.value = true
    try { const res = await api.reconcileReceipt(detail.value.id); detail.value = res.receipt; candidates.value = res.candidates; await page.fetchList(); msgSuccess(res.candidates.length ? '已找到候选，请管理员核对' : '小满查询已完成') }
    finally { saving.value = false }
  }
  async function resolve(resolution) {
    let remoteId = null
    if (resolution === 'bind_receipt') {
      try { remoteId = (await ElMessageBox.prompt('填写小满回款 ID（不是订单 ID）', '绑定小满回款', { inputPattern: /^\d+$/, inputErrorMessage: '请输入数字回款 ID' })).value }
      catch { return }
    }
    const why = await reason(resolution === 'bind_receipt' ? '绑定依据' : '确认小满未创建')
    if (!why) return
    detail.value = await api.resolveReceipt(detail.value.id, { resolution, xiaoman_receipt_id: remoteId, reason: why })
    candidates.value = []; await page.fetchList()
  }
  function reset() { dates.value = []; return page.handleReset() }
  return { ...page, dates, deliveryEnabled, editorVisible, detailVisible, detail, saving, uploading, orders, ordersLoading, balance,
    balanceLoading, error, candidates, form, editing, selectedOrder, remainingAfter, editable, searchOrders,
    selectOrder, refreshBalance, openCreate, showDetail, editCurrent, closeEditor, submit, retry, voidCurrent, reconcile, resolve, reset }
}
