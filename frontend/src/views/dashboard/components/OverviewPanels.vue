<template>
  <div class="dashboard-overview">
    <!-- 左侧：最近动态 -->
    <div class="overview-panel lg-card is-static">
      <div class="panel-header">
        <h3 class="panel-title">最近动态</h3>
        <span class="panel-boundary">各来源最近 5 条，展示 3 条</span>
      </div>
      <div v-for="item in recentErrors" :key="item.key" class="resource-warning" role="status">
        {{ item.label }}{{ item.resource.hasLoaded ? '更新失败，保留上次记录' : '读取失败' }}
        <button type="button" @click="item.resource.load()">重试</button>
      </div>

      <!-- 提成批次 -->
      <div v-if="data.recentCommissions.length > 0" class="activity-section">
        <div class="activity-list">
          <div v-for="item in data.recentCommissions.slice(0, 3)" :key="item.id" class="activity-item">
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
      <div v-else-if="data.recentTrackings.length > 0" class="activity-section">
        <div class="activity-list">
          <div v-for="item in data.recentTrackings.slice(0, 3)" :key="item.id" class="activity-item">
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
      <div v-else-if="data.recentDesigns.length > 0" class="activity-section">
        <div class="activity-list">
          <div v-for="item in data.recentDesigns.slice(0, 3)" :key="item.id" class="activity-item">
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
      <div v-else-if="data.recentPayments.length > 0" class="activity-section">
        <div class="activity-list">
          <div v-for="item in data.recentPayments.slice(0, 3)" :key="item.id" class="activity-item">
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
      <div v-else-if="recentLoading" class="activity-empty" role="status">正在读取最近动态…</div>
      <div v-else-if="!recentErrors.length" class="activity-empty">
        <el-icon class="empty-icon"><Document /></el-icon>
        <span>暂无最近动态</span>
      </div>
    </div>

    <!-- 右侧：状态分布 -->
    <div class="overview-panel lg-card is-static">
      <div class="panel-header">
        <h3 class="panel-title">状态分布</h3>
      </div>
      <div v-for="item in donutErrors" :key="item.key" class="resource-warning" role="status">
        {{ item.label }}{{ item.resource.hasLoaded ? '更新失败，保留上次统计' : '读取失败' }}
        <button type="button" @click="item.resource.load()">重试</button>
      </div>

      <div v-if="data.donutData.length > 0" class="chart-section">
        <div class="chart-donut">
          <svg viewBox="0 0 100 100" class="donut-svg">
            <circle
              v-for="(seg, idx) in data.donutSegments"
              :key="idx"
              cx="50" cy="50" r="40"
              fill="none"
              :stroke="seg.color"
              stroke-width="20"
              class="donut-seg"
              :stroke-dasharray="drawn ? `${seg.arc} ${seg.circumference - seg.arc}` : `0 ${seg.circumference}`"
              :stroke-dashoffset="seg.offset"
              transform="rotate(-90 50 50)"
            />
          </svg>
          <div class="donut-center">
            <div class="donut-total">{{ data.donutTotal }}</div>
            <div class="donut-label">{{ data.donutLabel }}</div>
          </div>
        </div>
        <div class="chart-legend">
          <div v-for="item in data.donutData" :key="item.key" class="legend-item">
            <span class="legend-dot" :style="{ backgroundColor: item.color }" />
            <span class="legend-name">{{ item.label }}</span>
            <span class="legend-value">{{ item.value }}</span>
            <span class="legend-percent">{{ item.percent }}%</span>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="donutLoading" class="chart-empty" role="status">正在读取状态分布…</div>
      <div v-else-if="!donutErrors.length" class="chart-empty">
        <el-icon class="empty-icon"><DataAnalysis /></el-icon>
        <span>暂无状态分布数据</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowRight, DataAnalysis, Document } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, required: true },
})
const recentLabels = {
  recentCommissions: '提成批次', recentTrackings: '物流动态',
  recentDesigns: '设计预约', recentPayments: '回款记录',
}
const recentResources = computed(() => Object.keys(recentLabels)
  .filter(key => props.data.enabledResources.includes(key))
  .map(key => ({ key, label: recentLabels[key], resource: props.data.resources[key] })))
const recentErrors = computed(() => recentResources.value.filter(item => item.resource.error))
const recentLoading = computed(() => recentResources.value.some(item => item.resource.loading && !item.resource.hasLoaded))
const donutResources = computed(() => [
  { key: 'trackingStats', label: '物流统计', resource: props.data.resources.trackingStats },
  { key: 'designStats', label: '设计统计', resource: props.data.resources.designStats },
].filter(item => props.data.enabledResources.includes(item.key)))
const donutErrors = computed(() => donutResources.value.filter(item => item.resource.error))
const donutLoading = computed(() => donutResources.value.some(item => item.resource.loading && !item.resource.hasLoaded))

// donut 首次出现 draw-in（低频、一次性；数据到达后下一帧从 0 弧过渡到目标弧）
const drawn = ref(false)
watch(
  () => props.data.donutSegments.length,
  len => {
    if (len > 0 && !drawn.value) {
      requestAnimationFrame(() => requestAnimationFrame(() => { drawn.value = true }))
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.dashboard-overview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.overview-panel {
  padding: 20px 22px;
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
.panel-boundary { color: var(--text-muted); font-size: 11px; }
.resource-warning { margin: 8px 0; color: var(--color-warning-text); font-size: 12px; }
.resource-warning button { border: 0; background: none; color: inherit; text-decoration: underline; cursor: pointer; }

.panel-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-text);
  text-decoration: none;
  margin-top: 12px;
  transition: color 200ms ease;
}
.panel-link:hover {
  color: var(--color-primary-text);
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
.status-primary { background: rgba(59, 130, 246, 0.1); color: var(--color-primary-text); }
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

/* 环形图 */
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

.donut-seg {
  transition: stroke-dasharray 400ms var(--ease-out-strong);
}
@media (prefers-reduced-motion: reduce) {
  .donut-seg {
    transition: none;
  }
}

.donut-center {
  position: absolute;
  top: 50%;
  left: 60px;
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

@media (max-width: 1199px) {
  .dashboard-overview {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .chart-donut {
    flex-direction: column;
    align-items: center;
  }
  .donut-center {
    left: 50%;
  }
}

@media (max-width: 479px) {
  .activity-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}
</style>
