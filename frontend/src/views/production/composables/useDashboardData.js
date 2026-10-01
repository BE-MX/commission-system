import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { getDashboardData } from '@/api/production'
import { currentBeijingDate, formatBeijingDate } from '@/utils/datetime'

/**
 * 生产看板数据 composable
 *
 * 调用 GET /api/production/dashboard，返回看板所需的全部响应式数据。
 * 自动 60 秒刷新（静默，不弹 loading）。
 */
export function useDashboardData() {
  const dashboardResource = useAsyncResource(async (_, { signal }) => getDashboardData({ signal, suppressToast: true }))
  const rawOrders = computed(() => dashboardResource.data.value?.orders || [])
  const kpi = computed(() => dashboardResource.data.value?.kpi || {})
  const processStats = computed(() => dashboardResource.data.value?.process_stats || [])
  const todayCompletions = computed(() => dashboardResource.data.value?.today_completions || [])
  const loading = ref(false)
  const error = dashboardResource.errorMessage
  let timer = null, interactiveRequests = 0
  async function fetch(silent = false) {
    if (!silent) { interactiveRequests++; loading.value = true }
    try { return await dashboardResource.load() }
    finally { if (!silent) loading.value = --interactiveRequests > 0 }
  }
  onMounted(() => {
    fetch(false)
    timer = setInterval(() => fetch(true), 60000)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
    dashboardResource.cancel()
  })

  // ── 衍生数据（与 ProductionDashboard.vue 原有解构对齐）──────────

  const orders = computed(() => rawOrders.value)

  const allProducts = computed(() =>
    rawOrders.value.flatMap(o => o.products || [])
  )

  const inTransit = computed(() =>
    allProducts.value.filter(p => p.status !== 'completed')
  )

  const urgent = computed(() =>
    allProducts.value.filter(p => p.is_urgent === 1 && p.status !== 'completed')
  )

  const wip = computed(() =>
    allProducts.value.filter(p => p.status === 'pending' && p.process_steps > 0)
  )

  const completedToday = computed(() => todayCompletions.value)

  // KPI 汇总（后端已算好，直接透出）
  const kpiStats = computed(() => ({
    transitCount:          kpi.value.transit_count ?? 0,
    transitQty:            kpi.value.transit_qty ?? 0,
    urgentCount:           kpi.value.urgent_count ?? 0,
    urgentCriticalCount:   kpi.value.urgent_critical_count ?? 0,
    todayDoneCount:        kpi.value.today_completed_count ?? 0,
    todayDoneQty:          kpi.value.today_completed_qty ?? 0,
    expiring7dCount:       kpi.value.expiring_7d_count ?? 0,
    wipModelCount:         kpi.value.wip_model_count ?? 0,
  }))

  // 时间轴分组（30天内，按交期日期升序）
  const timelineGroups = computed(() => {
    const todayStr = currentBeijingDate()
    const cutoffStr = formatBeijingDate(new Date(Date.now() + 30 * 86400000))

    const items = inTransit.value.filter(p => {
      if (!p.expected_delivery_date) return false
      return p.expected_delivery_date >= todayStr && p.expected_delivery_date <= cutoffStr
    })

    const map = {}
    for (const p of items) {
      const key = p.expected_delivery_date
      if (!map[key]) map[key] = []
      map[key].push(p)
    }

    return Object.keys(map)
      .sort()
      .map(date => ({
        date,
        products: map[date],
        totalQty: map[date].reduce((s, p) => s + p.order_qty, 0),
        hasUrgent: map[date].some(p => p.is_urgent === 1),
      }))
  })

  return {
    orders,
    allProducts,
    inTransit,
    urgent,
    wip,
    completedToday,
    processStats,
    kpiStats,
    timelineGroups,
    loading,
    error, dashboardResource, hasLoaded: dashboardResource.hasLoaded,
    refresh: () => fetch(false),
  }
}
