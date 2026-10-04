<template>
  <div class="design-stats-page">
    <!-- 金色极光背景（纯装饰；与工作台/发票页同源 styles/liquid-glass.css） -->
    <div class="design-stats-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 页面级筛选：驱动统计卡与工作量表（非纯表格筛选，保留在卡片外） -->
    <div class="toolbar">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        :clearable="false"
        class="filter-w-lg"
        @change="fetchStats"
      />
      <GlassButton :icon="Refresh" @click="fetchStats">刷新</GlassButton>
    </div>

    <!-- Summary cards -->
    <el-row :gutter="16" class="summary-cards">
      <el-col :span="6">
        <div class="stat-card emphasis lg-card">
          <div class="stat-value">{{ summary.total }}</div>
          <div class="stat-label">总任务数</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card lg-card">
          <div class="stat-value">{{ summary.completed }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card lg-card">
          <div class="stat-value">{{ summary.in_progress }}</div>
          <div class="stat-label">进行中</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card lg-card">
          <div class="stat-value">{{ summary.scheduled }}</div>
          <div class="stat-label">待排期</div>
        </div>
      </el-col>
    </el-row>

    <!-- Designer workload table -->
    <div class="section-title">设计师工作量</div>
    <div ref="panelRef" class="table-card design-stats-panel">
    <!-- 操作行：本页无主操作按钮，右侧 TableTools 四图标（Action Bar Spec） -->
    <div class="action-bar">
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columnDefs"
        :fullscreen="isFullscreen"
        @refresh="fetchStats"
        @fullscreen="toggleFullscreen"
      />
    </div>
    <el-table
      :data="designerStats"
      v-loading="loading"
      class="list-table"
      :class="densityClass"
      border
      :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
      <template #empty>
        <el-empty :image-size="96" description="暂无数据" />
      </template>
      <el-table-column v-if="visibleKeys.includes('designer-name')" prop="designer_name" label="设计师" min-width="120" max-width="180" show-overflow-tooltip sortable />
      <el-table-column v-if="visibleKeys.includes('total')" prop="total" label="总任务数" min-width="100" max-width="150" sortable />
      <el-table-column v-if="visibleKeys.includes('completed')" prop="completed" label="已完成" min-width="100" max-width="150" sortable>
        <template #default="{ row }">
          <StatusBadge type="success" size="small" effect="plain">{{ row.completed }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('in-progress')" prop="in_progress" label="进行中" min-width="100" max-width="150" sortable>
        <template #default="{ row }">
          <StatusBadge type="warning" size="small" effect="plain">{{ row.in_progress }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('avg-duration')" prop="avg_duration_days" label="平均任务时长(天)" min-width="160" max-width="240" show-overflow-tooltip sortable>
        <template #default="{ row }">
          {{ row.avg_duration_days || '-' }}
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('completion-rate')" label="完成率" min-width="160" max-width="240">
        <template #default="{ row }">
          <el-progress
            :percentage="row.total > 0 ? Math.round(row.completed / row.total * 100) : 0"
            :stroke-width="14"
            :text-inside="true"
          />
        </template>
      </el-table-column>
    </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getDesignStats } from '@/api/design'
import { beijingCalendarDate } from '@/utils/datetime'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'

// 列配置数组：TableTools 列显隐的数据源（本表无操作列）
const columnDefs = [
  { key: 'designer-name', label: '设计师' },
  { key: 'total', label: '总任务数' },
  { key: 'completed', label: '已完成' },
  { key: 'in-progress', label: '进行中' },
  { key: 'avg-duration', label: '平均任务时长(天)' },
  { key: 'completion-rate', label: '完成率' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('design-stats', columnDefs)

function getDefaultDateRange() {
  const now = beijingCalendarDate()
  const start = new Date(now.getFullYear(), now.getMonth(), 1)
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return [formatDate(start), formatDate(end)]
}

function formatDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const dateRange = ref(getDefaultDateRange())
const loading = ref(false)
const summary = reactive({ total: 0, completed: 0, in_progress: 0, scheduled: 0 })
const designerStats = ref([])

async function fetchStats() {
  if (!dateRange.value || dateRange.value.length !== 2) return
  loading.value = true
  try {
    const res = await getDesignStats({
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
    })
    const data = res.data || {}
    Object.assign(summary, data.summary || {})
    designerStats.value = data.designer_stats || []
  } catch {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
/* 极光层（.lg-aurora）定位上下文 */
.design-stats-page {
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环 */
.design-stats-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上（点名内容块） */
.design-stats-page .toolbar,
.design-stats-page .summary-cards,
.design-stats-page .section-title,
.design-stats-page .design-stats-panel {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.design-stats-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白（本表无固定列） */
.design-stats-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.toolbar {
  margin-bottom: 20px;
}

.summary-cards {
  margin-bottom: 24px;
}

/* 玻璃质感由 .lg-card 提供（渐变磨砂 + 暖金彩色阴影 + hover 上浮），这里只留布局 */
.stat-card {
  padding: 18px 16px;
  text-align: center;
}

/* 强调卡（总任务数）：金调渐变玻璃（scoped 优先级高于全局 .lg-card） */
.stat-card.emphasis {
  background: linear-gradient(165deg, rgba(255, 255, 255, 0.8) 0%, rgba(245, 203, 92, 0.16) 100%);
  border-color: rgba(212, 148, 28, 0.4);
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}
</style>
