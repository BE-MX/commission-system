import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import {
  deleteInvoice,
  downloadInvoiceExcel,
  downloadInvoicePdf,
  fetchInvoicePrintHtml,
  getInvoiceSyncLogs,
  listInvoices,
  syncInvoice,
  validateInvoice,
} from '@/api/invoice'

export function useInvoiceManagePage() {
  const loading = ref(false)
  const invoices = ref([])
  const filters = reactive({ keyword: '', status: '', order_type: '' })
  const pagination = reactive({ page: 1, page_size: 20, total: 0 })
  const syncLogsVisible = ref(false)
  const syncLogsLoading = ref(false)
  const syncLogs = ref([])
  const syncLogsTitle = ref('')
  let showIssues = () => {}

  const summary = computed(() => invoices.value.reduce((acc, invoice) => {
    acc.total += 1
    acc.amount += Number(invoice.total_amount || 0)
    if (invoice.status === 'ready') acc.ready += 1
    if (invoice.status === 'draft') acc.draft += 1
    return acc
  }, { total: 0, ready: 0, draft: 0, amount: 0 }))

  async function loadInvoices() {
    loading.value = true
    try {
      const params = { ...filters, page: pagination.page, page_size: pagination.page_size }
      if (!params.order_type) delete params.order_type
      const result = await listInvoices(params)
      invoices.value = result.items || []
      pagination.total = result.total || 0
    } finally {
      loading.value = false
    }
  }

  async function validateAndSync(id) {
    const validation = await validateInvoice(id)
    if (!validation.ok) return showIssues(validation.issues)
    const result = await syncInvoice(id)
    if (result.ok) ElMessage.success('已同步到小满')
    else if (result.issues?.length) showIssues(result.issues)
    else ElMessage.warning(result.message || '小满同步未完成')
    loadInvoices()
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
  const formatDateTime = value => value ? String(value).replace('T', ' ').slice(0, 16) : '-'
  const money = value => Number(value || 0).toFixed(2)
  const money4 = value => Number(value || 0).toFixed(4)
  const statusText = status => ({ draft: '草稿', ready: '可同步', synced: '已同步', sync_failed: '同步失败' })[status] || status
  const statusType = status => ({ draft: 'info', ready: 'success', synced: 'success', sync_failed: 'danger' })[status] || 'info'
  const syncText = status => ({ not_synced: '未同步', synced: '已同步', sync_failed: '失败' })[status] || status
  const syncType = status => ({ not_synced: 'info', synced: 'success', sync_failed: 'danger' })[status] || 'info'

  onMounted(loadInvoices)
  return {
    actionText, bindIssueHandler, filters, formatDateTime, handleExport, invoices, loadInvoices,
    loading, money, money4, openSyncLogs, pagination, removeInvoice, statusText, statusType,
    summary, syncLogs, syncLogsLoading, syncLogsTitle, syncLogsVisible, syncText, syncType,
    validateAndSync,
  }
}
