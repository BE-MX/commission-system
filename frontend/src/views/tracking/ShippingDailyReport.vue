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

<style scoped src="./shipping-daily-report.css"></style>
