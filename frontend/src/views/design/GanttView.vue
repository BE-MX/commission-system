<template>
  <div>
    <!-- Toolbar -->
    <div class="gantt-toolbar">
      <div class="toolbar-left">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          :clearable="false"
          style="width: 280px"
          @change="fetchData"
        />
        <el-select
          v-model="selectedDesigners"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="筛选设计师"
          clearable
          style="width: 220px"
          @change="fetchData"
        >
          <el-option
            v-for="d in allDesigners"
            :key="d.id"
            :label="d.name"
            :value="d.id"
          />
        </el-select>
        <GlassButton :icon="Refresh" @click="fetchData">刷新</GlassButton>
      </div>
      <div class="toolbar-right">
        <GlassButton :icon="Download" @click="handleExport" :loading="exporting">导出 Excel</GlassButton>
      </div>
    </div>

    <!-- Legend -->
    <div class="gantt-legend">
      <span class="legend-item" v-for="item in legendItems" :key="item.status">
        <span class="legend-icon-wrap" :style="{ backgroundColor: item.color }">
          <el-icon :size="12"><component :is="item.icon" /></el-icon>
        </span>
        {{ item.label }}
      </span>
    </div>

    <!-- Gantt chart -->
    <GanttChart
      v-if="ganttData.designers.length > 0"
      :designers="ganttData.designers"
      :start-date="dateRange[0]"
      :end-date="dateRange[1]"
      :unavailable-dates="ganttData.unavailable_dates"
      :date-load="ganttData.date_load"
      @task-click="onTaskClick"
    />
    <el-empty v-else-if="!loading" description="暂无排期数据" />

    <!-- Task detail dialog -->
    <el-dialog
      v-model="detailVisible"
      title="任务详情"
      width="480px"
      :close-on-click-modal="true"
    >
      <template v-if="selectedTask">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="任务编号">{{ selectedTask.task_no }}</el-descriptions-item>
          <el-descriptions-item label="任务名称">{{ selectedTask.task_name }}</el-descriptions-item>
          <el-descriptions-item label="客户">{{ selectedTask.customer_name }}</el-descriptions-item>
          <el-descriptions-item label="业务员">{{ selectedTask.salesperson_name }}</el-descriptions-item>
          <el-descriptions-item label="拍摄类型">{{ selectedTask.shoot_type }}</el-descriptions-item>
          <el-descriptions-item label="优先级">
            <el-tag :type="selectedTask.priority === 'urgent' ? 'danger' : ''">
              {{ selectedTask.priority === 'urgent' ? '加急' : '普通' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="计划开始">{{ selectedTask.plan_start_date }} {{ periodLabel(selectedTask.plan_start_period) }}</el-descriptions-item>
          <el-descriptions-item label="计划结束">{{ selectedTask.plan_end_date }} {{ periodLabel(selectedTask.plan_end_period) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(selectedTask.status)" size="small">
              {{ statusLabel(selectedTask.status) }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Refresh, Download, Clock, Calendar, VideoPlay, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getGanttData, getDesigners } from '@/api/design'
import GanttChart from '@/components/design/GanttChart.vue'

// --- Default date range: today ±7 days ---
function getDefaultDateRange() {
  const now = new Date()
  const start = new Date(now)
  start.setDate(now.getDate() - 7)
  const end = new Date(now)
  end.setDate(now.getDate() + 7)
  return [formatDate(start), formatDate(end)]
}

function formatDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const dateRange = ref(getDefaultDateRange())
const selectedDesigners = ref([])
const allDesigners = ref([])
const loading = ref(false)
const exporting = ref(false)

const ganttData = ref({
  designers: [],
  unavailable_dates: [],
  capacity_map: {},
  date_load: {},
})

const STATUS_ICONS = {
  pending_design: Clock,
  scheduled: Calendar,
  in_progress: VideoPlay,
  completed: CircleCheck,
  cancelled: CircleClose,
}

const legendItems = [
  { status: 'pending_design', color: 'rgba(212,148,28,0.7)', icon: Clock, label: '待设计' },
  { status: 'scheduled', color: 'rgba(212,148,28,0.7)', icon: Calendar, label: '已排期' },
  { status: 'in_progress', color: 'rgba(220,53,69,0.7)', icon: VideoPlay, label: '进行中' },
  { status: 'completed', color: 'rgba(45,159,111,0.7)', icon: CircleCheck, label: '已完成' },
  { status: 'cancelled', color: 'rgba(156,149,144,0.7)', icon: CircleClose, label: '已取消' },
]

// --- Status helpers ---
const STATUS_LABELS = {
  pending_design: '待设计',
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}

const STATUS_TAG_TYPES = {
  pending_design: 'warning',
  scheduled: '',
  in_progress: 'danger',
  completed: 'success',
  cancelled: 'info',
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function statusTagType(status) {
  return STATUS_TAG_TYPES[status] || ''
}

const PERIOD_LABELS = { am: '上午', pm: '下午' }
function periodLabel(p) { return PERIOD_LABELS[p] || '' }

// --- Task detail dialog ---
const detailVisible = ref(false)
const selectedTask = ref(null)

function onTaskClick(task) {
  selectedTask.value = task
  detailVisible.value = true
}

// --- Data fetching ---
async function fetchDesigners() {
  try {
    const res = await getDesigners()
    allDesigners.value = res.data || []
  } catch {
    // ignore
  }
}

async function fetchData() {
  if (!dateRange.value || dateRange.value.length !== 2) return
  loading.value = true
  try {
    const params = {
      start_date: dateRange.value[0],
      end_date: dateRange.value[1],
    }
    if (selectedDesigners.value.length > 0) {
      params.designer_id = selectedDesigners.value.join(',')
    }
    const res = await getGanttData(params)
    ganttData.value = {
      designers: res.data?.designers || [],
      unavailable_dates: res.data?.unavailable_dates || [],
      capacity_map: res.data?.capacity_map || {},
      date_load: res.data?.date_load || {},
    }
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

// --- Export ---
async function handleExport() {
  if (!dateRange.value || dateRange.value.length !== 2) return
  exporting.value = true
  try {
    const url = `/api/design/export/tasks?start_date=${dateRange.value[0]}&end_date=${dateRange.value[1]}`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error('导出失败')
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const disposition = resp.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename\*?=(?:UTF-8'')?(.+)/i)
    a.download = match ? decodeURIComponent(match[1]) : `design_tasks_${dateRange.value[0]}_${dateRange.value[1]}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(a.href)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  fetchDesigners()
  fetchData()
})
</script>

<style scoped>
.gantt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gantt-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--toolbar-bg);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-secondary);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  color: #fff;
}
</style>
