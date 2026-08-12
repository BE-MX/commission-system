<template>
  <div class="daily-report-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="daily-report-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- Page Header -->
    <div class="page-header">
      <div class="header-title">
        <div class="title-bar" />
        <h1>物流日报</h1>
      </div>
      <p class="header-desc">
        <el-icon><Clock /></el-icon>
        每日 08:30 自动生成，汇总您名下所有运单状态
      </p>
    </div>

    <div class="report-layout">
      <!-- ===== 左侧日历 ===== -->
      <div class="left-panel">
        <div class="calendar-card lg-card is-static">
          <!-- 日历头部 -->
          <div class="calendar-header">
            <div class="calendar-title">
              <span class="year-month">{{ calendarYear }} 年 {{ calendarMonth + 1 }} 月</span>
              <el-tag size="small" class="realtime-tag">实时</el-tag>
            </div>
            <div class="calendar-nav">
              <button class="nav-btn" @click="goPrevMonth">
                <el-icon><ArrowLeft /></el-icon>
              </button>
              <button class="nav-btn today-btn" @click="goToday">今天</button>
              <button class="nav-btn" @click="goNextMonth">
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>
          </div>

          <!-- 星期标题 -->
          <div class="weekdays">
            <div v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</div>
          </div>

          <!-- 日期网格 -->
          <div class="days-grid">
            <div
              v-for="(day, i) in calendarDays"
              :key="`${day.fullDate}-${i}`"
              class="day-cell"
              :class="{
                'other-month': !day.isCurrent,
                'is-today': day.isToday,
                'is-selected': selectedDate === day.fullDate,
                'has-data': day.hasData,
              }"
              @click="day.isCurrent && selectDate(day.fullDate)"
            >
              <span class="day-number">{{ day.date }}</span>
              <span
                v-if="day.isCurrent && day.hasData"
                class="data-dot"
                :class="{ 'selected': selectedDate === day.fullDate }"
              />
            </div>
          </div>

          <!-- 底部图例 -->
          <div class="calendar-legend">
            <div class="legend-item">
              <span class="legend-dot selected" />
              <span>选中</span>
            </div>
            <div class="legend-item">
              <span class="legend-dot today" />
              <span>今天</span>
            </div>
            <div class="legend-item">
              <span class="legend-dot has-data" />
              <span>有日报</span>
            </div>
          </div>
        </div>

        <!-- 快捷统计卡 -->
        <div class="quick-stats">
          <div class="quick-stat-card blue lg-card">
            <div class="quick-stat-icon">
              <el-icon><Box /></el-icon>
            </div>
            <div class="quick-stat-info">
              <div class="quick-stat-label">本月总运单</div>
              <div class="quick-stat-value">{{ monthTotal }}</div>
            </div>
          </div>
          <div class="quick-stat-card green lg-card">
            <div class="quick-stat-icon">
              <el-icon><TrendCharts /></el-icon>
            </div>
            <div class="quick-stat-info">
              <div class="quick-stat-label">本月签收率</div>
              <div class="quick-stat-value">{{ monthRate }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 右侧内容区 ===== -->
      <div class="right-panel">
        <div v-if="loading" class="loading-state lg-card is-static">
          <el-skeleton :rows="12" animated />
        </div>

        <div v-else-if="!reportExists" class="empty-state lg-card is-static" key="empty">
          <div class="empty-icon-wrap">
            <div class="empty-icon-bg" />
            <el-icon class="empty-icon"><MessageBox /></el-icon>
          </div>
          <p class="empty-title">{{ selectedDate }} 暂无日报</p>
          <p class="empty-sub">
            <el-icon><Clock /></el-icon>
            日报将于每日 08:30 自动生成
          </p>
          <GlassButton
            variant="primary"
            :left-icon="Refresh"
            :loading="generating"
            style="margin-top: 16px"
            @click="handleGenerate"
          >
            生成日报
          </GlassButton>
        </div>

        <div v-else class="report-content" key="content">
          <!-- 日期标题栏 -->
          <div class="report-header-bar lg-card is-static">
            <div>
              <h3 class="report-date-title">{{ selectedDate }} 物流日报</h3>
              <p v-if="reportSummary" class="report-summary">{{ reportSummary }}</p>
            </div>
            <div class="report-actions">
              <GlassButton
                variant="primary"
                size="sm"
                :left-icon="Refresh"
                :loading="generating"
                @click="handleGenerate"
              >
                生成日报
              </GlassButton>
              <el-tag v-if="reportData?.is_pushed" type="success" size="small">已推送</el-tag>
              <el-tag v-else type="info" size="small">未推送</el-tag>
            </div>
          </div>

          <!-- 四宫格统计 -->
          <div class="stats-grid">
            <div class="stat-card total lg-card">
              <div class="stat-icon">
                <el-icon><Grid /></el-icon>
              </div>
              <div class="stat-label">总运单</div>
              <div class="stat-value">{{ reportStats.total }}</div>
            </div>
            <div class="stat-card transit lg-card">
              <div class="stat-icon">
                <el-icon><Van /></el-icon>
              </div>
              <div class="stat-label">运输中</div>
              <div class="stat-value">{{ reportStats.transit }}</div>
            </div>
            <div class="stat-card delivered lg-card">
              <div class="stat-icon">
                <el-icon><CircleCheck /></el-icon>
              </div>
              <div class="stat-label">已签收</div>
              <div class="stat-value">{{ reportStats.delivered }}</div>
            </div>
            <div class="stat-card exception lg-card">
              <div class="stat-icon">
                <el-icon><Warning /></el-icon>
              </div>
              <div class="stat-label">异常</div>
              <div class="stat-value">{{ reportStats.exception }}</div>
            </div>
          </div>

          <!-- 运单明细表格 -->
          <div v-if="reportShipments.length > 0" class="shipment-section">
            <h4 class="section-title">
              <el-icon><List /></el-icon>
              运单明细
            </h4>
            <el-table :data="reportShipments" size="small" class="shipment-table list-table" border>
              <el-table-column prop="waybill_no" label="运单号" min-width="130" show-overflow-tooltip sortable>
                <template #default="{ row }">
                  <strong>{{ row.waybill_no }}</strong>
                </template>
              </el-table-column>
              <el-table-column prop="carrier_name" label="物流商" min-width="90" show-overflow-tooltip sortable />
              <el-table-column prop="receiver_country" label="目的国" min-width="80" show-overflow-tooltip sortable />
              <el-table-column prop="unified_status" label="状态" min-width="90" sortable>
                <template #default="{ row }">
                  <span :class="`status-badge status-${row.unified_status}`">{{ row.status_label }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="estimated_delivery_date" label="预计送达" min-width="100" sortable />
            </el-table>
          </div>

          <!-- 日报 HTML（后端渲染） -->
          <div v-if="reportHtml" class="html-section lg-card is-static">
            <div class="report-html" v-html="reportHtml" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import {
  Clock, ArrowLeft, ArrowRight, Grid, TrendCharts,
  MessageBox, Van, CircleCheck, Warning, List, Document, Refresh,
} from '@element-plus/icons-vue'

import { useShippingDailyReport } from './composables/useShippingDailyReport'

const {
  WEEKDAYS,
  calendarYear, calendarMonth, selectedDate,
  loading, generating,
  reportExists, reportHtml,
  reportShipments, reportStats, reportSummary,
  monthTotal, monthRate,
  calendarDays,
  goPrevMonth, goNextMonth, goToday, selectDate,
  handleGenerate,
} = useShippingDailyReport()
</script>

<style scoped>
.daily-report-page {
  padding: 20px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.daily-report-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-drawer/el-dialog 的 .el-overlay position: fixed */
.daily-report-page .page-header,
.daily-report-page .report-layout {
  position: relative;
  z-index: 1;
}
.page-header {
  margin-bottom: 20px;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.title-bar {
  width: 4px;
  height: 24px;
  background: linear-gradient(to bottom, var(--color-primary), #c49b52);
  border-radius: 2px;
}
.header-title h1 {
  font-size: 22px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0;
}
.header-desc {
  margin: 0 0 0 16px;
  color: #8b95a5;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.report-layout {
  display: flex;
  gap: 20px;
  align-items: stretch;
  height: calc(100vh - 100px);
}
.left-panel {
  width: 380px;
  flex-shrink: 0;
  overflow-y: auto;
}
.right-panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding-right: 4px;
}

/* ===== 日历卡片 ===== */
/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影），这里只留布局 */
.calendar-card {
  overflow: hidden;
}
.calendar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e5ef;
}
.calendar-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.year-month {
  font-size: 16px;
  font-weight: 700;
  color: #1a1a2e;
}
.realtime-tag {
  background: #fef9f0 !important;
  color: #b08d4f !important;
  border-color: #f5e0b5 !important;
}
.calendar-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}
.nav-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b95a5;
  cursor: pointer;
  transition: color 0.2s, background-color 0.2s, border-color 0.2s;
}
.nav-btn:hover {
  background: #f0f2f7;
}
.today-btn {
  width: auto;
  padding: 0 12px;
  background: linear-gradient(to right, var(--color-primary), #c49b52) !important;
  color: #fff !important;
  font-size: 12px;
  font-weight: 500;
}
.today-btn:hover {
  box-shadow: 0 2px 8px rgba(212, 175, 110, 0.3);
}

.weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  padding: 12px 16px 4px;
}
.weekday {
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: #8b95a5;
  padding: 8px 0;
}

.days-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  padding: 0 16px 12px;
  gap: 4px;
}
.day-cell {
  aspect-ratio: 1;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  cursor: pointer;
  transition: color 0.2s, background-color 0.2s, border-color 0.2s, box-shadow 0.2s;
  position: relative;
  border: 1px solid transparent;
}
.day-cell.other-month {
  color: #c0c8d4;
  cursor: default;
}
.day-cell:not(.other-month):hover {
  background: #f0f2f7;
}
.day-cell.is-today {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 700;
  border-color: #bfdbfe;
}
.day-cell.is-selected {
  background: linear-gradient(135deg, var(--color-primary), #c49b52);
  color: #fff;
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(212, 175, 110, 0.25);
  transform: scale(1.05);
}
.day-cell.has-data:not(.is-selected):not(.is-today) {
  background: #fafbfe;
  font-weight: 500;
}
.day-cell.has-data:not(.is-selected):not(.is-today):hover {
  background: #fef9f0;
  border-color: rgba(212, 175, 110, 0.3);
}
.data-dot {
  position: absolute;
  bottom: 4px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-primary);
}
.data-dot.selected {
  background: rgba(255,255,255,0.7);
}

.calendar-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  border-top: 1px solid #f0f2f7;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #8b95a5;
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.legend-dot.selected {
  background: linear-gradient(135deg, var(--color-primary), #c49b52);
}
.legend-dot.today {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}
.legend-dot.has-data {
  background: var(--color-primary);
}

/* ===== 快捷统计 ===== */
.quick-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 16px;
}
/* 玻璃质感由 .lg-card 提供，这里只留布局 */
.quick-stat-card {
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.quick-stat-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}
.quick-stat-card.blue .quick-stat-icon {
  background: #eff6ff;
  color: #2563eb;
}
.quick-stat-card.green .quick-stat-icon {
  background: #ecfdf5;
  color: #059669;
}
.quick-stat-label {
  font-size: 11px;
  color: #8b95a5;
  margin-bottom: 2px;
}
.quick-stat-value {
  font-size: 20px;
  font-weight: 700;
  font-family: monospace;
}
.quick-stat-card.blue .quick-stat-value {
  color: #2563eb;
}
.quick-stat-card.green .quick-stat-value {
  color: #059669;
}

/* ===== 右侧内容 ===== */
/* 玻璃质感由 .lg-card 提供，这里只留布局 */
.loading-state {
  padding: 24px;
}
.empty-state {
  min-height: 500px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.empty-icon-wrap {
  position: relative;
  width: 96px;
  height: 96px;
  margin-bottom: 20px;
}
.empty-icon-bg {
  position: absolute;
  inset: 0;
  background: linear-gradient(to bottom right, rgba(212, 175, 110, 0.1), transparent);
  border-radius: 50%;
}
.empty-icon {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48px;
  color: #d0d5dd;
}
.empty-title {
  font-size: 15px;
  font-weight: 500;
  color: #8b95a5;
  margin: 0 0 8px;
}
.empty-sub {
  font-size: 13px;
  color: #a0aec0;
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
}

.report-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.report-header-bar {
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.report-date-title {
  font-size: 17px;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 4px;
}
.report-summary {
  font-size: 12px;
  color: #8b95a5;
  margin: 0;
}
.report-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ===== 四宫格统计 ===== */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
/* 玻璃质感由 .lg-card 提供（含 hover 上浮），这里只留布局与状态描边色 */
.stat-card {
  padding: 16px;
  transition: transform 0.2s;
}
.stat-card.total {
  border-color: #bfdbfe;
}
.stat-card.transit {
  border-color: #fde68a;
}
.stat-card.delivered {
  border-color: #a7f3d0;
}
.stat-card.exception {
  border-color: #fecaca;
}
.stat-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  margin-bottom: 10px;
}
.stat-card.total .stat-icon {
  background: #eff6ff;
  color: #2563eb;
}
.stat-card.transit .stat-icon {
  background: #fffbeb;
  color: #d97706;
}
.stat-card.delivered .stat-icon {
  background: #ecfdf5;
  color: #059669;
}
.stat-card.exception .stat-icon {
  background: #fef2f2;
  color: #dc2626;
}
.stat-label {
  font-size: 11px;
  color: #8b95a5;
  margin-bottom: 4px;
}
.stat-value {
  font-size: 26px;
  font-weight: 700;
  font-family: monospace;
}
.stat-card.total .stat-value {
  color: #2563eb;
}
.stat-card.transit .stat-value {
  color: #d97706;
}
.stat-card.delivered .stat-value {
  color: #059669;
}
.stat-card.exception .stat-value {
  color: #dc2626;
}

/* ===== 运单表格 ===== */
/* 表格面板：同款渐变玻璃（同 invoice-manage.css 的 .invoice-panel） */
.shipment-section {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
  padding: 20px;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.shipment-section :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title .el-icon {
  font-size: 16px;
  color: var(--color-primary);
}
.shipment-table {
  --el-table-border-color: #f0f2f7;
}
.status-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
.status-picked_up { background: #eff6ff; color: #1d4ed8; }
.status-in_transit { background: #fef3c7; color: #92400e; }
.status-customs_hold { background: #fee2e2; color: #991b1b; }
.status-out_for_delivery { background: #dbeafe; color: #1e40af; }
.status-delivered { background: #d1fae5; color: #065f46; }
.status-exception { background: #fee2e2; color: #991b1b; }
.status-returned { background: #f3f4f6; color: #4b5563; }

/* ===== HTML 日报 ===== */
/* 玻璃质感由 .lg-card 提供，这里只留布局 */
.html-section {
  padding: 20px;
}
.report-html {
  overflow-x: auto;
}
.report-html :deep(*) {
  max-width: 100%;
}
</style>
