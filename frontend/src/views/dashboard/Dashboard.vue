<template>
  <div class="dashboard-page anim-stagger">

    <!-- ==================== ① Hero 欢迎区 ==================== -->
    <div class="dashboard-hero">
      <div class="hero-content">
        <div class="hero-tag">ARK PLATFORM</div>
        <h1 class="hero-greeting">
          {{ authStore.user?.real_name || '用户' }}，{{ greeting }}
        </h1>
        <p class="hero-subtitle">{{ subtitleText }}</p>
        <p v-if="dailyTip" class="hero-tip">
          <el-icon class="tip-icon"><Star /></el-icon>
          <span class="tip-text">{{ dailyTip }}</span>
        </p>
      </div>
      <div class="hero-decoration">
        <div class="geo-shape geo-square" />
        <div class="geo-shape geo-hexagon" />
        <div class="geo-shape geo-circle" />
      </div>
    </div>

    <!-- ==================== ② 待办提醒区（条件渲染） ==================== -->
    <div v-if="showTodoArea" class="dashboard-todos">
      <!-- 审批待办 -->
      <div
        v-if="authStore.hasAnyPermission(['design:audit']) && pendingApprovals > 0"
        class="todo-alert todo-alert-warning"
        @click="$router.push('/design/audit')"
      >
        <div class="todo-alert-left">
          <el-icon class="todo-icon"><Bell /></el-icon>
          <span class="todo-text">您有 {{ pendingApprovals }} 条预约待审批</span>
        </div>
        <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
      </div>

      <!-- 今日拍摄提醒 -->
      <div
        v-if="authStore.hasAnyPermission(['design:manage']) && todayShootCount > 0"
        class="todo-alert todo-alert-warning"
        @click="$router.push('/design/gantt')"
      >
        <div class="todo-alert-left">
          <el-icon class="todo-icon"><Bell /></el-icon>
          <span class="todo-text">今日有 {{ todayShootCount }} 项拍摄安排</span>
        </div>
        <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
      </div>

      <!-- 归属待补充 -->
      <div
        v-if="authStore.hasAnyPermission(['customer:write']) && incompleteCount > 0"
        class="todo-alert todo-alert-primary"
        @click="$router.push('/customer/snapshot')"
      >
        <div class="todo-alert-left">
          <el-icon class="todo-icon"><Warning /></el-icon>
          <span class="todo-text">有 {{ incompleteCount }} 条客户归属信息待补充</span>
        </div>
        <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
      </div>

      <!-- 物流异常 -->
      <div
        v-if="authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal > 0"
        class="todo-alert todo-alert-danger"
        @click="$router.push('/tracking')"
      >
        <div class="todo-alert-left">
          <el-icon class="todo-icon"><WarningFilled /></el-icon>
          <span class="todo-text">检测到 {{ trackingAbnormal }} 单物流异常</span>
        </div>
        <span class="todo-link">前往处理 <el-icon class="todo-arrow"><ArrowRight /></el-icon></span>
      </div>
    </div>

    <!-- ==================== ③ 数据指标区 ==================== -->
    <div class="dashboard-metrics">
      <!-- 待补充归属 -->
      <div
        v-if="authStore.hasAnyPermission(['customer:read'])"
        class="metric-card"
        :class="{ 'metric-highlight': incompleteCount > 0 }"
      >
        <div class="metric-header">
          <span class="metric-label">待补充归属</span>
          <span class="metric-dot dot-amber" />
        </div>
        <div class="metric-value">{{ incompleteCount }}</div>
        <div class="metric-footer">
          <span v-if="incompleteCount > 0" class="metric-tag tag-pending">待处理</span>
          <span v-else class="metric-status">已全部补充</span>
        </div>
      </div>

      <!-- 本月提成批次 -->
      <div
        v-if="authStore.hasAnyPermission(['commission:read'])"
        class="metric-card"
      >
        <div class="metric-header">
          <span class="metric-label">本月提成批次</span>
          <span class="metric-dot dot-blue" />
        </div>
        <div class="metric-value">{{ batchCount }}</div>
        <div class="metric-footer">
          <el-tag v-if="latestBatch" :type="batchStatusType(latestBatch.status)" size="small" effect="plain">
            {{ batchStatusLabel(latestBatch.status) }}
          </el-tag>
          <span v-else class="metric-status">暂无批次</span>
        </div>
      </div>

      <!-- 员工总数 -->
      <div
        v-if="authStore.hasAnyPermission(['employee:read'])"
        class="metric-card"
      >
        <div class="metric-header">
          <span class="metric-label">员工总数</span>
          <span class="metric-dot dot-gray" />
        </div>
        <div class="metric-value">{{ employeeCount }}</div>
        <div class="metric-footer">
          <span class="metric-status">在职人员</span>
        </div>
      </div>

      <!-- 在途运单 -->
      <div
        v-if="authStore.hasAnyPermission(['tracking:read'])"
        class="metric-card"
      >
        <div class="metric-header">
          <span class="metric-label">在途运单</span>
          <span class="metric-dot dot-cyan" />
        </div>
        <div class="metric-value">{{ trackingCount }}</div>
        <div class="metric-footer">
          <span class="metric-status">实时跟踪中</span>
        </div>
      </div>

      <!-- 今日拍摄 -->
      <div
        v-if="authStore.hasAnyPermission(['design:read'])"
        class="metric-card"
      >
        <div class="metric-header">
          <span class="metric-label">今日拍摄</span>
          <span class="metric-dot dot-green" />
        </div>
        <div class="metric-value">{{ todayShootCount }}</div>
        <div class="metric-footer">
          <span class="metric-status">已排期</span>
        </div>
      </div>

      <!-- 待审批预约 -->
      <div
        v-if="authStore.hasAnyPermission(['design:audit'])"
        class="metric-card"
        :class="{ 'metric-highlight': pendingApprovals > 0 }"
      >
        <div class="metric-header">
          <span class="metric-label">待审批预约</span>
          <span class="metric-dot dot-amber" />
        </div>
        <div class="metric-value">{{ pendingApprovals }}</div>
        <div class="metric-footer">
          <span v-if="pendingApprovals > 0" class="metric-tag tag-pending">待审批</span>
          <span v-else class="metric-status">暂无待审</span>
        </div>
      </div>

      <!-- 最近回款 -->
      <div
        v-if="authStore.hasAnyPermission(['payment:read'])"
        class="metric-card"
      >
        <div class="metric-header">
          <span class="metric-label">最近回款</span>
          <span class="metric-dot dot-gold" />
        </div>
        <div class="metric-value">{{ formatMoney(latestPayment?.amount) }}</div>
        <div class="metric-footer">
          <span class="metric-status">{{ formatDate(latestPayment?.synced_at || latestPayment?.paid_at) }}</span>
        </div>
      </div>
    </div>

    <!-- ==================== ④ 快捷操作区 ==================== -->
    <div class="dashboard-actions">
      <!-- 回款同步 -->
      <router-link v-if="authStore.hasAnyPermission(['payment:read'])" to="/payment/sync" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><Refresh /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">回款同步</div>
          <div class="action-desc">拉取业务系统数据</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 提成批次 -->
      <router-link v-if="authStore.hasAnyPermission(['commission:read'])" to="/commission/batch" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><List /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">提成批次</div>
          <div class="action-desc">计算与确认提成</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 客户归属 -->
      <router-link v-if="authStore.hasAnyPermission(['customer:read'])" to="/customer/snapshot" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><Document /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">客户归属</div>
          <div class="action-desc">补充客户归属信息</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 员工属性 -->
      <router-link v-if="authStore.hasAnyPermission(['employee:read'])" to="/employee/attribute" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><UserFilled /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">员工属性</div>
          <div class="action-desc">设置开发/分配属性</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 主管关系 -->
      <router-link v-if="authStore.hasAnyPermission(['employee:read'])" to="/supervisor/relation" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><Connection /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">主管关系</div>
          <div class="action-desc">维护业务主管关系</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 物流跟踪 -->
      <router-link v-if="authStore.hasAnyPermission(['tracking:read'])" to="/tracking" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><Van /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">物流跟踪</div>
          <div class="action-desc">查看在途运单状态</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 提交预约 -->
      <router-link v-if="authStore.hasAnyPermission(['design:write'])" to="/design/submit" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><EditPen /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">提交预约</div>
          <div class="action-desc">新建拍摄/设计预约</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 我的预约 -->
      <router-link v-if="authStore.hasAnyPermission(['design:write'])" to="/design/my-requests" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><Document /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">我的预约</div>
          <div class="action-desc">查看我提交的预约</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 排期甘特图 -->
      <router-link v-if="authStore.hasAnyPermission(['design:read'])" to="/design/gantt" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><Calendar /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">排期甘特图</div>
          <div class="action-desc">查看设计排期视图</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 审批队列 -->
      <router-link v-if="authStore.hasAnyPermission(['design:audit'])" to="/design/audit" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-badge v-if="pendingApprovals > 0" :value="pendingApprovals" class="action-badge">
            <el-icon><Stamp /></el-icon>
          </el-badge>
          <el-icon v-else><Stamp /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">审批队列</div>
          <div class="action-desc">审批待处理的预约</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 设计管理 -->
      <router-link v-if="authStore.hasAnyPermission(['design:manage'])" to="/design/manage" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><Setting /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">设计管理</div>
          <div class="action-desc">排期与任务管理</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 设计统计 -->
      <router-link v-if="authStore.hasAnyPermission(['design:manage'])" to="/design/stats" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">设计统计</div>
          <div class="action-desc">查看设计业务数据</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 用户管理 -->
      <router-link v-if="authStore.hasAnyPermission(['user:read'])" to="/system/users" class="action-card">
        <div class="action-icon-wrapper action-bg-dark">
          <el-icon><User /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">用户管理</div>
          <div class="action-desc">管理系统用户</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>

      <!-- 角色权限 -->
      <router-link v-if="authStore.hasAnyPermission(['user:read'])" to="/system/roles" class="action-card">
        <div class="action-icon-wrapper action-bg-gold">
          <el-icon><Lock /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">角色权限</div>
          <div class="action-desc">配置角色与权限</div>
        </div>
        <el-icon class="action-arrow"><ArrowRight /></el-icon>
      </router-link>
    </div>

    <!-- ==================== ⑤ 动态概览区 ==================== -->
    <div class="dashboard-overview">
      <!-- 左侧：最近动态 -->
      <div class="overview-panel">
        <div class="panel-header">
          <h3 class="panel-title">最近动态</h3>
        </div>

        <!-- 提成批次 -->
        <div v-if="recentCommissions.length > 0" class="activity-section">
          <div class="activity-list">
            <div v-for="item in recentCommissions.slice(0, 3)" :key="item.id" class="activity-item">
              <div class="activity-main">
                <span class="activity-name">{{ item.name }}</span>
                <span class="activity-status" :class="`status-${item.status}`">{{ item.statusText }}</span>
              </div>
              <div class="activity-meta">{{ item.time }}</div>
            </div>
          </div>
          <router-link to="/commission/batch" class="panel-link">查看全部 <el-icon><ArrowRight /></el-icon></router-link>
        </div>

        <!-- 运单更新 -->
        <div v-else-if="recentTrackings.length > 0" class="activity-section">
          <div class="activity-list">
            <div v-for="item in recentTrackings.slice(0, 3)" :key="item.id" class="activity-item">
              <div class="activity-main">
                <span class="activity-name">{{ item.waybillNo }}</span>
                <span class="activity-status" :class="`status-${item.status}`">{{ item.statusText }}</span>
              </div>
              <div class="activity-meta">{{ item.time }}</div>
            </div>
          </div>
          <router-link to="/tracking" class="panel-link">查看全部 <el-icon><ArrowRight /></el-icon></router-link>
        </div>

        <!-- 设计预约 -->
        <div v-else-if="recentDesigns.length > 0" class="activity-section">
          <div class="activity-list">
            <div v-for="item in recentDesigns.slice(0, 3)" :key="item.id" class="activity-item">
              <div class="activity-main">
                <span class="activity-name">{{ item.customerName }}</span>
                <span class="activity-status" :class="`status-${item.status}`">{{ item.statusText }}</span>
              </div>
              <div class="activity-meta">{{ item.meta }}</div>
            </div>
          </div>
          <router-link to="/design/my-requests" class="panel-link">查看全部 <el-icon><ArrowRight /></el-icon></router-link>
        </div>

        <!-- 回款记录 -->
        <div v-else-if="recentPayments.length > 0" class="activity-section">
          <div class="activity-list">
            <div v-for="item in recentPayments.slice(0, 3)" :key="item.id" class="activity-item">
              <div class="activity-main">
                <span class="activity-name">{{ item.customerName }}</span>
                <span class="activity-amount">{{ item.amount }}</span>
              </div>
              <div class="activity-meta">{{ item.time }}</div>
            </div>
          </div>
          <router-link to="/payment/sync" class="panel-link">查看全部 <el-icon><ArrowRight /></el-icon></router-link>
        </div>

        <!-- 空状态 -->
        <div v-else class="activity-empty">
          <el-icon class="empty-icon"><Document /></el-icon>
          <span>暂无最近动态</span>
        </div>
      </div>

      <!-- 右侧：状态分布 -->
      <div class="overview-panel">
        <div class="panel-header">
          <h3 class="panel-title">状态分布</h3>
        </div>

        <!-- 运单状态分布 -->
        <div v-if="donutData.length > 0" class="chart-section">
          <div class="chart-donut">
            <svg viewBox="0 0 100 100" class="donut-svg">
              <circle
                v-for="(seg, idx) in donutSegments"
                :key="idx"
                cx="50" cy="50" r="40"
                fill="none"
                :stroke="seg.color"
                stroke-width="20"
                :stroke-dasharray="`${seg.arc} ${seg.circumference - seg.arc}`"
                :stroke-dashoffset="seg.offset"
                transform="rotate(-90 50 50)"
              />
            </svg>
            <div class="donut-center">
              <div class="donut-total">{{ donutTotal }}</div>
              <div class="donut-label">{{ donutLabel }}</div>
            </div>
          </div>
          <div class="chart-legend">
            <div v-for="item in donutData" :key="item.key" class="legend-item">
              <span class="legend-dot" :style="{ backgroundColor: item.color }" />
              <span class="legend-name">{{ item.label }}</span>
              <span class="legend-value">{{ item.value }}</span>
              <span class="legend-percent">{{ item.percent }}%</span>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="chart-empty">
          <el-icon class="empty-icon"><DataAnalysis /></el-icon>
          <span>暂无状态分布数据</span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

// Element Plus 图标
import {
  Bell, Warning, WarningFilled, Refresh, List, Document,
  UserFilled, Connection, Van, EditPen, Calendar, Stamp,
  Setting, TrendCharts, User, Lock, ArrowRight, DataAnalysis, Star
} from '@element-plus/icons-vue'

// API
import { getSnapshotList } from '@/api/customer'
import { getBatchList } from '@/api/commission'
import { getEmployeeList } from '@/api/employee'
import { getSyncedPayments } from '@/api/payment'
import { getShipmentList, getTrackingStats } from '@/api/tracking'
import { getRequests, getTaskList, getDesignStats } from '@/api/design'

// 日常TIPS
import dailyTipsData from '@/assets/daily-tips.json'

const authStore = useAuthStore()

// ==================== 1. 问候语 ====================
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour >= 5 && hour < 11) return '早上好'
  if (hour >= 11 && hour < 14) return '中午好'
  if (hour >= 14 && hour < 18) return '下午好'
  return '晚上好'
})

// 副文案：角色化动态显示
// 有待办数据时显示具体数量，无待办时按角色显示概括文案
const subtitleText = computed(() => {
  // 有待办数据时优先显示具体数量
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

  // 无待办时按角色显示概括文案
  if (authStore.hasAnyPermission(['design:audit'])) {
    return '审批设计预约，把控拍摄排期质量'
  }
  if (authStore.hasAnyPermission(['design:manage'])) {
    return '管理设计排期，协调拍摄资源'
  }
  if (authStore.hasAnyPermission(['commission:write'])) {
    return '核对提成数据，确认批次计算结果'
  }
  if (authStore.hasAnyPermission(['payment:read'])) {
    return '同步回款数据，核算业务业绩'
  }
  if (authStore.hasAnyPermission(['tracking:read'])) {
    return '跟踪物流动态，监控在途运单状态'
  }
  if (authStore.hasAnyPermission(['customer:write'])) {
    return '维护客户归属，完善资料信息'
  }
  if (authStore.hasAnyPermission(['employee:read'])) {
    return '管理人员属性，维护组织架构'
  }

  return '莱莎方舟 — 企业内部综合管理平台'
})

// ==================== 2. 数据状态 ====================
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

// 最近动态数据
const recentCommissions = ref([])
const recentTrackings = ref([])
const recentDesigns = ref([])
const recentPayments = ref([])

// 状态分布数据
const donutData = ref([])
const donutLabel = ref('')

// ==================== 3. 待办区域显示控制 ====================
const showTodoArea = computed(() => {
  return (authStore.hasAnyPermission(['design:audit']) && pendingApprovals.value > 0) ||
         (authStore.hasAnyPermission(['design:manage']) && todayShootCount.value > 0) ||
         (authStore.hasAnyPermission(['customer:write']) && incompleteCount.value > 0) ||
         (authStore.hasAnyPermission(['tracking:read']) && trackingAbnormal.value > 0)
})

// ==================== 4. 环形图计算 ====================
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

// ==================== 5. TIPS 随机选择 ====================
function pickDailyTip() {
  if (!dailyTipsData || dailyTipsData.length === 0) return
  // 使用 sessionStorage 记录当前会话已显示的 tip，避免刷新页面时重复
  const sessionKey = 'dashboard_tip_index'
  const usedKey = 'dashboard_tip_used'
  let used = []
  try {
    const stored = sessionStorage.getItem(usedKey)
    if (stored) used = JSON.parse(stored)
  } catch { /* ignore */ }

  // 如果全部用完，重置
  if (used.length >= dailyTipsData.length) {
    used = []
  }

  // 从未使用的索引中随机选择
  const available = dailyTipsData.map((_, i) => i).filter(i => !used.includes(i))
  const pick = available[Math.floor(Math.random() * available.length)]

  dailyTip.value = dailyTipsData[pick]
  used.push(pick)
  try {
    sessionStorage.setItem(usedKey, JSON.stringify(used))
    sessionStorage.setItem(sessionKey, String(pick))
  } catch { /* ignore */ }
}

// ==================== 6. 数据加载 ====================
onMounted(() => {
  pickDailyTip()
  loadAllData()
})

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
      // 最近动态
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
      // 运单统计
      const statsRes = await getTrackingStats()
      const stats = statsRes.data || {}
      trackingAbnormal.value = stats.exception || 0
      // 状态分布
      const dist = []
      if (stats.in_transit) dist.push({ key: 'in_transit', label: '在途', value: stats.in_transit, color: '#3B82F6', percent: 0 })
      if (stats.delivered) dist.push({ key: 'delivered', label: '已签收', value: stats.delivered, color: '#2D9F6F', percent: 0 })
      if (stats.exception) dist.push({ key: 'exception', label: '异常', value: stats.exception, color: '#DC3545', percent: 0 })
      const total = dist.reduce((s, i) => s + i.value, 0)
      dist.forEach(item => { item.percent = total > 0 ? Math.round((item.value / total) * 100) : 0 })
      donutData.value = dist
      donutLabel.value = '运单总数'
      // 最近动态
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
    // 今日拍摄
    try {
      const res = await getTaskList({ page: 1, page_size: 1 })
      todayShootCount.value = res.data?.total || 0
    } catch { /* ignore */ }

    // 待审批
    if (authStore.hasAnyPermission(['design:audit'])) {
      try {
        const res = await getRequests({ page: 1, page_size: 1 })
        pendingApprovals.value = res.data?.total || 0
      } catch { /* ignore */ }
    }

    // 设计统计
    try {
      const today = new Date()
      const startOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
      const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0)
      const res = await getDesignStats({
        start_date: startOfMonth.toISOString().split('T')[0],
        end_date: endOfMonth.toISOString().split('T')[0]
      })
      const summary = res.data?.summary || {}
      // 如果还没有运单分布数据，用设计分布
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
      // 最近动态
      const recentRes = await getRequests({ page: 1, page_size: 5 })
      const recentItems = recentRes.data?.items || []
      recentDesigns.value = recentItems.map((item, idx) => ({
        id: item.id || idx,
        customerName: item.customer_name || '-',
        status: normalizeStatus(item.status),
        statusText: translateDesignStatus(item.status),
        meta: item.expect_shoot_date ? `期望日期：${item.expect_shoot_date}` : formatDate(item.created_at)
      }))
    } catch { /* ignore */ }
  }

  // 回款记录
  if (authStore.hasAnyPermission(['payment:read'])) {
    try {
      const res = await getSyncedPayments({ page: 1, page_size: 1 })
      const items = res.data?.items || []
      latestPayment.value = items[0] || null
      // 最近动态
      const recentRes = await getSyncedPayments({ page: 1, page_size: 5 })
      const recentItems = recentRes.data?.items || []
      recentPayments.value = recentItems.map((item, idx) => ({
        id: item.id || idx,
        customerName: item.customer_name || '-',
        amount: formatMoney(item.amount),
        time: formatDate(item.synced_at || item.paid_at)
      }))
    } catch { /* ignore */ }
  }
}

// ==================== 6. 辅助函数 ====================

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
    'pending': 'warning', 'approved': 'primary', 'scheduled': 'success', 'completed': 'success',
    'PENDING_DESIGN': 'warning', 'PENDING_APPROVAL': 'warning', 'APPROVED': 'primary',
    'SCHEDULED': 'success', 'IN_PROGRESS': 'info', 'COMPLETED': 'success', 'REJECTED': 'danger'
  }
  return map[status] || 'info'
}

function translateDesignStatus(status) {
  const map = {
    'pending': '待审批', 'approved': '已通过', 'scheduled': '已排期', 'completed': '已完成',
    'PENDING_DESIGN': '待设计', 'PENDING_APPROVAL': '待审批', 'APPROVED': '已通过',
    'SCHEDULED': '已排期', 'IN_PROGRESS': '执行中', 'COMPLETED': '已完成', 'REJECTED': '已拒绝'
  }
  return map[status] || status
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
</script>

<style scoped>
/* ========== 页面容器 ========== */
.dashboard-page {
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 28px;
}

/* ========== 入场动效 ========== */
.anim-stagger > * {
  animation: fadeInUp 0.5s ease forwards;
  opacity: 0;
}
.anim-stagger > *:nth-child(1) { animation-delay: 0ms; }
.anim-stagger > *:nth-child(2) { animation-delay: 70ms; }
.anim-stagger > *:nth-child(3) { animation-delay: 140ms; }
.anim-stagger > *:nth-child(4) { animation-delay: 210ms; }
.anim-stagger > *:nth-child(5) { animation-delay: 280ms; }

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ========== Hero 欢迎区 ========== */
.dashboard-hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  overflow: hidden;
  background: linear-gradient(135deg, #141210, #1E1B18);
  border-radius: 16px;
  padding: 36px 40px;
  margin-bottom: 24px;
  min-height: 140px;
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 2;
}

.hero-tag {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--color-gold);
}

.hero-greeting {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 800;
  color: #F5F2EE;
  margin: 0;
  letter-spacing: -0.01em;
}

.hero-subtitle {
  font-family: var(--font-body);
  font-size: 14px;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
}

.hero-tip {
  display: inline-flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 14px;
  background: rgba(245, 203, 92, 0.08);
  border: 1px solid rgba(245, 203, 92, 0.15);
  border-radius: 8px;
  max-width: 520px;
}

.tip-icon {
  color: var(--color-gold);
  font-size: 14px;
  margin-top: 2px;
  flex-shrink: 0;
}

.tip-text {
  font-family: var(--font-body);
  font-size: 13px;
  color: rgba(245, 203, 92, 0.85);
  line-height: 1.5;
}

/* Hero 几何装饰 */
.hero-decoration {
  position: relative;
  width: 200px;
  height: 160px;
  flex-shrink: 0;
}

.geo-shape {
  position: absolute;
  border: 1px solid rgba(245, 203, 92, 0.15);
}

.geo-square {
  width: 80px;
  height: 80px;
  top: 20px;
  right: 40px;
  border-radius: 12px;
  animation: geoRotate 20s linear infinite;
}

.geo-hexagon {
  width: 50px;
  height: 50px;
  top: 60px;
  right: 10px;
  clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
  background: rgba(245, 203, 92, 0.08);
  border: none;
  animation: geoBreathe 3s ease-in-out infinite;
}

.geo-circle {
  width: 100px;
  height: 100px;
  top: 10px;
  right: 60px;
  border-radius: 50%;
  animation: geoBreathe 4s ease-in-out infinite reverse;
}

@keyframes geoRotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

@keyframes geoBreathe {
  0%, 100% { transform: scale(1); opacity: 0.5; }
  50%      { transform: scale(1.08); opacity: 1; }
}

/* ========== 待办提醒区 ========== */
.dashboard-todos {
  margin-bottom: 16px;
}

.todo-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 200ms ease;
  margin-bottom: 8px;
}
.todo-alert:last-child {
  margin-bottom: 0;
}
.todo-alert:hover {
  transform: translateY(-1px);
  box-shadow: var(--card-shadow-hover);
}

.todo-alert-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.todo-text {
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 500;
}

.todo-link {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.todo-alert-warning {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}
.todo-alert-warning .todo-link {
  color: var(--color-primary);
}
.todo-alert-warning .todo-link:hover {
  color: var(--color-primary-hover);
}

.todo-alert-primary {
  background: var(--color-primary-light);
  color: var(--color-primary);
}
.todo-alert-primary .todo-link {
  color: var(--color-primary);
}
.todo-alert-primary .todo-link:hover {
  color: var(--color-primary-hover);
}

.todo-alert-danger {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}
.todo-alert-danger .todo-link {
  color: var(--color-danger);
}
.todo-alert-danger .todo-link:hover {
  opacity: 0.8;
}

/* ========== 指标卡区域 ========== */
.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.metric-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px 22px;
  transition: all 250ms ease;
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--card-shadow-hover);
}
.metric-card.metric-highlight {
  border-left: 3px solid var(--color-gold);
}

.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.metric-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-secondary);
}

.metric-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-gold   { background: var(--color-gold); box-shadow: 0 0 6px rgba(245,203,92,0.4); }
.dot-amber  { background: #F5A623; box-shadow: 0 0 6px rgba(245,166,35,0.4); }
.dot-green  { background: var(--color-success); box-shadow: 0 0 6px rgba(45,159,111,0.4); }
.dot-blue   { background: var(--color-primary); box-shadow: 0 0 6px rgba(212,148,28,0.4); }
.dot-cyan   { background: #3B82F6; box-shadow: 0 0 6px rgba(59,130,246,0.4); }
.dot-gray   { background: #6B7280; box-shadow: 0 0 6px rgba(107,114,128,0.3); }

.metric-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 10px;
}

.metric-footer {
  min-height: 22px;
}

.metric-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 100px;
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 500;
}

.tag-pending {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}

.metric-status {
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-muted);
}

/* ========== 快捷操作区 ========== */
.dashboard-actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 16px 20px;
  transition: all 250ms ease;
  cursor: pointer;
  text-decoration: none;
}
.action-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--card-shadow-hover);
  border-color: var(--border-hover);
}
.action-card:hover .action-arrow {
  opacity: 1;
  transform: translateX(2px);
}

.action-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  flex-shrink: 0;
  color: #fff;
}

.action-bg-gold {
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
}
.action-bg-dark {
  background: linear-gradient(135deg, #4a5568, #1a1a2e);
}

.action-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.action-name {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.action-desc {
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-muted);
}

.action-arrow {
  color: var(--text-muted);
  opacity: 0;
  transition: all 200ms ease;
  flex-shrink: 0;
}

/* Badge 覆盖 */
.action-card :deep(.el-badge__content) {
  border: none;
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
}
.action-card :deep(.el-badge__content.is-fixed) {
  top: 4px;
  right: 4px;
}

/* ========== 动态概览区 ========== */
.dashboard-overview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.overview-panel {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  padding: 20px 22px;
  transition: all 250ms ease;
}
.overview-panel:hover {
  box-shadow: var(--card-shadow-hover);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 8px;
}

.panel-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.panel-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  text-decoration: none;
  margin-top: 12px;
  transition: color 200ms ease;
}
.panel-link:hover {
  color: var(--color-primary-hover);
}

/* 最近动态列表 */
.activity-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.activity-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
}
.activity-item:last-child {
  border-bottom: none;
}

.activity-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.activity-name {
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-meta {
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

.activity-amount {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-gold);
  white-space: nowrap;
  flex-shrink: 0;
}

/* 状态标签 */
.activity-status {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 100px;
  font-family: var(--font-body);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.status-success { background: rgba(45, 159, 111, 0.1); color: var(--color-success); }
.status-warning { background: var(--color-warning-bg); color: var(--color-warning-text); }
.status-danger  { background: var(--color-danger-bg); color: var(--color-danger); }
.status-info    { background: var(--table-header-bg); color: var(--text-secondary); }
.status-primary { background: rgba(59, 130, 246, 0.1); color: var(--color-primary); }
.status-muted   { background: var(--table-header-bg); color: var(--text-muted); }

/* 空状态 */
.activity-empty,
.chart-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: var(--text-muted);
  font-family: var(--font-body);
  font-size: 14px;
}
.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

/* ========== 环形图 ========== */
.chart-donut {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 0;
  position: relative;
}

.donut-svg {
  width: 120px;
  height: 120px;
  flex-shrink: 0;
}

.donut-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
}

.donut-total {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.donut-label {
  font-family: var(--font-body);
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.chart-legend {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-body);
  font-size: 13px;
  color: var(--text-secondary);
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}

.legend-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.legend-value {
  font-weight: 600;
  color: var(--text-primary);
  min-width: 28px;
  text-align: right;
}

.legend-percent {
  font-weight: 500;
  color: var(--text-muted);
  min-width: 40px;
  text-align: right;
}

/* ========== 响应式 ========== */
@media (max-width: 1199px) {
  .dashboard-overview {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .dashboard-page {
    padding: 16px;
  }
  .dashboard-hero {
    padding: 24px;
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
  .hero-decoration {
    display: none;
  }
  .hero-greeting {
    font-size: 22px;
  }
  .dashboard-metrics {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }
  .metric-value {
    font-size: 24px;
  }
  .dashboard-actions {
    grid-template-columns: 1fr;
  }
  .chart-donut {
    flex-direction: column;
    align-items: center;
  }
}

@media (max-width: 479px) {
  .dashboard-metrics {
    grid-template-columns: 1fr;
  }
  .todo-alert {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .activity-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}
</style>
