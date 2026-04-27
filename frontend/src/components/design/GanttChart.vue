<template>
  <div class="gantt-wrapper" ref="wrapperRef">
    <!-- Header row: row label + date headers -->
    <div class="gantt-scroll" ref="scrollRef">
      <div class="gantt-grid" :style="gridStyle">
        <!-- Corner cell -->
        <div class="gantt-corner">{{ mode === 'pool' ? '设计组' : '设计师' }}</div>
        <!-- Date headers -->
        <div
          v-for="(d, idx) in dateRange"
          :key="'h-' + d.str"
          class="gantt-date-header"
          :class="{
            'is-weekend': d.isWeekend,
            'is-today': d.isToday,
            'is-unavailable': isUnavailable(d.str),
          }"
        >
          <span class="date-weekday">{{ d.weekday }}</span>
          <span class="date-label">{{ d.dayNum }}</span>
          <span
            v-if="getLoadDot(d.str)"
            class="load-dot"
            :class="getLoadDot(d.str)"
          ></span>
        </div>

        <!-- Pool mode: single row -->
        <template v-if="mode === 'pool'">
          <div class="gantt-row-label">设计组</div>
          <div
            class="gantt-row"
            :style="{ gridColumn: '2 / ' + (dateRange.length + 2) }"
          >
            <div
              v-for="(d, idx) in dateRange"
              :key="'u-' + d.str"
              class="gantt-cell-overlay"
              :class="{
                'is-weekend': d.isWeekend,
                'is-today': d.isToday,
                'is-unavailable': isUnavailable(d.str),
              }"
              :style="{ left: (idx / totalDays * 100) + '%', width: (1 / totalDays * 100) + '%' }"
            ></div>
            <el-popover
              v-for="(task, ti) in allTasks"
              :key="task.task_id"
              placement="top"
              :width="280"
              trigger="hover"
            >
              <template #reference>
                <div
                  class="task-bar"
                  :class="{ 'is-urgent': task.priority === 'urgent', 'is-draggable': draggable }"
                  :style="getTaskBarStyle(task, ti)"
                  @click="$emit('task-click', task)"
                  @mousedown="onTaskMousedown($event, task)"
                >
                  <span class="task-bar-text">{{ task.task_name || task.task_no }}</span>
                </div>
              </template>
              <div class="task-popover">
                <p><strong>任务编号：</strong>{{ task.task_no }}</p>
                <p><strong>客户：</strong>{{ task.customer_name }}</p>
                <p><strong>业务员：</strong>{{ task.salesperson_name }}</p>
                <p><strong>拍摄类型：</strong>{{ shootTypeLabel(task.shoot_type) }}</p>
                <p><strong>优先级：</strong>{{ task.priority === 'urgent' ? '加急' : '普通' }}</p>
                <p><strong>计划日期：</strong>{{ task.plan_start_date }} ~ {{ task.plan_end_date }}</p>
                <p><strong>状态：</strong>
                  <el-tag :type="statusTagType(task.status)" size="small">
                    {{ statusLabel(task.status) }}
                  </el-tag>
                </p>
              </div>
            </el-popover>
          </div>
        </template>

        <!-- Individual mode: one row per designer -->
        <template v-else v-for="designer in designers" :key="designer.id">
          <div class="gantt-row-label">{{ designer.name }}</div>
          <div
            class="gantt-row"
            :style="{ gridColumn: '2 / ' + (dateRange.length + 2) }"
          >
            <div
              v-for="(d, idx) in dateRange"
              :key="'u-' + d.str"
              class="gantt-cell-overlay"
              :class="{
                'is-weekend': d.isWeekend,
                'is-today': d.isToday,
                'is-unavailable': isUnavailable(d.str),
              }"
              :style="{ left: (idx / totalDays * 100) + '%', width: (1 / totalDays * 100) + '%' }"
            ></div>
            <el-popover
              v-for="(task, ti) in getDesignerTasks(designer)"
              :key="task.task_id"
              placement="top"
              :width="280"
              trigger="hover"
            >
              <template #reference>
                <div
                  class="task-bar"
                  :class="{ 'is-urgent': task.priority === 'urgent', 'is-draggable': draggable }"
                  :style="getTaskBarStyle(task, ti)"
                  @click="$emit('task-click', task)"
                  @mousedown="onTaskMousedown($event, task)"
                >
                  <span class="task-bar-text">{{ task.task_name || task.task_no }}</span>
                </div>
              </template>
              <div class="task-popover">
                <p><strong>任务编号：</strong>{{ task.task_no }}</p>
                <p><strong>客户：</strong>{{ task.customer_name }}</p>
                <p><strong>业务员：</strong>{{ task.salesperson_name }}</p>
                <p><strong>拍摄类型：</strong>{{ shootTypeLabel(task.shoot_type) }}</p>
                <p><strong>优先级：</strong>{{ task.priority === 'urgent' ? '加急' : '普通' }}</p>
                <p><strong>计划日期：</strong>{{ task.plan_start_date }} ~ {{ task.plan_end_date }}</p>
                <p><strong>状态：</strong>
                  <el-tag :type="statusTagType(task.status)" size="small">
                    {{ statusLabel(task.status) }}
                  </el-tag>
                </p>
              </div>
            </el-popover>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  designers: { type: Array, default: () => [] },
  startDate: { type: String, required: true },
  endDate: { type: String, required: true },
  unavailableDates: { type: Array, default: () => [] },
  dateLoad: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'individual' }, // 'pool' or 'individual'
  draggable: { type: Boolean, default: false },
})

const emit = defineEmits(['task-click', 'reschedule'])

// --- Date utilities ---
function parseDate(str) {
  const [y, m, d] = str.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function formatDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

const todayStr = formatDate(new Date())

const dateRange = computed(() => {
  const start = parseDate(props.startDate)
  const end = parseDate(props.endDate)
  const dates = []
  const cur = new Date(start)
  while (cur <= end) {
    const str = formatDate(cur)
    const dow = cur.getDay()
    dates.push({
      str,
      display: `${String(cur.getMonth() + 1).padStart(2, '0')}/${String(cur.getDate()).padStart(2, '0')}`,
      dayNum: String(cur.getDate()),
      weekday: WEEKDAYS[dow],
      isWeekend: dow === 0 || dow === 6,
      isToday: str === todayStr,
    })
    cur.setDate(cur.getDate() + 1)
  }
  return dates
})

const totalDays = computed(() => dateRange.value.length)

const displayRows = computed(() => {
  if (props.mode === 'pool') return 1
  return props.designers.length
})

const gridStyle = computed(() => ({
  gridTemplateColumns: `[label-col] 120px repeat(${totalDays.value}, minmax(40px, 1fr))`,
  gridTemplateRows: `auto repeat(${displayRows.value}, minmax(60px, auto))`,
}))

// --- Unavailable check ---
const unavailableSet = computed(() => new Set(props.unavailableDates))

function isUnavailable(dateStr) {
  return unavailableSet.value.has(dateStr)
}

// --- Load dot ---
function getLoadDot(dateStr) {
  const info = props.dateLoad[dateStr]
  if (!info) return null
  const ratio = info.max_capacity > 0 ? info.active_count / info.max_capacity : 0
  if (ratio >= 1) return 'load-red'
  if (ratio >= 0.7) return 'load-yellow'
  return 'load-green'
}

// --- Task positioning ---
function getDesignerTasks(designer) {
  return designer.tasks || []
}

// All tasks across all designers (for pool mode)
const allTasks = computed(() => {
  const tasks = []
  for (const designer of props.designers) {
    if (designer.tasks) {
      tasks.push(...designer.tasks)
    }
  }
  // Also include standalone tasks prop
  if (props.tasks?.length) {
    tasks.push(...props.tasks)
  }
  return tasks
})

function getTaskBarStyle(task, stackIndex = 0) {
  if (!task.plan_start_date || !task.plan_end_date) return { display: 'none' }
  const gridStart = parseDate(props.startDate)
  const taskStart = parseDate(task.plan_start_date)
  const taskEnd = parseDate(task.plan_end_date)
  const total = totalDays.value
  if (total <= 0) return { display: 'none' }

  const startOffset = Math.max(0, (taskStart - gridStart) / 86400000)
  const endOffset = Math.min(total, (taskEnd - gridStart) / 86400000 + 1)
  const span = endOffset - startOffset

  if (span <= 0) return { display: 'none' }

  const left = (startOffset / total) * 100
  const width = (span / total) * 100
  const color = statusColor(task.status)

  // Stack bars vertically: 28px height + 2px gap
  const top = 2 + stackIndex * (28 + 2)

  return {
    left: left + '%',
    width: width + '%',
    top: top + 'px',
    backgroundColor: color,
  }
}

// --- Status helpers ---
const STATUS_COLORS = {
  pending_design: '#E6A23C',
  scheduled: '#409EFF',
  in_progress: '#F56C6C',
  completed: '#67C23A',
  cancelled: '#909399',
}

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

const SHOOT_TYPE_LABELS = {
  product_photo: '产品图',
  model_photo: '模特图',
  video: '视频',
  product_video: '产品视频',
  other: '其他',
}

function statusColor(status) {
  return STATUS_COLORS[status] || '#409EFF'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function statusTagType(status) {
  return STATUS_TAG_TYPES[status] || ''
}

function shootTypeLabel(type) {
  return SHOOT_TYPE_LABELS[type] || type || ''
}

// --- Drag-to-reschedule ---
const scrollRef = ref(null)
const dragState = ref(null) // { task, startX, barEl, origLeft, cellWidth, duration }

function onTaskMousedown(event, task) {
  if (!props.draggable) return
  if (event.button !== 0) return // left button only
  event.preventDefault()
  event.stopPropagation()

  const barEl = event.currentTarget
  const rowEl = barEl.closest('.gantt-row')
  if (!rowEl) return

  const rowRect = rowEl.getBoundingClientRect()
  const cellWidth = rowRect.width / totalDays.value

  // Calculate task duration in days
  const taskStart = parseDate(task.plan_start_date)
  const taskEnd = parseDate(task.plan_end_date)
  const duration = Math.round((taskEnd - taskStart) / 86400000) // days between start and end

  dragState.value = {
    task,
    startX: event.clientX,
    barEl,
    origTransform: barEl.style.transform || '',
    cellWidth,
    duration,
    rowWidth: rowRect.width,
    origLeft: parseFloat(barEl.style.left), // percentage
  }

  barEl.classList.add('is-dragging')
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(event) {
  if (!dragState.value) return
  const { startX, barEl, cellWidth } = dragState.value
  const dx = event.clientX - startX

  // Snap to cell boundaries
  const cellOffset = Math.round(dx / cellWidth)
  const snappedDx = cellOffset * cellWidth

  barEl.style.transform = `translateX(${snappedDx}px)`
}

function onDragEnd(event) {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)

  if (!dragState.value) return
  const { task, startX, barEl, cellWidth, duration } = dragState.value
  const dx = event.clientX - startX
  const cellOffset = Math.round(dx / cellWidth)

  // Reset visual state
  barEl.style.transform = ''
  barEl.classList.remove('is-dragging')

  if (cellOffset === 0) {
    dragState.value = null
    return
  }

  // Calculate new dates
  const origStart = parseDate(task.plan_start_date)
  const newStart = new Date(origStart)
  newStart.setDate(newStart.getDate() + cellOffset)
  const newEnd = new Date(newStart)
  newEnd.setDate(newEnd.getDate() + duration)

  // Bounds check: new dates must stay within the gantt range
  const rangeStart = parseDate(props.startDate)
  const rangeEnd = parseDate(props.endDate)
  if (newStart < rangeStart || newEnd > rangeEnd) {
    dragState.value = null
    return
  }

  emit('reschedule', {
    taskId: task.task_id,
    planStartDate: formatDate(newStart),
    planEndDate: formatDate(newEnd),
    task,
  })

  dragState.value = null
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})
</script>

<style scoped>
.gantt-wrapper {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.gantt-scroll {
  overflow-x: auto;
  overflow-y: auto;
  max-height: 600px;
}

.gantt-grid {
  display: grid;
  min-width: max-content;
}

/* Corner cell */
.gantt-corner {
  position: sticky;
  left: 0;
  z-index: 3;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
  border-right: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  padding: 8px;
}

/* Date headers */
.gantt-date-header {
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 2px;
  font-size: 12px;
  color: #606266;
  position: relative;
  min-width: 40px;
}

.gantt-date-header.is-weekend {
  background: #f5f5f5;
}

.gantt-date-header.is-today {
  border-bottom: 2px solid var(--color-gold, #e6a23c);
}

.gantt-date-header.is-unavailable {
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 3px,
    rgba(144, 147, 153, 0.12) 3px,
    rgba(144, 147, 153, 0.12) 6px
  );
}

.date-label {
  font-weight: 600;
  line-height: 1.2;
}

.date-weekday {
  font-size: 11px;
  color: #909399;
  line-height: 1.2;
}

/* Load dots */
.load-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 2px;
}

.load-dot.load-green {
  background: #67C23A;
}

.load-dot.load-yellow {
  background: #E6A23C;
}

.load-dot.load-red {
  background: #F56C6C;
}

/* Row label */
.gantt-row-label {
  position: sticky;
  left: 0;
  z-index: 2;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
}

/* Row content */
.gantt-row {
  position: relative;
  border-bottom: 1px solid #ebeef5;
  min-height: 60px;
}

/* Cell overlays for unavailable / weekend / today */
.gantt-cell-overlay {
  position: absolute;
  top: 0;
  bottom: 0;
  pointer-events: none;
}

.gantt-cell-overlay.is-weekend {
  background: rgba(250, 245, 232, 0.4);
}

.gantt-cell-overlay.is-today {
  border-left: 2px solid var(--color-gold, #e6a23c);
}

.gantt-cell-overlay.is-unavailable {
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 3px,
    rgba(144, 147, 153, 0.12) 3px,
    rgba(144, 147, 153, 0.12) 6px
  );
}

/* Task bar */
.task-bar {
  position: absolute;
  height: 28px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  line-height: 28px;
  padding: 0 8px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  z-index: 1;
  transition: filter 0.15s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}

.task-bar.is-urgent {
  border-left: 3px solid #F56C6C;
}

.task-bar:hover {
  filter: brightness(1.1);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.18);
}

.task-bar.is-draggable {
  cursor: grab;
}

.task-bar.is-draggable:active {
  cursor: grabbing;
}

.task-bar.is-dragging {
  opacity: 0.85;
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  outline: 2px dashed #409EFF;
  outline-offset: 1px;
  cursor: grabbing;
  user-select: none;
}

.task-bar-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Popover content */
.task-popover p {
  margin: 4px 0;
  font-size: 13px;
  color: #303133;
  line-height: 1.6;
}
</style>
