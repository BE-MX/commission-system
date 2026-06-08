<template>
  <div class="db-root" :data-theme="theme">
    <!-- 顶栏 -->
    <DashboardTopbar />

    <!-- 主体 -->
    <main class="db-main">

      <!-- ① KPI 行 -->
      <div class="db-kpi-row">
        <KpiCard
          label="在途未入库订单产品"
          :value="kpiStats.transitCount"
          :sub="`合计 ${kpiStats.transitQty} 件未入库`"
          accent-color="var(--db-accent-blue)"
          @click="openModal('transit')"
        />
        <KpiCard
          label="加急订单产品"
          :value="kpiStats.urgentCount"
          :sub="`其中 ${kpiStats.urgentCriticalCount} 件 ≤3天交货`"
          trend="⚡ 需重点关注"
          trend-type="hot"
          accent-color="var(--db-accent-red)"
          @click="openModal('urgent')"
        />
        <KpiCard
          label="今日完工入库"
          :value="kpiStats.todayDoneCount"
          :sub="`合计 ${kpiStats.todayDoneQty} 件入库`"
          accent-color="var(--db-accent-cyan)"
          @click="openModal('today')"
        />
        <KpiCard
          label="7天内到期"
          :value="kpiStats.expiring7dCount"
          trend="⚠ 请及时跟进"
          trend-type="warn"
          accent-color="var(--db-accent-gold)"
          @click="openModal('expiring')"
        />
        <KpiCard
          label="进行中产品型号"
          :value="kpiStats.wipModelCount"
          trend="正常推进中"
          trend-type="up"
          accent-color="var(--db-accent-purple)"
          @click="openModal('wip')"
        />
      </div>

      <!-- ② 状态分布 + 订单进度 -->
      <div class="db-row-2">
        <div class="db-card">
          <div class="db-card-header">
            <span class="db-card-title">
              <span class="db-card-icon db-icon-blue">◎</span>
              在途产品状态分布
            </span>
            <span class="db-badge">点击扇区查看详情</span>
          </div>
          <StatusDonutChart
            :data="statusChartData"
            :echarts-theme="echartsTheme"
            style="height:280px"
            @sector-click="onStatusSectorClick"
          />
        </div>

        <div class="db-card">
          <div class="db-card-header">
            <span class="db-card-title">
              <span class="db-card-icon db-icon-cyan">≡</span>
              各订单入库进度
            </span>
            <span class="db-badge">点击查看订单详情</span>
          </div>
          <OrderProgressList
            :orders="orders"
            @order-click="onOrderClick"
          />
        </div>
      </div>

      <!-- ③ 进行中型号 + 工序统计 + 加急区 -->
      <div class="db-row-3">
        <div class="db-col-left">
          <!-- 进行中产品型号 -->
          <div class="db-card">
            <div class="db-card-header">
              <span class="db-card-title">
                <span class="db-card-icon db-icon-purple">▶</span>
                进行中产品型号
              </span>
              <span class="db-badge">已有报工记录的产品</span>
            </div>
            <WipModelGrid
              :products="wip"
              @product-click="onOrderClick"
            />
          </div>

          <!-- 工序完成统计 -->
          <div class="db-card">
            <div class="db-card-header">
              <span class="db-card-title">
                <span class="db-card-icon db-icon-teal">▦</span>
                各工序完成数量统计
              </span>
              <span class="db-badge">点击工序查看明细</span>
            </div>
            <ProcessBarChart
              :data="processStatsForChart"
              :echarts-theme="echartsTheme"
              style="height:200px"
              @bar-click="onProcessBarClick"
            />
          </div>
        </div>

        <!-- 加急区 -->
        <div class="db-card db-urgent-card">
          <div class="db-card-header">
            <span class="db-card-title">
              <span class="db-card-icon db-icon-red">⚡</span>
              加急订单产品
            </span>
            <span class="db-badge db-badge-hot">{{ kpiStats.urgentCount }} 件</span>
          </div>
          <UrgentOrderPanel
            :products="urgent"
            :echarts-theme="echartsTheme"
            @item-click="openModal('urgent')"
          />
        </div>
      </div>

      <!-- ④ 交货时间轴 -->
      <div class="db-card">
        <div class="db-card-header">
          <span class="db-card-title">
            <span class="db-card-icon db-icon-gold">◷</span>
            即将交货时间轴（30天内）
          </span>
          <span class="db-badge">点击节点查看详情</span>
        </div>
        <DeliveryTimeline
          :groups="timelineGroupsForView"
          @node-click="onTimelineNodeClick"
        />
      </div>
    </main>

    <!-- ═══ 弹窗区 ═══ -->

    <!-- 在途明细 -->
    <BaseModal v-model="modals.transit" title="在途未入库 · 产品明细" width="860px">
      <DetailTable :columns="transitCols" :rows="inTransit">
        <template #status="{ row }">
          <span :class="['db-tag', row.is_urgent ? 'db-tag-urgent' : 'db-tag-normal']">
            {{ row.is_urgent ? '加急' : '正常' }}
          </span>
        </template>
        <template #remaining="{ row }">
          <b style="color:var(--db-accent-blue)">{{ row.order_qty - row.received_qty }}</b>
        </template>
      </DetailTable>
    </BaseModal>

    <!-- 加急明细 -->
    <BaseModal v-model="modals.urgent" title="⚡ 加急订单产品 · 全部明细" width="760px">
      <div style="height:200px;margin-bottom:16px">
        <UrgentBarChart :data="urgent" :echarts-theme="echartsTheme" style="height:100%" />
      </div>
      <DetailTable :columns="urgentCols" :rows="urgentWithDays">
        <template #days_left="{ row }">
          <b :style="{ color: row.days_left <= 1 ? 'var(--db-accent-red)' : row.days_left <= 3 ? 'var(--db-accent-gold)' : 'var(--db-accent-cyan)' }">
            {{ row.days_left <= 0 ? '已逾期' : row.days_left + '天' }}
          </b>
        </template>
        <template #progress="{ row }">
          <div class="db-inline-bar">
            <div class="db-inline-fill" :style="{ width: pct(row) + '%', background: pct(row) > 80 ? 'var(--db-accent-cyan)' : 'var(--db-accent-gold)' }"></div>
            <span>{{ pct(row) }}%</span>
          </div>
        </template>
      </DetailTable>
    </BaseModal>

    <!-- 今日完工 -->
    <BaseModal v-model="modals.today" title="今日完工入库 · 明细">
      <DetailTable :columns="todayCols" :rows="completedToday" />
    </BaseModal>

    <!-- 7天到期 -->
    <BaseModal v-model="modals.expiring" title="⚠ 7天内到期 · 产品明细" width="760px">
      <div style="height:200px;margin-bottom:16px">
        <OrderDetailBarChart :products="expiring7d" :echarts-theme="echartsTheme" style="height:100%" />
      </div>
      <DetailTable :columns="expiringCols" :rows="expiring7dWithDays">
        <template #days_left="{ row }">
          <b :style="{ color: row.days_left <= 1 ? 'var(--db-accent-red)' : row.days_left <= 3 ? 'var(--db-accent-gold)' : 'var(--db-accent-blue)' }">
            {{ row.days_left === 0 ? '今天' : row.days_left === 1 ? '明天' : row.days_left + '天' }}
          </b>
        </template>
        <template #process_pct="{ row }">
          <div class="db-inline-bar">
            <div class="db-inline-fill" :style="{ width: processPct(row) + '%' }"></div>
            <span>{{ processPct(row) }}%</span>
          </div>
        </template>
      </DetailTable>
    </BaseModal>

    <!-- 进行中型号 KPI -->
    <BaseModal v-model="modals.wip" title="进行中产品型号 · 工序进度" width="700px">
      <div style="height:320px">
        <OrderDetailBarChart
          :products="wipForChart"
          :echarts-theme="echartsTheme"
          style="height:100%"
          value-field="done_pct"
          label-suffix="%"
        />
      </div>
    </BaseModal>

    <!-- 状态分布明细 -->
    <BaseModal v-model="modals.statusDetail" :title="statusDetailTitle">
      <DetailTable :columns="statusDetailCols" :rows="statusDetailRows">
        <template #progress="{ row }">
          <div class="db-inline-bar">
            <div class="db-inline-fill" :style="{ width: pct(row) + '%' }"></div>
            <span>{{ pct(row) }}%</span>
          </div>
        </template>
      </DetailTable>
    </BaseModal>

    <!-- 订单详情 -->
    <BaseModal v-model="modals.orderDetail" :title="orderDetailTitle" width="760px">
      <div style="height:220px;margin-bottom:16px">
        <OrderDetailBarChart
          v-if="selectedOrder"
          :products="selectedOrder.products"
          :echarts-theme="echartsTheme"
          style="height:100%"
        />
      </div>
      <DetailTable v-if="selectedOrder" :columns="orderDetailCols" :rows="selectedOrder.products">
        <template #process_pct="{ row }">
          <div class="db-inline-bar">
            <div class="db-inline-fill" :style="{ width: processPct(row) + '%' }"></div>
            <span>{{ row.done_steps }}/{{ row.process_steps }}</span>
          </div>
        </template>
        <template #urgent="{ row }">
          <span v-if="row.is_urgent" class="db-tag db-tag-urgent">加急</span>
          <span v-else>—</span>
        </template>
      </DetailTable>
    </BaseModal>

    <!-- 时间轴节点明细 -->
    <BaseModal v-model="modals.tlDetail" :title="tlDetailTitle">
      <DetailTable :columns="tlDetailCols" :rows="tlDetailRows">
        <template #urgent="{ row }">
          <span v-if="row.is_urgent" class="db-tag db-tag-urgent">加急</span>
          <span v-else>—</span>
        </template>
        <template #process_pct="{ row }">
          <div class="db-inline-bar">
            <div class="db-inline-fill" :style="{ width: processPct(row) + '%' }"></div>
            <span>{{ row.done_steps }}/{{ row.process_steps }}</span>
          </div>
        </template>
      </DetailTable>
    </BaseModal>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDashboardTheme }  from './composables/useDashboardTheme'
import { useDashboardData }   from './composables/useDashboardData'

import DashboardTopbar     from '@/components/production/DashboardTopbar.vue'
import KpiCard             from '@/components/production/KpiCard.vue'
import StatusDonutChart    from '@/components/production/StatusDonutChart.vue'
import OrderProgressList   from '@/components/production/OrderProgressList.vue'
import WipModelGrid        from '@/components/production/WipModelGrid.vue'
import ProcessBarChart     from '@/components/production/ProcessBarChart.vue'
import UrgentOrderPanel    from '@/components/production/UrgentOrderPanel.vue'
import UrgentBarChart      from '@/components/production/UrgentBarChart.vue'
import OrderDetailBarChart from '@/components/production/OrderDetailBarChart.vue'
import DeliveryTimeline    from '@/components/production/DeliveryTimeline.vue'
import BaseModal           from '@/components/production/BaseModal.vue'
import DetailTable         from '@/components/production/DetailTable.vue'

// ── 主题 ──────────────────────────────────────────
const { theme } = useDashboardTheme()
const echartsTheme = computed(() => theme.value === 'dark' ? 'dark' : '')

// ── 数据 ──────────────────────────────────────────
const {
  orders, allProducts, inTransit, urgent, wip,
  completedToday, processStats, kpiStats, timelineGroups
} = useDashboardData()

// ── 衍生数据 ──────────────────────────────────────
const statusChartData = computed(() => [
  { name: '未开始', value: allProducts.value.filter(p => p.status === 'pending').length },
  { name: '进行中', value: allProducts.value.filter(p => p.status === 'in_progress').length },
  { name: '已完成', value: allProducts.value.filter(p => p.status === 'completed').length },
])

const today = new Date()
const daysLeft = d => Math.round((new Date(d) - today) / 86400000)

const expiring7d = computed(() =>
  allProducts.value.filter(p => {
    const dl = daysLeft(p.expected_delivery_date)
    return dl >= 0 && dl <= 7 && p.status !== 'completed'
  }).sort((a, b) => new Date(a.expected_delivery_date) - new Date(b.expected_delivery_date))
)

const urgentWithDays = computed(() =>
  urgent.value.map(p => ({ ...p, days_left: daysLeft(p.expected_delivery_date) }))
)
const expiring7dWithDays = computed(() =>
  expiring7d.value.map(p => ({ ...p, days_left: daysLeft(p.expected_delivery_date) }))
)
const wipForChart = computed(() =>
  wip.value.map(p => ({ ...p, done_pct: Math.round(p.done_steps / p.process_steps * 100) }))
)

// timelineGroups 字段适配
const timelineGroupsForView = computed(() =>
  timelineGroups.value.map(g => ({
    ...g,
    product_count: g.products.length,
    has_urgent:    g.hasUrgent,
    remaining_qty: g.totalQty,
    models:        g.products.map(p => p.model),
  }))
)

// processStats 字段适配
const processStatsForChart = computed(() =>
  processStats.value.map(s => ({ name: s.process, done: s.count }))
)

const pct = row => {
  if (!row.order_qty) return 0
  return Math.round(row.received_qty / row.order_qty * 100)
}
const processPct = row => {
  if (!row.process_steps) return 0
  return Math.round(row.done_steps / row.process_steps * 100)
}

// ── 弹窗状态 ──────────────────────────────────────
const modals = ref({
  transit: false, urgent: false, today: false, expiring: false,
  wip: false, statusDetail: false, orderDetail: false, tlDetail: false,
})
function openModal(key) { modals.value[key] = true }

// 状态分布弹窗
const statusDetailTitle = ref('')
const statusDetailRows  = ref([])
function onStatusSectorClick(statusName) {
  statusDetailTitle.value = statusName + ' · 产品明细'
  const map = { '进行中': 'in_progress', '已完成': 'completed', '未开始': 'pending' }
  statusDetailRows.value = allProducts.value.filter(p => p.status === map[statusName])
  modals.value.statusDetail = true
}

// 订单详情弹窗
const selectedOrder    = ref(null)
const orderDetailTitle = ref('')
function onOrderClick(orderId) {
  selectedOrder.value    = orders.value.find(o => o.order_id === orderId)
  orderDetailTitle.value = orderId + ' · 产品明细'
  modals.value.orderDetail = true
}

// 时间轴节点弹窗
const tlDetailTitle = ref('')
const tlDetailRows  = ref([])
function onTimelineNodeClick(date) {
  const dl = daysLeft(date)
  tlDetailTitle.value = `${date} 交货 · ${dl === 0 ? '今天' : dl === 1 ? '明天' : dl + '天后'}`
  tlDetailRows.value = allProducts.value.filter(
    p => p.expected_delivery_date === date && p.status !== 'completed'
  )
  modals.value.tlDetail = true
}

// 工序点击
function onProcessBarClick(name, value) {
  console.log(`工序「${name}」今日完成 ${value} 件`)
}

// ── 表格列定义 ────────────────────────────────────
const transitCols = [
  { key: 'order_id',               label: '订单号' },
  { key: 'model',                  label: '产品型号' },
  { key: 'spec_info',              label: '规格' },
  { key: 'order_qty',              label: '订单量' },
  { key: 'received_qty',           label: '已入库' },
  { key: 'remaining',              label: '未入库', slot: true },
  { key: 'expected_delivery_date', label: '交货日期' },
  { key: 'status',                 label: '状态', slot: true },
]
const urgentCols = [
  { key: 'model',                  label: '产品型号' },
  { key: 'order_qty',              label: '订单量' },
  { key: 'received_qty',           label: '已入库' },
  { key: 'progress',               label: '进度', slot: true },
  { key: 'expected_delivery_date', label: '交货日期' },
  { key: 'days_left',              label: '剩余天数', slot: true },
]
const todayCols = [
  { key: 'model',    label: '产品型号' },
  { key: 'qty',      label: '入库数量' },
  { key: 'time',     label: '入库时间' },
  { key: 'operator', label: '操作人' },
  { key: 'order_id', label: '订单号' },
]
const expiringCols = [
  { key: 'model',                  label: '产品型号' },
  { key: 'order_qty',              label: '订单量' },
  { key: 'current_process',        label: '当前工序' },
  { key: 'process_pct',            label: '工序进度', slot: true },
  { key: 'expected_delivery_date', label: '交货日期' },
  { key: 'days_left',              label: '剩余天数', slot: true },
]
const statusDetailCols = [
  { key: 'model',                  label: '产品型号' },
  { key: 'order_id',               label: '订单号' },
  { key: 'order_qty',              label: '订单量' },
  { key: 'received_qty',           label: '已入库' },
  { key: 'progress',               label: '进度', slot: true },
  { key: 'expected_delivery_date', label: '交货日期' },
]
const orderDetailCols = [
  { key: 'model',           label: '产品型号' },
  { key: 'spec_info',       label: '规格' },
  { key: 'order_qty',       label: '订单量' },
  { key: 'received_qty',    label: '已入库' },
  { key: 'current_process', label: '当前工序' },
  { key: 'process_pct',     label: '工序进度', slot: true },
  { key: 'urgent',          label: '加急', slot: true },
]
const tlDetailCols = [
  { key: 'model',        label: '产品型号' },
  { key: 'spec_info',    label: '规格' },
  { key: 'order_qty',    label: '订单量' },
  { key: 'received_qty', label: '已入库' },
  { key: 'process_pct',  label: '工序进度', slot: true },
  { key: 'urgent',       label: '加急', slot: true },
]
</script>

<style scoped>
@import '@/styles/dashboard-theme.css';

.db-root {
  min-height: 100vh;
  background: var(--db-bg-deep);
  color: var(--db-text-primary);
  font-family: 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  transition: background .3s, color .3s;
  /* 全出血：抵消 MainLayout 的内边距 */
  margin: -20px;
}

.db-main {
  padding: 20px 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* KPI 行 */
.db-kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}

/* 第二行 */
.db-row-2 {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
}

/* 第三行 */
.db-row-3 {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 16px;
}
.db-col-left {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Card */
.db-card {
  background: var(--db-bg-card);
  border: 1px solid var(--db-border);
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: var(--db-shadow);
  transition: background .3s, border-color .3s;
}

.db-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.db-card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--db-text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.db-card-icon {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 5px; font-size: 12px;
}
.db-icon-blue   { background: rgba(88,166,255,.15);  color: var(--db-accent-blue); }
.db-icon-cyan   { background: rgba(57,211,83,.12);   color: var(--db-accent-cyan); }
.db-icon-purple { background: rgba(188,140,255,.12); color: var(--db-accent-purple); }
.db-icon-teal   { background: rgba(86,212,197,.12);  color: var(--db-accent-teal); }
.db-icon-red    { background: rgba(255,107,107,.12); color: var(--db-accent-red); }
.db-icon-gold   { background: rgba(240,180,41,.12);  color: var(--db-accent-gold); }

.db-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 20px;
  background: rgba(88,166,255,.12); color: var(--db-accent-blue);
  border: 1px solid rgba(88,166,255,.25);
}
.db-badge-hot {
  background: rgba(255,107,107,.12); color: var(--db-accent-red);
  border-color: rgba(255,107,107,.25);
}

/* Tag */
.db-tag {
  display: inline-block; font-size: 10px;
  padding: 2px 6px; border-radius: 3px; font-weight: 600;
}
.db-tag-urgent {
  background: rgba(255,107,107,.15); color: var(--db-accent-red);
  border: 1px solid rgba(255,107,107,.3);
}
.db-tag-normal {
  background: rgba(88,166,255,.1); color: var(--db-accent-blue);
  border: 1px solid rgba(88,166,255,.2);
}

/* 内联进度条 */
.db-inline-bar {
  display: flex; align-items: center; gap: 6px;
}
.db-inline-bar > div {
  width: 60px; height: 5px; border-radius: 3px;
  background: var(--db-bg-deep); overflow: hidden;
  flex-shrink: 0;
}
.db-inline-fill {
  height: 100%; border-radius: 3px;
  background: var(--db-accent-blue);
  transition: width .4s ease;
}
.db-inline-bar > span {
  font-size: 11px; color: var(--db-text-muted); flex-shrink: 0;
}

/* 滚动条 */
.db-root ::-webkit-scrollbar { width: 5px; height: 5px; }
.db-root ::-webkit-scrollbar-track { background: var(--db-bg-deep); }
.db-root ::-webkit-scrollbar-thumb { background: var(--db-border); border-radius: 3px; }
</style>
