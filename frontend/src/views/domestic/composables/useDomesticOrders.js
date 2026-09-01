/**
 * 内贸订单列表 + 详情抽屉逻辑（宪法 12/14：useListPage + feedback + DetailDrawer）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  attachItemRoute, deleteOrder, exportOrder, getItemWxacode, getOptions, getOrder, getProcessRoutes,
  listDomesticSkips, listOrders, listProcessWorkers, listReports, newRequestId,
  revokeDomesticSkip, revokeReport, shipItem, skipDomesticStep,
  submitDraftOrder, submitReport, terminateOrder,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { downloadBlob } from '@/utils/download'
import { currentBeijingDateTime } from '@/utils/datetime'
import { normalizeOutcomeAllocation } from '@/views/domestic/conditionalRouting'

export function useDomesticOrders() {
  const route = useRoute()
  const router = useRouter()
  const filterOptions = ref({ order_categories: [], order_types: [], order_channels: [] })

  const listApi = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      for (const key of ['keyword', 'order_category', 'order_type', 'order_channel']) {
        if (form[key]) params[key] = form[key]
      }
      if (form.status !== '' && form.status !== null) params.status = form.status
      if (form.dateRange?.length === 2) {
        params.date_start = form.dateRange[0]
        params.date_end = form.dateRange[1]
      }
      const res = await listOrders(params)
      return res.data || {}
    },
    {
      searchForm: {
        keyword: route.query.keyword || '',
        status: '',
        order_category: '',
        order_type: '',
        order_channel: '',
        dateRange: [],
      },
    },
  )

  // ── 详情抽屉 ──
  const detailVisible = ref(false)
  const detailLoading = ref(false)
  const detail = ref(null)
  const routes = ref([])

  async function loadDetail(orderId) {
    detailLoading.value = true
    try {
      const res = await getOrder(orderId)
      detail.value = res.data
    } finally {
      detailLoading.value = false
    }
  }

  async function openDetail(row) {
    detailVisible.value = true
    detail.value = null
    await loadDetail(row.id)
    if (!routes.value.length) {
      try {
        const res = await getProcessRoutes()
        routes.value = res.data || []
      } catch { /* 拦截器已提示 */ }
    }
  }

  async function refreshAll() {
    if (detail.value) await loadDetail(detail.value.id)
    await listApi.fetchList()
  }

  // ── 发货登记 ──
  const shipDialog = reactive({ visible: false, item: null, ship_time: null, ship_weight: null })

  function openShip(item) {
    Object.assign(shipDialog, {
      visible: true, item,
      ship_time: currentBeijingDateTime().replace('T', ' '),
      ship_weight: null,
    })
  }

  async function confirmShip() {
    if (!shipDialog.ship_time) return ElMessage.warning('请填发货时间')
    if (!(shipDialog.ship_weight > 0)) return ElMessage.warning('请填发货克重')
    try {
      await shipItem(shipDialog.item.id, {
        ship_time: shipDialog.ship_time,
        ship_weight: shipDialog.ship_weight,
      })
    } catch { return }
    shipDialog.visible = false
    msgSuccess('发货登记')
    await refreshAll()
  }

  // ── 主站代报工（车间没带手机时的兜底口子）──
  // 必须选实际做活的工人：件数记错人 = 计件工资算错人
  const reportDialog = reactive({
    visible: false, item: null, step: null, qty: 1, outcomes: {},
    workerId: null, workers: [], loading: false,
  })

  async function openReport(item, step) {
    Object.assign(reportDialog, {
      visible: true, item, step, qty: step.reportable_qty,
      outcomes: Object.fromEntries((step.outcome_options || []).map(option => [option.code, 0])),
      workerId: null, workers: [], loading: true,
    })
    try {
      const res = await listProcessWorkers(step.process_id)
      reportDialog.workers = res.data || []
      if (reportDialog.workers.length === 1) reportDialog.workerId = reportDialog.workers[0].id
    } catch { /* 拦截器已提示 */ } finally {
      reportDialog.loading = false
    }
  }

  async function confirmReport() {
    if (!reportDialog.workerId) return ElMessage.warning('请选择实际做活的工人')
    let allocation = { qty: reportDialog.qty, outcomes: undefined }
    if (reportDialog.step.rule_type === 'decision') {
      try {
        allocation = normalizeOutcomeAllocation(
          reportDialog.step.outcome_options,
          reportDialog.outcomes,
          reportDialog.step.reportable_qty,
        )
      } catch (error) {
        return ElMessage.warning(error.message)
      }
    } else if (!(reportDialog.qty > 0)) {
      return ElMessage.warning('请填报工数量')
    }
    try {
      await submitReport({
        item_id: reportDialog.item.id,
        progress_id: reportDialog.step.progress_id,
        qty: allocation.qty,
        outcomes: allocation.outcomes,
        on_behalf_user_id: reportDialog.workerId,
        request_id: newRequestId(),
      })
    } catch { return }
    reportDialog.visible = false
    msgSuccess('报工')
    await refreshAll()
  }

  // 主管例外跳过：只改变路由通行状态，不生成报工或工资数据
  const skipDialog = reactive({
    visible: false, item: null, step: null, qty: 1, reason: '', submitting: false,
  })

  function openSkip(item, step) {
    Object.assign(skipDialog, {
      visible: true, item, step, qty: step.reportable_qty, reason: '', submitting: false,
    })
  }

  const skipAuditDialog = reactive({
    visible: false, item: null, audits: [], loading: false, revokingId: null,
  })

  async function loadSkipAudits() {
    if (!skipAuditDialog.item) return
    skipAuditDialog.loading = true
    try {
      const res = await listDomesticSkips(skipAuditDialog.item.id)
      skipAuditDialog.audits = res.data || []
    } catch { /* 拦截器保留服务端原始错误 */ } finally {
      skipAuditDialog.loading = false
    }
  }

  async function openSkipAudits(item) {
    Object.assign(skipAuditDialog, { visible: true, item, audits: [], revokingId: null })
    await loadSkipAudits()
  }

  async function confirmSkip() {
    const reason = skipDialog.reason.trim()
    if (!(skipDialog.qty > 0)) return ElMessage.warning('请填跳过数量')
    if (reason.length < 5) return ElMessage.warning('请填写至少 5 个字的异常原因')
    const item = skipDialog.item
    skipDialog.submitting = true
    try {
      await skipDomesticStep({
        item_id: item.id,
        progress_id: skipDialog.step.progress_id,
        qty: skipDialog.qty,
        reason,
        request_id: newRequestId(),
      })
    } catch {
      return
    } finally {
      skipDialog.submitting = false
    }
    skipDialog.visible = false
    msgSuccess('异常跳过')
    await refreshAll()
    if (logDialog.visible && logDialog.item?.id === item.id) await openLogs(item)
    if (skipAuditDialog.visible && skipAuditDialog.item?.id === item.id) await loadSkipAudits()
  }

  async function handleRevokeSkip(audit) {
    try {
      await confirmDanger(
        '撤销', `“${audit.process_name}”的异常跳过`,
        '如果这些件已有后续实际报工，系统会阻止撤销并说明原因。',
      )
    } catch { return }
    skipAuditDialog.revokingId = audit.skip_log_id
    try {
      await revokeDomesticSkip(audit.skip_log_id)
    } catch {
      return
    } finally {
      skipAuditDialog.revokingId = null
    }
    msgSuccess('撤销异常跳过')
    await refreshAll()
    if (logDialog.visible && logDialog.item?.id === skipAuditDialog.item?.id) {
      await openLogs(skipAuditDialog.item)
    }
    await loadSkipAudits()
  }

  // ── 报工流水与撤销 ──
  const logDialog = reactive({ visible: false, item: null, logs: [], loading: false })

  async function openLogs(item) {
    Object.assign(logDialog, { visible: true, item, logs: [], loading: true })
    try {
      const res = await listReports({ item_id: item.id, page: 1, page_size: 100 })
      logDialog.logs = res.data?.items || []
    } catch { /* 拦截器已提示 */ } finally {
      logDialog.loading = false
    }
  }

  async function handleRevokeReport(logId) {
    try {
      await confirmDanger('撤销', '这条报工记录', '撤销后本道累计数量会相应减少。')
    } catch { return }
    await revokeReport(logId)
    msgSuccess('撤销')
    await refreshAll()
    if (logDialog.item) await openLogs(logDialog.item)
  }

  // ── 补配路线 ──
  const attachDialog = reactive({ visible: false, item: null, route_id: null })

  function openAttachRoute(item) {
    Object.assign(attachDialog, { visible: true, item, route_id: null })
  }

  async function confirmAttachRoute() {
    if (!attachDialog.route_id) return ElMessage.warning('请选择工艺路线')
    let res
    try {
      res = await attachItemRoute(attachDialog.item.id, attachDialog.route_id)
    } catch { return }
    attachDialog.visible = false
    ElMessage.success(res.message || '已配好工艺路线')
    await refreshAll()
  }

  // ── 订单动作 ──
  async function handleExport(row) {
    const response = await exportOrder(row.id)
    downloadBlob(response)
  }

  async function handleSubmitDraft(row) {
    try {
      await ElMessageBox.confirm(
        `提交后将从客户充值余额扣除 ¥${Number(row.total_amount || 0).toFixed(2)}，确认继续？`,
        '提交草稿',
        { type: 'warning', confirmButtonText: '提交并扣款' },
      )
    } catch { return }
    await submitDraftOrder(row.id)
    msgSuccess('提交订单')
    await refreshAll()
  }

  async function handleTerminate(row) {
    let value
    try {
      ({ value } = await ElMessageBox.prompt('终止后这张单不能再报工。填个原因：', '终止订单', {
        type: 'warning', inputPlaceholder: '如：客户取消',
      }))
    } catch { return }  // 用户点了取消
    await terminateOrder(row.id, value)
    msgSuccess('终止')
    await refreshAll()
  }

  async function handleDelete(row) {
    try {
      await confirmDanger('删除', `订单 ${row.domestic_no}`)
    } catch { return }
    await deleteOrder(row.id)
    msgSuccess('删除')
    detailVisible.value = false
    await listApi.fetchList()
  }

  // 打印弹框：内容渲染在 iframe 里的独立文档中，打印只出那份文档，
  // 但弹框本身停在订单页上——关掉就回到原来的列表和抽屉，不用按浏览器后退
  const printDialog = reactive({ visible: false, mode: 'card', itemId: null })

  function openPrintCard(item) {
    Object.assign(printDialog, { visible: true, mode: 'card', itemId: item.id })
  }

  function openQrLabel(item) {
    Object.assign(printDialog, { visible: true, mode: 'label', itemId: item.id })
  }

  // 进度码的 30×20 标签版（左 LOGO 右码，与流转卡二维码标签同版式）
  function openWxacodeLabel() {
    if (!wxacodeDialog.item) return
    Object.assign(printDialog, { visible: true, mode: 'wxacode', itemId: wxacodeDialog.item.id })
  }

  // ── 订单产品进度小程序码（明细级，微信扫码免登录看该产品进度，可发客户）──
  const wxacodeDialog = reactive({ visible: false, loading: false, item: null, info: null, image: '', envVersion: 'release' })

  async function openWxacode(item) {
    Object.assign(wxacodeDialog, { visible: true, loading: true, item, info: null, image: '', envVersion: 'release' })
    try {
      const res = await getItemWxacode(item.id)
      wxacodeDialog.info = res.data || null
      wxacodeDialog.image = res.data?.image_base64 || ''
      wxacodeDialog.envVersion = res.data?.env_version || 'release'
    } catch { /* 拦截器已提示（正式版未发布 / IP 白名单没配会在这里报出来）*/ } finally {
      wxacodeDialog.loading = false
    }
  }

  function downloadWxacode() {
    if (!wxacodeDialog.image) return
    // 扩展名跟着 data URL 的实际 MIME 走（微信返回的是 jpeg，别写死 png）
    const ext = wxacodeDialog.image.startsWith('data:image/png') ? 'png' : 'jpg'
    const a = document.createElement('a')
    a.href = wxacodeDialog.image
    a.download = `进度码-${wxacodeDialog.info?.domestic_no || 'order'}-${wxacodeDialog.item?.id || ''}.${ext}`
    a.click()
  }

  function goCreate() {
    router.push({ name: 'DomesticOrderCreate' })
  }

  const hasUnrouted = computed(
    () => (detail.value?.items || []).some(i => !i.route_id),
  )

  onMounted(async () => {
    try {
      const res = await getOptions()
      filterOptions.value = res.data || filterOptions.value
    } catch { /* 拦截器已提示 */ }
  })

  return {
    ...listApi,
    filterOptions,
    detailVisible, detailLoading, detail, routes, hasUnrouted,
    openDetail, refreshAll,
    shipDialog, openShip, confirmShip,
    reportDialog, openReport, confirmReport,
    skipDialog, openSkip, confirmSkip,
    skipAuditDialog, openSkipAudits, loadSkipAudits, handleRevokeSkip,
    logDialog, openLogs, handleRevokeReport,
    attachDialog, openAttachRoute, confirmAttachRoute,
    printDialog, openPrintCard, openQrLabel, openWxacodeLabel,
    wxacodeDialog, openWxacode, downloadWxacode,
    handleExport, handleSubmitDraft, handleTerminate, handleDelete, goCreate,
  }
}
