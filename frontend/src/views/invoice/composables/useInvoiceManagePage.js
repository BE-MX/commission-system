import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import { formatMoney } from '@/utils/money'
import {
  deleteInvoice,
  downloadInvoiceExcel,
  downloadInvoicePdf,
  fetchInvoicePrintHtml,
  getInvoiceSyncLogs,
  getInvoiceSummary,
  listInvoices,
  resolveInvoiceSyncUncertain,
} from '@/api/invoice'
import { INVOICE_SYNC_OUTCOME, isInvoiceSyncing, validateThenSync } from './invoiceSyncFlow'
import { formatInvoiceDateTime } from './invoiceDateTime'
import { currentBeijingDate } from '@/utils/datetime'

export function useInvoiceManagePage() {
  const loading = ref(false)
  const invoices = ref([])
  const today = currentBeijingDate()
  const month = today.slice(0, 7)
  const [yearNumber, monthNumber] = month.split('-').map(Number)
  const lastDay = new Date(Date.UTC(yearNumber, monthNumber, 0)).getUTCDate()
  const summaryDateRange = ref([`${month}-01`, `${month}-${lastDay}`])
  const summary = ref(null)
  const summaryLoading = ref(false)
  const summaryError = ref('')
  let summaryRequestId = 0
  const filters = reactive({ keyword: '', order_id: '', status: '', order_type: '' })
  const pagination = reactive({ page: 1, page_size: 20, total: 0 })
  const hasActiveFilters = computed(() => Boolean(filters.keyword || filters.order_id || filters.status || filters.order_type))

  function resetFilters() {
    filters.keyword = ''
    filters.order_id = ''
    filters.status = ''
    filters.order_type = ''
    pagination.page = 1
    loadInvoices()
  }

  function handleSizeChange() {
    pagination.page = 1
    loadInvoices()
  }

  // 表格视图状态：列显示 + 行密度，页面本地持久化（List Page Spec 第 9 节试点）
  const columnDefs = [
    { key: 'invoice_no', label: '发票号', prop: 'invoice_no', minWidth: 220, maxWidth: 320, className: 'invoice-number-column' },
    { key: 'customer_name', label: '客户', prop: 'customer_name', minWidth: 180, maxWidth: 260, tooltip: true },
    { key: 'order_type', label: '类型', minWidth: 76, maxWidth: 96 },
    { key: 'invoice_date', label: '日期', prop: 'invoice_date', minWidth: 116, maxWidth: 150 },
    { key: 'item_count', label: '明细', prop: 'item_count', minWidth: 80, maxWidth: 120, align: 'right' },
    { key: 'total_amount', label: '金额（USD）', minWidth: 132, maxWidth: 160, align: 'right' },
    { key: 'status', label: '状态', minWidth: 84, maxWidth: 110 },
    { key: 'sync_status', label: '同步', minWidth: 84, maxWidth: 110 },
    { key: 'created_by', label: '创建人', minWidth: 84, maxWidth: 120, tooltip: true },
    { key: 'created_at', label: '创建时间', minWidth: 130, maxWidth: 160, tooltip: true },
  ]
  const TABLE_VIEW_KEY = 'invoice-manage-table-view'
  const density = ref('default')
  const visibleKeys = ref(columnDefs.map(column => column.key))
  try {
    const saved = JSON.parse(localStorage.getItem(TABLE_VIEW_KEY) || 'null')
    if (Array.isArray(saved?.visibleKeys)) {
      const known = new Set(columnDefs.map(column => column.key))
      const restored = saved.visibleKeys.filter(key => known.has(key))
      if (restored.length) visibleKeys.value = restored
    }
    if (['compact', 'default', 'comfort'].includes(saved?.density)) density.value = saved.density
  } catch { /* 本地偏好损坏时忽略，使用默认视图 */ }

  watch([density, visibleKeys], () => {
    try {
      localStorage.setItem(TABLE_VIEW_KEY, JSON.stringify({ density: density.value, visibleKeys: visibleKeys.value }))
    } catch { /* 隐私模式等写入失败时忽略 */ }
  }, { deep: true })

  const visibleColumns = computed(() => columnDefs.filter(column => visibleKeys.value.includes(column.key)))
  const syncLogsVisible = ref(false)
  const syncLogsLoading = ref(false)
  const syncLogs = ref([])
  const syncLogsTitle = ref('')
  let showIssues = () => {}

  async function loadSummary() {
    const [dateFrom, dateTo] = summaryDateRange.value || []
    if (!dateFrom || !dateTo) return
    const requestId = ++summaryRequestId
    summaryLoading.value = true
    summaryError.value = ''
    try {
      const result = await getInvoiceSummary({ date_from: dateFrom, date_to: dateTo })
      if (requestId === summaryRequestId) summary.value = result
    } catch {
      if (requestId === summaryRequestId) {
        summary.value = null
        summaryError.value = '订单概览加载失败，请重试'
      }
    } finally {
      if (requestId === summaryRequestId) summaryLoading.value = false
    }
  }

  async function loadInvoices() {
    const summaryRequest = loadSummary()
    loading.value = true
    try {
      const params = { ...filters, page: pagination.page, page_size: pagination.page_size }
      if (params.order_id) params.order_id = params.order_id.trim()
      if (!params.order_id) delete params.order_id
      if (!params.order_type) delete params.order_type
      const result = await listInvoices(params)
      invoices.value = result.items || []
      pagination.total = result.total || 0
    } finally {
      loading.value = false
      await summaryRequest
    }
  }

  async function validateAndSync(id) {
    const outcome = await validateThenSync(id, showIssues)
    if (outcome !== INVOICE_SYNC_OUTCOME.DUPLICATE) await loadInvoices()
  }

  async function resolveUncertain(row, resolution) {
    try {
      let xiaomanOrderId = null
      if (resolution === 'bind_order') {
        const result = await ElMessageBox.prompt(
          '请填写已在 OKKI 后台确认的数字订单 ID',
          '绑定已生成订单',
          { inputPattern: /^\d+$/, inputErrorMessage: '请输入有效的数字订单 ID' },
        )
        xiaomanOrderId = result.value.trim()
      }
      const reasonResult = await ElMessageBox.prompt(
        resolution === 'confirm_existing' ? '请填写至少10字原订单核对依据；系统将核验数量、价格和金额' : resolution === 'bind_order' ? '请填写绑定依据' : '请填写确认 OKKI 未生成订单的依据',
        '人工核对原因',
        { inputPattern: /\S{2,}/, inputErrorMessage: '请至少填写 2 个非空字符' },
      )
      await resolveInvoiceSyncUncertain(row.id, {
        resolution,
        reason: reasonResult.value.trim(),
        xiaoman_order_id: xiaomanOrderId,
      })
      msgSuccess('待核对状态处理')
      await loadInvoices()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') throw error
    }
  }

  async function openSyncLogs(row) {
    syncLogsTitle.value = `同步日志 - ${row.invoice_no}`
    syncLogsVisible.value = true
    syncLogsLoading.value = true
    try {
      const result = await getInvoiceSyncLogs(row.id)
      syncLogs.value = result.items || []
    } finally {
      syncLogsLoading.value = false
    }
  }

  function handleExport(command, row) {
    if (command === 'excel') return exportFile(row, downloadInvoiceExcel, 'xlsx')
    if (command === 'pdf') return exportFile(row, downloadInvoicePdf, 'pdf')
    return openPrint(row.id)
  }

  async function exportFile(row, download, extension) {
    const response = await download(row.id)
    const blob = new Blob([response.data], { type: response.headers['content-type'] })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${row.invoice_no || 'invoice'}.${extension}`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function openPrint(id) {
    const html = await fetchInvoicePrintHtml(id)
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
    window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }

  async function removeInvoice(row) {
    await confirmDanger('删除', `发票 ${row.invoice_no}`)
    await deleteInvoice(row.id)
    msgSuccess('删除')
    loadInvoices()
  }

  function bindIssueHandler(handler) { showIssues = handler }
  const actionText = action => ({ create: '首次推送', update: '编辑推送', retry: '重试' })[action] || action
  const formatDateTime = formatInvoiceDateTime
  const money = value => formatMoney(value)
  const money4 = value => formatMoney(value, 4)
  // 状态字典：枚举 → { label, tone } 单点维护（DESIGN.md「Status Badge & 状态字典」）
  const STATUS_DICT = {
    draft: { label: '草稿', tone: 'info' },
    cancel_pending: { label: '取消处理中', tone: 'info' },
    cancelled: { label: '已取消', tone: 'info' },
    ready: { label: '可同步', tone: 'success' },
    synced: { label: '已同步', tone: 'success' },
    sync_failed: { label: '同步失败', tone: 'danger' },
    sync_uncertain: { label: '同步结果待核对', tone: 'warning' },
  }
  const SYNC_DICT = {
    not_synced: { label: '未同步', tone: 'info' },
    synced: { label: '已同步', tone: 'success' },
    sync_failed: { label: '失败', tone: 'danger' },
    sync_uncertain: { label: '待核对', tone: 'warning' },
  }
  const statusOptions = Object.entries(STATUS_DICT).map(([value, meta]) => ({ value, label: meta.label }))
  const statusText = status => STATUS_DICT[status]?.label || status
  const statusType = status => STATUS_DICT[status]?.tone || 'info'
  const syncText = status => SYNC_DICT[status]?.label || status
  const syncType = status => SYNC_DICT[status]?.tone || 'info'
  const orderTypeTone = type => (type === 'production' ? 'warning' : 'info')

  onMounted(loadInvoices)
  return {
    actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
    loading, money, money4, openSyncLogs, pagination, removeInvoice, statusText, statusType,
    summary, summaryDateRange, summaryError, summaryLoading, loadSummary,
    syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
    isInvoiceSyncing, resolveUncertain, validateAndSync,
    hasActiveFilters, handleSizeChange, orderTypeTone, resetFilters, statusOptions,
    columnDefs, density, visibleColumns, visibleKeys,
  }
}
