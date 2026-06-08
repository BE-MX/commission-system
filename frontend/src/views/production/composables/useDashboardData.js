import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getDashboardData } from '@/api/production'

/**
 * 生产看板数据 composable
 *
 * 调用 GET /api/production/dashboard，返回看板所需的全部响应式数据。
 * 自动 60 秒刷新（静默，不弹 loading）。
 */
export function useDashboardData() {
  const rawOrders = ref([])
  const kpi = ref({})
  const processStats = ref([])
  const todayCompletions = ref([])
  const loading = ref(true)
  const error = ref(null)

  let timer = null

  async function fetch(silent = false) {
    try {
      if (!silent) loading.value = true
      const res = await getDashboardData()
      // axios 拦截器已解包 response.data
      const data = res.data ?? res
      rawOrders.value = data.orders || []
      kpi.value = data.kpi || {}
      processStats.value = data.process_stats || []
      todayCompletions.value = data.today_completions || []
      error.value = null
    } catch (e) {
      error.value = e.message || '获取看板数据失败'
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    fetch(false)
    timer = setInterval(() => fetch(true), 60000)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
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
    const todayStr = new Date().toISOString().slice(0, 10)
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() + 30)

    const items = inTransit.value.filter(p => {
      if (!p.expected_delivery_date) return false
      const d = new Date(p.expected_delivery_date)
      return d >= new Date(todayStr) && d <= cutoff
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
    error,
    refresh: () => fetch(false),
  }
}
