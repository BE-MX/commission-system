import { promptAction, msgSuccess, confirmDanger, confirmAction, alertAction, notifyFeedback, isFeedbackCancelled } from '@/utils/feedback'
import { computed, h, onMounted, onUnmounted, reactive, ref } from 'vue'

import { formatMoney } from '@/utils/money'
import { useTableView } from '@/composables/useTableView'
import { useListPage } from '@/composables/useListPage'
import {
  deleteInvoice,
  deleteInvoiceWithRelated,
  previewInvoiceDeletion,
  downloadInvoiceExcel,
  downloadInvoicePdf,
  fetchInvoicePrintHtml,
  getInvoiceSyncLogs,
  getInvoiceSummary,
  listInvoices,
  resolveInvoiceSyncUncertain,
} from '@/api/invoice'
import { INVOICE_SYNC_OUTCOME, isInvoiceSyncing, validateThenSync } from './invoiceSyncFlow'
import { createInvoiceSubmissionGuard } from './invoiceSubmissionGuard'
import { runRelatedInvoiceDeletion, usesRelatedInvoiceDeletion } from './invoiceDeletionFlow'
import { formatInvoiceDateTime } from './invoiceDateTime'
import { currentBeijingDate } from '@/utils/datetime'

export function useInvoiceManagePage() {
  const listPage = useListPage((params, { signal }) => {
    if (params.order_id) params.order_id = params.order_id.trim()
    if (!params.order_id) delete params.order_id
    if (!params.order_type) delete params.order_type
    return listInvoices(params, { signal, suppressToast: true })
  }, { searchForm: { keyword: '', order_id: '', status: '', order_type: '' } })
  const {
    loading, list: invoices, searchForm: filters, page, pageSize, total,
    appliedSearchForm, errorMessage: listErrorMessage, hasLoaded, hasData, dataPage, hasPendingSearch,
    handleReset: resetFilters, handlePageChange, handleSizeChange,
  } = listPage
  const today = currentBeijingDate()
  const month = today.slice(0, 7)
  const [yearNumber, monthNumber] = month.split('-').map(Number)
  const lastDay = new Date(Date.UTC(yearNumber, monthNumber, 0)).getUTCDate()
  const summaryDateRange = ref([`${month}-01`, `${month}-${lastDay}`])
  const summary = ref(null)
  const summaryLoading = ref(false)
  const summaryError = ref('')
  let summaryRequestId = 0
  let summaryController
  const hasActiveFilters = computed(() => Object.values(appliedSearchForm.value).some(Boolean))

  // 列配置数组：TableTools 列显隐的数据源 + 表格渲染驱动（Action Bar Spec / List Page Spec 第 9 节）
  const columnDefs = [
    { key: 'invoice_no', label: '发票号', prop: 'invoice_no', minWidth: 220, maxWidth: 320, className: 'invoice-number-column', fixed: 'left' },
    { key: 'customer_name', label: '客户', prop: 'customer_name', minWidth: 180, maxWidth: 260, tooltip: true, fixed: 'left' },
    { key: 'order_type', label: '类型', minWidth: 110, maxWidth: 130 },
    { key: 'invoice_date', label: '日期', prop: 'invoice_date', minWidth: 116, maxWidth: 150 },
    { key: 'item_count', label: '明细', prop: 'item_count', minWidth: 80, maxWidth: 120, align: 'right' },
    { key: 'total_amount', label: '金额（USD）', minWidth: 132, maxWidth: 160, align: 'right' },
    { key: 'status', label: '状态', minWidth: 160, maxWidth: 180, tooltip: true },
    { key: 'sync_status', label: '同步', minWidth: 110, maxWidth: 130, tooltip: true },
    { key: 'created_by', label: '创建人', minWidth: 84, maxWidth: 120, tooltip: true },
    { key: 'created_at', label: '创建时间', minWidth: 130, maxWidth: 160, tooltip: true },
  ]
  // 表格视图状态（列显隐/密度/全屏）走全局基建 useTableView（Action Bar Spec）
  const { density, densityClass, visibleKeys, visibleColumns, panelRef, isFullscreen, toggleFullscreen } =
    useTableView('invoice-manage', columnDefs)
  const syncLogsVisible = ref(false)
  const syncLogsLoading = ref(false)
  const syncLogs = ref([])
  const syncLogsTitle = ref('')
  let showIssues = () => {}
  const deletionGuard = createInvoiceSubmissionGuard(reactive(new Set()))
  const isInvoiceDeleting = id => deletionGuard.isPending(id)

  async function loadSummary() {
    const [dateFrom, dateTo] = summaryDateRange.value || []
    if (!dateFrom || !dateTo) return
    const requestId = ++summaryRequestId
    summaryController?.abort()
    const controller = new AbortController()
    summaryController = controller
    summaryLoading.value = true
    summaryError.value = ''
    try {
      const result = await getInvoiceSummary({ date_from: dateFrom, date_to: dateTo }, { signal: controller.signal, suppressToast: true })
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
    const [loaded] = await Promise.all([listPage.fetchList(), loadSummary()])
    return loaded
  }

  function handleSearch() {
    return listPage.handleSearch()
  }

  async function refreshUpdate() {
    const [loaded] = await Promise.all([listPage.refreshUpdate(), loadSummary()])
    return loaded
  }

  async function handleSaved({ created = false } = {}) {
    // Invoice lists are sorted by created_at descending; a new invoice belongs on page one.
    const [loaded] = await Promise.all([created ? listPage.refreshCreate() : listPage.refreshUpdate(), loadSummary()])
    return loaded
  }

  async function validateAndSync(id) {
    const outcome = await validateThenSync(id, showIssues)
    if (outcome !== INVOICE_SYNC_OUTCOME.DUPLICATE) await refreshUpdate()
  }

  async function resolveUncertain(row, resolution) {
    try {
      let xiaomanOrderId = null
      if (resolution === 'bind_order') {
        const result = await promptAction(
          '请填写已在 OKKI 后台确认的数字订单 ID',
          '绑定已生成订单',
          { inputPattern: /^\d+$/, inputErrorMessage: '请输入有效的数字订单 ID' },
        )
        xiaomanOrderId = result.value.trim()
      }
      const reasonResult = await promptAction(
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
      await refreshUpdate()
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
    if (row.status === 'cancelled' || isInvoiceSyncing(row.id)) return
    try {
      await deletionGuard.run(row.id, async () => {
        if (usesRelatedInvoiceDeletion(row)) {
          return runRelatedInvoiceDeletion(row.id, {
            preview: previewInvoiceDeletion,
            remove: deleteInvoiceWithRelated,
            refresh: refreshUpdate,
            notify: notifyFeedback,
            isCancelled: isFeedbackCancelled,
            showBlockers: message => alertAction(h('div', message.split('\n').map(line => h('p', line))), '暂时无法删除', { type: 'warning', confirmButtonText: '知道了' }),
            confirm: message => confirmAction(h('div', message.split('\n').map(line => h('p', line))), '删除订单及关联单据', {
              type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger',
            }),
          })
        }
        await confirmDanger('删除', `发票 ${row.invoice_no}`)
        await deleteInvoice(row.id)
        msgSuccess('删除')
        await Promise.all([listPage.refreshRemove(), loadSummary()])
      })
    } catch (error) {
      if (!isFeedbackCancelled(error)) throw error
    }
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

  onMounted(loadSummary)
  onUnmounted(() => {
    summaryRequestId += 1
    summaryController?.abort()
  })
  function handleTableSort({ prop, order }) { return listPage.handleSortChange({ sort_field: order ? prop : undefined, sort_order: order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : undefined }) }
  return {
    handleTableSort, actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
    loading, money, money4, openSyncLogs, page, pageSize, total, removeInvoice, statusText, statusType,
    listErrorMessage, hasLoaded, hasData, dataPage, hasPendingSearch,
    handleSearch, handlePageChange, handleSaved, refreshUpdate,
    summary, summaryDateRange, summaryError, summaryLoading, loadSummary,
    syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
    isInvoiceSyncing, resolveUncertain, validateAndSync,
    isInvoiceDeleting, usesRelatedInvoiceDeletion,
    hasActiveFilters, handleSizeChange, orderTypeTone, resetFilters, statusOptions,
    columnDefs, density, densityClass, isFullscreen, panelRef, toggleFullscreen, visibleColumns, visibleKeys,
  }
}
