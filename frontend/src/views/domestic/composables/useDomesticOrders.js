/**
 * 内贸订单列表 + 详情抽屉逻辑（宪法 12/14：useListPage + feedback + DetailDrawer）。
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  attachItemRoute, deleteOrder, getOrder, getOrderWxacode, getProcessRoutes,
  listOrders, listProcessWorkers, listReports, newRequestId, revokeReport,
  shipItem, submitReport, terminateOrder,
} from '@/api/domestic'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgSuccess } from '@/utils/feedback'

export function useDomesticOrders() {
  const route = useRoute()
  const router = useRouter()

  const listApi = useListPage(
    async ({ page, page_size, ...form }) => {
      const params = { page, page_size }
      for (const key of ['keyword', 'order_type']) {
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
        order_type: '',
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
      ship_time: new Date().toISOString().slice(0, 19).replace('T', ' '),
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
    visible: false, item: null, step: null, qty: 1, workerId: null, workers: [], loading: false,
  })

  async function openReport(item, step) {
    Object.assign(reportDialog, {
      visible: true, item, step, qty: step.reportable_qty,
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
    if (!(reportDialog.qty > 0)) return ElMessage.warning('请填报工数量')
    if (!reportDialog.workerId) return ElMessage.warning('请选择实际做活的工人')
    try {
      await submitReport({
        item_id: reportDialog.item.id,
        progress_id: reportDialog.step.progress_id,
        qty: reportDialog.qty,
        on_behalf_user_id: reportDialog.workerId,
        request_id: newRequestId(),
      })
    } catch { return }
    reportDialog.visible = false
    msgSuccess('报工')
    await refreshAll()
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
  const printDialog = reactive({ visible: false, mode: 'card', itemId: null, orderId: null })

  function openPrintCard(item) {
    Object.assign(printDialog, { visible: true, mode: 'card', itemId: item.id, orderId: null })
  }

  function openQrLabel(item) {
    Object.assign(printDialog, { visible: true, mode: 'label', itemId: item.id, orderId: null })
  }

  // 进度码的 30×20 标签版（左 LOGO 右码，与流转卡二维码标签同版式）
  function openWxacodeLabel() {
    if (!wxacodeDialog.order) return
    Object.assign(printDialog, { visible: true, mode: 'wxacode', itemId: null, orderId: wxacodeDialog.order.id })
  }

  // ── 订单进度小程序码（微信扫码免登录看进度，可发客户）──
  const wxacodeDialog = reactive({ visible: false, loading: false, order: null, image: '', envVersion: 'release' })

  async function openWxacode(row) {
    Object.assign(wxacodeDialog, { visible: true, loading: true, order: row, image: '', envVersion: 'release' })
    try {
      const res = await getOrderWxacode(row.id)
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
    a.download = `进度码-${wxacodeDialog.order?.domestic_no || 'order'}.${ext}`
    a.click()
  }

  function goCreate() {
    router.push({ name: 'DomesticOrderCreate' })
  }

  const hasUnrouted = computed(
    () => (detail.value?.items || []).some(i => !i.route_id),
  )

  return {
    ...listApi,
    detailVisible, detailLoading, detail, routes, hasUnrouted,
    openDetail, refreshAll,
    shipDialog, openShip, confirmShip,
    reportDialog, openReport, confirmReport,
    logDialog, openLogs, handleRevokeReport,
    attachDialog, openAttachRoute, confirmAttachRoute,
    printDialog, openPrintCard, openQrLabel, openWxacodeLabel,
    wxacodeDialog, openWxacode, downloadWxacode,
    handleTerminate, handleDelete, goCreate,
  }
}
