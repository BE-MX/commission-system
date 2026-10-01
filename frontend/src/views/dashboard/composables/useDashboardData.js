import { formatMoney } from '../../../utils/money.js'
/**
 * 工作台数据 composable — 聚合各业务模块的待办/最近动态/统计
 *
 * 集中:
 *   - state: 各种 count / latest / recent 列表 / donut 数据
 *   - computed: subtitleText / showTodoArea / donutTotal / donutSegments / greeting
 *   - methods: pickDailyTip / loadAllData / 状态映射工具函数
 *
 * 可选摘要和最近记录各用独立资源；失败保留同一账号/权限范围内的上次数据，
 * 单个 API 报错不会阻塞 Dashboard 其他资源。
 */
import { ref, computed, onMounted, onActivated, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAsyncResource } from '@/composables/useAsyncResource'

import { getSnapshotList } from '@/api/customer'
import { getBatchList } from '@/api/commission'
import { getEmployeeList } from '@/api/employee'
import { getSyncedPayments } from '@/api/payment'
import { getShipmentList, getTrackingStats } from '@/api/tracking'
import { getRequests, getTaskList, getDesignStats } from '@/api/design'
import { fetchGreeting, getCustomerWorkSummary } from '@/api/dashboard'

import dailyTipsData from '@/assets/daily-tips.json'
import { getTodayHolidays, getUpcomingHolidays } from '../holidays'
import { beijingCalendarDate, currentBeijingDate, currentBeijingHour, formatBeijingDate, formatCalendarDate } from '@/utils/datetime'


// ── 状态映射工具 ─────────────────────────────────────────


function batchStatusType(status) {
  return { draft: 'info', calculated: '', confirmed: 'success', voided: 'danger' }[status] || 'info'
}

function batchStatusLabel(status) {
  return { draft: '草稿', calculated: '已计算', confirmed: '已确认', voided: '已作废' }[status] || status
}

function normalizeStatus(status) {
  const map = {
    '在途': 'info', '已签收': 'success', '异常': 'danger', '其他': 'muted',
    '草稿': 'info', '已计算': 'warning', '已确认': 'success', '已作废': 'danger',
    'pending_audit': 'warning', 'pending_design': 'warning', 'scheduled': 'success',
    'in_progress': 'info', 'completed': 'success', 'rejected': 'danger', 'cancelled': 'danger',
    'PENDING_DESIGN': 'warning', 'PENDING_APPROVAL': 'warning', 'APPROVED': 'primary',
    'SCHEDULED': 'success', 'IN_PROGRESS': 'info', 'COMPLETED': 'success', 'REJECTED': 'danger'
  }
  return map[status] || 'info'
}

function translateDesignStatus(status) {
  const map = {
    'pending_audit': '待审批', 'pending_design': '待排期', 'scheduled': '已排期',
    'in_progress': '执行中', 'completed': '已完成', 'rejected': '已拒绝', 'cancelled': '已取消',
    'PENDING_DESIGN': '待排期', 'PENDING_APPROVAL': '待审批', 'APPROVED': '已通过',
    'SCHEDULED': '已排期', 'IN_PROGRESS': '执行中', 'COMPLETED': '已完成', 'REJECTED': '已拒绝'
  }
  return map[status] || status
}

function formatDate(date) {
  return formatBeijingDate(date)
}

function dashboardMoney(amount) { return formatMoney(amount, { currency: 'CNY', currencyDisplay: 'narrowSymbol', missing: '-' }) }


// ── composable ──────────────────────────────────────────


export function useDashboardData() {
  const authStore = useAuthStore()

  // 问候语
  const greeting = computed(() => {
    const hour = currentBeijingHour()
    if (hour >= 5 && hour < 11) return '早上好'
    if (hour >= 11 && hour < 14) return '中午好'
    if (hour >= 14 && hour < 18) return '下午好'
    return '晚上好'
  })

  // 问候、节假日与业务读取各自有独立生命周期。
  const dailyTip = ref('')
  const quiet = signal => ({ signal, showLoading: false, suppressToast: true })
  function page(res) {
    if (!Array.isArray(res.data?.items) || !Number.isFinite(res.data?.total)) throw new Error('摘要响应格式不正确')
    return res.data
  }
  function items(res) {
    if (!Array.isArray(res.data?.items)) throw new Error('最近记录响应格式不正确')
    return res.data.items
  }
  const resources = {
    customerWork: useAsyncResource(async (_, { signal }) => {
      const value = (await getCustomerWorkSummary(quiet(signal))).data
      if (!value || !Array.isArray(value.items) || !Number.isFinite(value.total)) throw new Error('客户事项摘要格式不正确')
      return value
    }),
    incomplete: useAsyncResource(async (_, { signal }) => page(await getSnapshotList({ is_complete: 'false', page_size: 1 }, quiet(signal)))),
    batches: useAsyncResource(async (_, { signal }) => page(await getBatchList({ page: 1, page_size: 1 }, quiet(signal)))),
    recentCommissions: useAsyncResource(async (_, { signal }) => items(await getBatchList({ page: 1, page_size: 5 }, quiet(signal))).map((item, idx) => ({
      id: item.id || idx, name: item.batch_name || '未命名批次', status: normalizeStatus(item.status),
      statusText: batchStatusLabel(item.status), time: formatDate(item.created_at),
    }))),
    employees: useAsyncResource(async (_, { signal }) => page(await getEmployeeList({ page: 1, page_size: 1 }, quiet(signal)))),
    trackingCount: useAsyncResource(async (_, { signal }) => page(await getShipmentList({ page: 1, page_size: 1 }, quiet(signal)))),
    trackingStats: useAsyncResource(async (_, { signal }) => {
      const value = (await getTrackingStats(undefined, quiet(signal))).data
      if (!value || !['in_transit', 'delivered', 'exception'].every(key => typeof value[key] === 'number' && Number.isFinite(value[key]))) throw new Error('物流统计格式不正确')
      return value
    }),
    recentTrackings: useAsyncResource(async (_, { signal }) => items(await getShipmentList({ page: 1, page_size: 5 }, quiet(signal))).map((item, idx) => ({
      id: item.id || idx, waybillNo: item.waybill_no || '-', status: normalizeStatus(item.current_status),
      statusText: item.current_status || '-', time: formatDate(item.last_event_time || item.updated_at),
    }))),
    recentShipments: useAsyncResource(async (_, { signal }) => items(await getShipmentList({
      is_active: '1', page: 1, page_size: 5, sort_field: 'updated_at', sort_order: 'desc',
    }, quiet(signal)))),
    designTasks: useAsyncResource(async (_, { signal }) => page(await getTaskList({ page: 1, page_size: 1 }, quiet(signal)))),
    approvals: useAsyncResource(async (_, { signal }) => page(await getRequests({ status: 'pending_audit', page: 1, page_size: 1 }, quiet(signal)))),
    designStats: useAsyncResource(async (_, { signal }) => {
      const [year, month] = currentBeijingDate().split('-').map(Number)
      const end = formatCalendarDate(new Date(year, month, 0))
      const summary = (await getDesignStats({ start_date: `${year}-${String(month).padStart(2, '0')}-01`, end_date: end }, quiet(signal))).data?.summary
      if (!summary || !['total', 'completed', 'in_progress', 'scheduled'].every(key => typeof summary[key] === 'number' && Number.isFinite(summary[key]))) throw new Error('设计统计格式不正确')
      return summary
    }),
    recentDesigns: useAsyncResource(async (_, { signal }) => items(await getRequests({ page: 1, page_size: 5 }, quiet(signal))).map((item, idx) => ({
      id: item.id || idx, customerName: item.customer_name || '-', status: normalizeStatus(item.status),
      statusText: translateDesignStatus(item.status),
      meta: item.expect_start_date ? `期望日期：${item.expect_start_date}${item.expect_end_date && item.expect_end_date !== item.expect_start_date ? ' ~ ' + item.expect_end_date : ''}` : formatDate(item.created_at),
    }))),
    latestPayment: useAsyncResource(async (_, { signal }) => items(await getSyncedPayments(paymentParams(1), quiet(signal)))[0] || null),
    recentPayments: useAsyncResource(async (_, { signal }) => items(await getSyncedPayments(paymentParams(5), quiet(signal))).map((item, idx) => ({
      id: item.id || idx, customerName: item.customer_name || '-', amount: dashboardMoney(item.payment_amount),
      time: formatDate(item.payment_date),
    }))),
  }
  function paymentParams(pageSize) {
    const today = currentBeijingDate()
    const start = new Date(new Date(`${today}T00:00:00+08:00`).getTime() - 30 * 86400000)
    return { date_start: formatBeijingDate(start), date_end: today, page: 1, page_size: pageSize }
  }
  const access = {
    customerWork: ['customer_pcw:read', 'customer_radar:read', 'customer:read', 'customer:read_all'],
    incomplete: ['customer:read'], batches: ['commission:read'], recentCommissions: ['commission:read'],
    employees: ['employee:read'], trackingCount: ['tracking:read'], trackingStats: ['tracking:read'],
    recentTrackings: ['tracking:read'], recentShipments: ['tracking:read'],
    designTasks: ['design:read', 'design:audit', 'design:manage'], approvals: ['design:audit'],
    designStats: ['design:audit', 'design:manage'], recentDesigns: ['design:read', 'design:audit', 'design:manage'],
    latestPayment: ['payment:read'], recentPayments: ['payment:read'],
  }
  const enabledResources = computed(() => Object.keys(resources).filter(key => authStore.hasAnyPermission(access[key])))
  const totalOf = key => computed(() => resources[key].data.value?.total ?? null)
  const incompleteCount = totalOf('incomplete')
  const batchCount = totalOf('batches')
  const latestBatch = computed(() => resources.batches.data.value?.items?.[0] ?? null)
  const employeeCount = totalOf('employees')
  const trackingCount = totalOf('trackingCount')
  const trackingAbnormal = computed(() => resources.trackingStats.data.value?.exception ?? null)
  const todayShootCount = totalOf('designTasks')
  const pendingApprovals = totalOf('approvals')
  const latestPayment = computed(() => resources.latestPayment.data.value)
  const customerWorkSummary = computed(() => resources.customerWork.data.value)
  const customerWorkSummaryError = computed(() => resources.customerWork.error.value ? '客户事项摘要暂时无法读取，请重试或打开客户工作台核验' : '')
  const recentCommissions = computed(() => resources.recentCommissions.data.value ?? [])
  const recentTrackings = computed(() => resources.recentTrackings.data.value ?? [])
  const recentShipments = computed(() => resources.recentShipments.data.value ?? [])
  const recentDesigns = computed(() => resources.recentDesigns.data.value ?? [])
  const recentPayments = computed(() => resources.recentPayments.data.value ?? [])
  const donutData = computed(() => {
    const tracking = resources.trackingStats.data.value
    const design = resources.designStats.data.value
    const source = tracking && ['in_transit', 'delivered', 'exception'].some(key => Number(tracking[key]))
      ? [['in_transit', '在途', 'var(--color-blue)'], ['delivered', '已签收', 'var(--color-success)'], ['exception', '异常', 'var(--color-danger)']].map(([key, label, color]) => ({ key, label, color, value: Number(tracking[key] || 0) }))
      : design ? [['scheduled', '已排期', 'var(--color-blue)'], ['in_progress', '执行中', 'var(--color-gold)'], ['completed', '已完成', 'var(--color-success)'], ['other', '其他', 'var(--text-muted)']].map(([key, label, color]) => ({
        key, label, color, value: key === 'other' ? Math.max(0, Number(design.total || 0) - Number(design.scheduled || 0) - Number(design.in_progress || 0) - Number(design.completed || 0)) : Number(design[key] || 0),
      })) : []
    const nonzero = source.filter(item => item.value > 0)
    const total = nonzero.reduce((sum, item) => sum + item.value, 0)
    return nonzero.map(item => ({ ...item, percent: total ? Math.round(item.value / total * 100) : 0 }))
  })
  const donutLabel = computed(() => resources.trackingStats.data.value && ['in_transit', 'delivered', 'exception'].some(key => Number(resources.trackingStats.data.value[key])) ? '运单总数' : '任务总数')

  // ── 节假日日历（纯前端计算，挂载时算一次） ──────────────
  const todayHolidays = ref([])
  const upcomingHolidays = ref([])

  // ── AI 助理每日一句 ──────────────────────────────────
  // 首屏先用本地 daily tip 占位，AI 问候回来后无感替换；
  // source: 'ai' | 'fallback' | 'tip'
  const assistantLine = ref('')
  const assistantSource = ref('tip')
  const assistantLoading = ref(false)
  let greetingSeq = 0
  let greetingController

  const GREETING_CACHE_KEY = 'ark_ai_greeting_v1'

  function todayISO() {
    return currentBeijingDate()
  }

  function buildGreetingContext() {
    const now = beijingCalendarDate()
    const hour = currentBeijingHour()
    const period = hour < 5 ? '晚上' : hour < 11 ? '上午' : hour < 14 ? '中午' : hour < 18 ? '下午' : '晚上'
    const weekday = `周${'日一二三四五六'[now.getDay()]}`
    const pending = {}
    if (authStore.hasAnyPermission(['design:audit']) && pendingApprovals.value > 0) pending['待审批预约'] = pendingApprovals.value
    if (authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal.value > 0) pending['物流异常'] = trackingAbnormal.value
    if (authStore.hasAnyPermission(['customer:write']) && incompleteCount.value > 0) pending['待补充归属'] = incompleteCount.value
    if (authStore.hasAnyPermission(['design:manage']) && todayShootCount.value > 0) pending['今日拍摄'] = todayShootCount.value
    return {
      date: todayISO(),
      weekday,
      period,
      user_name: authStore.user?.real_name || '',
      holidays_today: todayHolidays.value
        .slice(0, 8) // 与后端 GreetingContext max_length=8 对齐（元旦 12 国全中，不截断会 422）
        .map(h => `${h.country}·${h.name}`),
      upcoming_holidays: upcomingHolidays.value
        .filter(h => h.daysUntil > 0 && h.daysUntil <= 30)
        .slice(0, 4)
        .map(h => `${h.country}·${h.name}(还有${h.daysUntil}天)`),
      pending,
    }
  }

  function readGreetingCache() {
    try {
      const cached = JSON.parse(localStorage.getItem(GREETING_CACHE_KEY) || 'null')
      if (cached && cached.uid === authStore.user?.id && cached.date === todayISO()) return cached
    } catch { /* ignore */ }
    return null
  }

  async function loadGreeting(refresh = false) {
    const id = ++greetingSeq
    greetingController?.abort()
    greetingController = new AbortController()
    const signal = greetingController.signal
    if (!refresh) {
      const cached = readGreetingCache()
      if (cached?.text) {
        assistantLine.value = cached.text
        assistantSource.value = cached.source || 'ai'
        return
      }
    }
    assistantLoading.value = true
    try {
      const res = await fetchGreeting({ refresh, context: buildGreetingContext() }, { signal })
      if (id !== greetingSeq || signal.aborted) return
      const data = res.data || {}
      if (data.text) {
        assistantLine.value = data.text
        assistantSource.value = data.source || 'ai'
        try {
          localStorage.setItem(GREETING_CACHE_KEY, JSON.stringify({
            uid: authStore.user?.id,
            date: todayISO(),
            text: assistantLine.value,
            source: assistantSource.value,
          }))
        } catch { /* ignore */ }
      }
    } catch {
      // 静默降级（suppressToast 已关掉拦截器弹条）：保留现有文案与徽章——
      // 首次失败时就是本地每日一句 + 'tip'；刷新失败时旧 AI 文案不降级徽章
    } finally {
      if (id === greetingSeq && !signal.aborted) assistantLoading.value = false
    }
  }

  // 副文案 — 角色 + 待办数量动态显示
  const subtitleText = computed(() => {
    if (authStore.hasAnyPermission(['design:audit']) && pendingApprovals.value > 0) {
      return `今日有 ${pendingApprovals.value} 条设计预约待您审批`
    }
    if (authStore.hasAnyPermission(['design:manage']) && todayShootCount.value > 0) {
      return `今日有 ${todayShootCount.value} 条拍摄任务待执行`
    }
    if (authStore.hasAnyPermission(['customer:write']) && incompleteCount.value > 0) {
      return `有 ${incompleteCount.value} 条客户归属信息待补充`
    }
    if (authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal.value > 0) {
      return `当前有 ${trackingAbnormal.value} 单物流异常需关注`
    }

    if (authStore.hasAnyPermission(['design:audit'])) return '审批设计预约，把控拍摄排期质量'
    if (authStore.hasAnyPermission(['design:manage'])) return '管理设计排期，协调拍摄资源'
    if (authStore.hasAnyPermission(['commission:write'])) return '核对提成数据，确认批次计算结果'
    if (authStore.hasAnyPermission(['payment:read'])) return '同步回款数据，核算业务业绩'
    if (authStore.hasAnyPermission(['tracking:read'])) return '跟踪物流动态，监控在途运单状态'
    if (authStore.hasAnyPermission(['customer:write'])) return '维护客户归属，完善资料信息'
    if (authStore.hasAnyPermission(['employee:read'])) return '管理人员属性，维护组织架构'

    return '莱莎方舟 — 企业内部综合管理平台'
  })

  const showTodoArea = computed(() => {
    return (authStore.hasAnyPermission(['design:audit']) && pendingApprovals.value > 0) ||
           (authStore.hasAnyPermission(['design:manage']) && todayShootCount.value > 0) ||
           (authStore.hasAnyPermission(['customer:write']) && incompleteCount.value > 0) ||
           (authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal.value > 0) ||
           (customerWorkSummary.value?.total ?? 0) > 0 || !!customerWorkSummaryError.value
  })

  const donutTotal = computed(() => donutData.value.reduce((s, i) => s + i.value, 0))

  const donutSegments = computed(() => {
    const r = 40
    const circumference = 2 * Math.PI * r
    const total = donutTotal.value
    let offset = 0
    return donutData.value.map(item => {
      const arc = total > 0 ? (item.value / total) * circumference : 0
      const seg = { color: item.color, arc, circumference, offset: -offset }
      offset += arc
      return seg
    })
  })

  // 日常 TIPS — sessionStorage 去重,全部用完后重置
  function pickDailyTip() {
    if (!dailyTipsData || dailyTipsData.length === 0) return
    const sessionKey = 'dashboard_tip_index'
    const usedKey = 'dashboard_tip_used'
    let used = []
    try {
      const stored = sessionStorage.getItem(usedKey)
      if (stored) used = JSON.parse(stored)
    } catch { /* ignore */ }

    if (used.length >= dailyTipsData.length) {
      used = []
    }

    const available = dailyTipsData.map((_, i) => i).filter(i => !used.includes(i))
    const pick = available[Math.floor(Math.random() * available.length)]

    dailyTip.value = dailyTipsData[pick]
    used.push(pick)
    try {
      sessionStorage.setItem(usedKey, JSON.stringify(used))
      sessionStorage.setItem(sessionKey, String(pick))
    } catch { /* ignore */ }
  }

  // 摘要与最近集合分别请求：某个业务或某个统计失败，不阻断其他已授权资源。
  async function loadAllData() {
    await Promise.all(enabledResources.value.map(key => resources[key].load()))
  }

  const authKey = computed(() => JSON.stringify({
    id: authStore.user?.id ?? null,
    permissions: [...(authStore.permissions || [])].sort(),
    roles: [...(authStore.roles || [])].sort(),
  }))
  let mounted = false
  watch(authKey, scope => {
    for (const resource of Object.values(resources)) resource.clear()
    greetingSeq++
    greetingController?.abort()
    assistantLoading.value = false
    assistantLine.value = dailyTip.value
    assistantSource.value = 'tip'
    if (mounted && authStore.user) loadAllData().finally(() => {
      if (authKey.value === scope) loadGreeting()
    })
  }, { immediate: true, flush: 'sync' })
  onMounted(() => {
    mounted = true
    // 节假日：挂载即算（纯本地，零等待）
    todayHolidays.value = getTodayHolidays()
    upcomingHolidays.value = getUpcomingHolidays({ days: 60 })
    // 首屏 instantly 给一句本地 tip，AI 问候在业务数据就位后再请求（上下文更准）
    pickDailyTip()
    assistantLine.value = dailyTip.value
    const scope = authKey.value
    if (authStore.user) loadAllData().finally(() => {
      if (authKey.value === scope) loadGreeting()
    })
  })

  // Dashboard 被 tab KeepAlive 缓存：回切时重算节假日（本地计算，零成本），
  // 隔夜则缓存失效、重新生成当日问候；同日命中缓存时组件状态本就最新，零请求
  onActivated(() => {
    todayHolidays.value = getTodayHolidays()
    upcomingHolidays.value = getUpcomingHolidays({ days: 60 })
    if (!readGreetingCache()) loadGreeting()
  })
  onUnmounted(() => greetingController?.abort())

  return {
    // computed
    greeting, subtitleText, showTodoArea, donutTotal, donutSegments,
    // state
    dailyTip,
    incompleteCount, batchCount, latestBatch, employeeCount,
    customerWorkSummary, customerWorkSummaryError,
    resources, enabledResources,
    trackingCount, trackingAbnormal, todayShootCount, pendingApprovals, latestPayment,
    recentCommissions, recentTrackings, recentDesigns, recentPayments, recentShipments,
    donutData, donutLabel,
    todayHolidays, upcomingHolidays,
    assistantLine, assistantSource, assistantLoading,
    // methods
    loadGreeting, loadAllData,
    // helpers (template 内可能用到)
    batchStatusType, batchStatusLabel,
    normalizeStatus, translateDesignStatus,
    formatDate, formatMoney: dashboardMoney,
  }
}
