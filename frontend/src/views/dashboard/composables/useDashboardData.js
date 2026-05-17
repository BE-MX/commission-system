/**
 * 工作台数据 composable — 聚合各业务模块的待办/最近动态/统计
 *
 * 集中:
 *   - state: 各种 count / latest / recent 列表 / donut 数据
 *   - computed: subtitleText / showTodoArea / donutTotal / donutSegments / greeting
 *   - methods: pickDailyTip / loadAllData / 状态映射工具函数
 *
 * 全部 fetch 都有权限保护(authStore.hasAnyPermission),失败 try/catch 忽略,
 * 不让单个 API 报错阻塞 Dashboard 渲染。
 */
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

import { getSnapshotList } from '@/api/customer'
import { getBatchList } from '@/api/commission'
import { getEmployeeList } from '@/api/employee'
import { getSyncedPayments } from '@/api/payment'
import { getShipmentList, getTrackingStats } from '@/api/tracking'
import { getRequests, getTaskList, getDesignStats } from '@/api/design'

import dailyTipsData from '@/assets/daily-tips.json'


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

function toLocalISODate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function formatDate(date) {
  if (!date) return '-'
  const d = new Date(date)
  if (isNaN(d.getTime())) return '-'
  const Y = d.getFullYear()
  const M = String(d.getMonth() + 1).padStart(2, '0')
  const D = String(d.getDate()).padStart(2, '0')
  return `${Y}-${M}-${D}`
}

function formatMoney(amount) {
  if (amount === null || amount === undefined) return '-'
  const num = Number(amount)
  if (isNaN(num)) return '-'
  return '¥ ' + num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}


// ── composable ──────────────────────────────────────────


export function useDashboardData() {
  const authStore = useAuthStore()

  // 问候语
  const greeting = computed(() => {
    const hour = new Date().getHours()
    if (hour >= 5 && hour < 11) return '早上好'
    if (hour >= 11 && hour < 14) return '中午好'
    if (hour >= 14 && hour < 18) return '下午好'
    return '晚上好'
  })

  // 数据状态
  const dailyTip = ref('')
  const incompleteCount = ref(0)
  const batchCount = ref(0)
  const latestBatch = ref(null)
  const employeeCount = ref(0)
  const trackingCount = ref(0)
  const trackingAbnormal = ref(0)
  const todayShootCount = ref(0)
  const pendingApprovals = ref(0)
  const latestPayment = ref(null)

  const recentCommissions = ref([])
  const recentTrackings = ref([])
  const recentDesigns = ref([])
  const recentPayments = ref([])

  const donutData = ref([])
  const donutLabel = ref('')

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
           (authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal.value > 0)
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

  async function loadAllData() {
    // 归属待补充
    if (authStore.hasAnyPermission(['customer:read'])) {
      try {
        const res = await getSnapshotList({ is_complete: 'false', page_size: 1 })
        incompleteCount.value = res.data?.total || 0
      } catch { /* ignore */ }
    }

    // 提成批次
    if (authStore.hasAnyPermission(['commission:read'])) {
      try {
        const res = await getBatchList({ page: 1, page_size: 1 })
        batchCount.value = res.data?.total || 0
        const items = res.data?.items || []
        if (items.length > 0) latestBatch.value = items[0]
        const recentRes = await getBatchList({ page: 1, page_size: 5 })
        const recentItems = recentRes.data?.items || []
        recentCommissions.value = recentItems.map((item, idx) => ({
          id: item.id || idx,
          name: item.batch_name || '未命名批次',
          status: normalizeStatus(item.status),
          statusText: batchStatusLabel(item.status),
          time: formatDate(item.created_at)
        }))
      } catch { /* ignore */ }
    }

    // 员工总数
    if (authStore.hasAnyPermission(['employee:read'])) {
      try {
        const res = await getEmployeeList({ page: 1, page_size: 1 })
        employeeCount.value = res.data?.total || 0
      } catch { /* ignore */ }
    }

    // 运单数据
    if (authStore.hasAnyPermission(['tracking:read'])) {
      try {
        const res = await getShipmentList({ page: 1, page_size: 1 })
        trackingCount.value = res.data?.total || 0
        const statsRes = await getTrackingStats()
        const stats = statsRes.data || {}
        trackingAbnormal.value = stats.exception || 0
        const dist = []
        if (stats.in_transit) dist.push({ key: 'in_transit', label: '在途', value: stats.in_transit, color: '#3B82F6', percent: 0 })
        if (stats.delivered) dist.push({ key: 'delivered', label: '已签收', value: stats.delivered, color: '#2D9F6F', percent: 0 })
        if (stats.exception) dist.push({ key: 'exception', label: '异常', value: stats.exception, color: '#DC3545', percent: 0 })
        const total = dist.reduce((s, i) => s + i.value, 0)
        dist.forEach(item => { item.percent = total > 0 ? Math.round((item.value / total) * 100) : 0 })
        donutData.value = dist
        donutLabel.value = '运单总数'
        const recentRes = await getShipmentList({ page: 1, page_size: 5 })
        const recentItems = recentRes.data?.items || []
        recentTrackings.value = recentItems.map((item, idx) => ({
          id: item.id || idx,
          waybillNo: item.waybill_no || '-',
          status: normalizeStatus(item.current_status),
          statusText: item.current_status || '-',
          time: formatDate(item.last_event_time || item.updated_at)
        }))
      } catch { /* ignore */ }
    }

    // 设计预约数据
    if (authStore.hasAnyPermission(['design:read', 'design:audit', 'design:manage'])) {
      try {
        const res = await getTaskList({ page: 1, page_size: 1 })
        todayShootCount.value = res.data?.total || 0
      } catch { /* ignore */ }

      if (authStore.hasAnyPermission(['design:audit'])) {
        try {
          const res = await getRequests({ status: 'pending_audit', page: 1, page_size: 1 })
          pendingApprovals.value = res.data?.total || 0
        } catch { /* ignore */ }
      }

      try {
        // 设计统计 — 需要 audit/manage 才能看 (任务分布是管理视角,非业务员视角)
        if (authStore.hasAnyPermission(['design:audit', 'design:manage'])) {
          const today = new Date()
          const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
          const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0)
          const res = await getDesignStats({
            start_date: toLocalISODate(startOfMonth),
            end_date: toLocalISODate(endOfMonth)
          })
          const summary = res.data?.summary || {}
          if (donutData.value.length === 0) {
            const dist = []
            const sTotal = summary.total || 0
            const sCompleted = summary.completed || 0
            const sInProgress = summary.in_progress || 0
            const sScheduled = summary.scheduled || 0
            if (sScheduled) dist.push({ key: 'scheduled', label: '已排期', value: sScheduled, color: '#3B82F6', percent: 0 })
            if (sInProgress) dist.push({ key: 'in_progress', label: '执行中', value: sInProgress, color: '#F5CB5C', percent: 0 })
            if (sCompleted) dist.push({ key: 'completed', label: '已完成', value: sCompleted, color: '#2D9F6F', percent: 0 })
            if (sTotal - sScheduled - sInProgress - sCompleted > 0) {
              dist.push({ key: 'other', label: '其他', value: sTotal - sScheduled - sInProgress - sCompleted, color: '#a0aec0', percent: 0 })
            }
            const total = dist.reduce((s, i) => s + i.value, 0)
            dist.forEach(item => { item.percent = total > 0 ? Math.round((item.value / total) * 100) : 0 })
            donutData.value = dist
            donutLabel.value = '任务总数'
          }
        }
        // 最近动态 — 任意 design 权限可看 (service 层按身份过滤"仅本人"或"全部")
        const recentRes = await getRequests({ page: 1, page_size: 5 })
        const recentItems = recentRes.data?.items || []
        recentDesigns.value = recentItems.map((item, idx) => ({
          id: item.id || idx,
          customerName: item.customer_name || '-',
          status: normalizeStatus(item.status),
          statusText: translateDesignStatus(item.status),
          meta: item.expect_start_date ? `期望日期：${item.expect_start_date}${item.expect_end_date && item.expect_end_date !== item.expect_start_date ? ' ~ ' + item.expect_end_date : ''}` : formatDate(item.created_at)
        }))
      } catch { /* ignore */ }
    }

    // 回款记录
    if (authStore.hasAnyPermission(['payment:read'])) {
      try {
        const today = new Date()
        const thirtyDaysAgo = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 30)
        const paymentParams = {
          date_start: toLocalISODate(thirtyDaysAgo),
          date_end: toLocalISODate(today),
          page: 1,
          page_size: 1,
        }
        const res = await getSyncedPayments(paymentParams)
        const items = res.data?.items || []
        latestPayment.value = items[0] || null
        const recentRes = await getSyncedPayments({ ...paymentParams, page_size: 5 })
        const recentItems = recentRes.data?.items || []
        recentPayments.value = recentItems.map((item, idx) => ({
          id: item.id || idx,
          customerName: item.customer_name || '-',
          amount: formatMoney(item.payment_amount),
          time: formatDate(item.payment_date)
        }))
      } catch { /* ignore */ }
    }
  }

  onMounted(() => {
    pickDailyTip()
    loadAllData()
  })

  return {
    // computed
    greeting, subtitleText, showTodoArea, donutTotal, donutSegments,
    // state
    dailyTip,
    incompleteCount, batchCount, latestBatch, employeeCount,
    trackingCount, trackingAbnormal, todayShootCount, pendingApprovals, latestPayment,
    recentCommissions, recentTrackings, recentDesigns, recentPayments,
    donutData, donutLabel,
    // helpers (template 内可能用到)
    batchStatusType, batchStatusLabel,
    normalizeStatus, translateDesignStatus,
    formatDate, formatMoney,
  }
}
